from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import db
from .change_detection import compare_versions
from .company_documents import ingest_company_document
from .demo import seed_demo
from .pipeline import create_run, execute_run
from .schemas import ComplianceReviewCreate, FinancialInput, RunCreate
from .settings import settings


STATUS_FACTOR = {
    "compliant": 1.0,
    "partially_compliant": 0.5,
    "non_compliant": 0.0,
    "needs_review": None,
    "insufficient_evidence": None,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _numbers(text: str | None) -> list[float]:
    return [float(x) for x in re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?", text or "")]


def _requirement_numbers(text: str | None) -> list[float]:
    values = _numbers(text)
    return values[1:] if values and re.search(r"(?:Article|المادة)\s+\d", text or "", re.I) else values


def _active_changes(db_path=None) -> list[dict[str, Any]]:
    now = _now()
    with db.connect(db_path) as connection:
        rows = connection.execute(
            """SELECT w.*, c.change_type, c.before_clause_id, c.after_clause_id,
                      c.before_text, c.after_text, s.authority, s.canonical_url
                 FROM regulation_watch_windows w
                 JOIN regulatory_changes c USING(change_id)
                 JOIN sources s USING(source_id)
                WHERE w.status='active' AND w.starts_at<=? AND w.expires_at>=?
                ORDER BY w.starts_at DESC""", (now, now)
        ).fetchall()
    return [dict(row) for row in rows]


def seed_core_demo(db_path: Path | str | None = None) -> dict[str, Any]:
    context = seed_demo(db_path)
    changes = compare_versions(context["old_version_id"], context["new_version_id"], db_path)
    run, created = create_run(RunCreate(
        company_snapshot_id=context["company_snapshot_id"],
        old_version_id=context["old_version_id"], new_version_id=context["new_version_id"],
        idempotency_key="core-differentiator-demo-v1",
    ), db_path)
    if created or run["phase"] not in {"awaiting_review", "completed"}:
        execute_run(run["run_id"], db_path=db_path)
    obligations = {item.article_ref: item for item in db.list_obligations(run["run_id"], db_path)}

    demo_dir = settings.root_dir / "data" / "demo"
    policy = ingest_company_document(
        raw=(demo_dir / "internal_emissions_policy.txt").read_bytes(),
        filename="internal_emissions_policy.txt", mime_type="text/plain",
        company_snapshot_id=context["company_snapshot_id"], document_kind="policy",
        title="سياسة التحكم في الانبعاثات — بيانات ديمو اصطناعية",
        department="Environmental Engineering", project_id="Advanced Manufacturing Expansion",
        db_path=db_path,
    )
    policy_doc = policy["document"]
    policy_chunk = next(c for c in policy["chunks"] if "100 mg/Nm3" in c["text"])
    old_clauses = {c.article_ref: c for c in db.list_clauses(context["old_version_id"], db_path)}
    obligation = obligations.get("Article 5.1")
    if obligation and "Article 5.1" in old_clauses:
        db.insert_dependency({
            "company_id": policy_doc["company_id"], "company_document_id": policy_doc["company_document_id"],
            "chunk_id": policy_chunk["chunk_id"], "source_id": context["source_id"],
            "version_id": context["old_version_id"], "clause_id": old_clauses["Article 5.1"].clause_id,
            "obligation_id": obligation.obligation_id, "obligation_key": obligation.obligation_key,
            "article_ref": "Article 5.1", "department": "Environmental Engineering",
            "project_id": "Advanced Manufacturing Expansion", "relationship_type": "depends_on",
        }, db_path)

    now = datetime.now(timezone.utc)
    for change in changes:
        if not change.substantive:
            continue
        with db.connect(db_path) as connection:
            connection.execute(
                """INSERT OR IGNORE INTO regulation_watch_windows
                   (watch_id, change_id, source_id, old_version_id, new_version_id, article_ref,
                    old_requirement_text, new_requirement_text, starts_at, expires_at, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')""",
                (db.stable_id("watch", change.change_id), change.change_id, change.source_id,
                 change.old_version_id, change.new_version_id, change.article_ref,
                 change.before_text, change.after_text, now.isoformat(), (now + timedelta(days=30)).isoformat()),
            )
    db.upsert_financial_input(FinancialInput(
        company_snapshot_id=context["company_snapshot_id"], currency="SAR",
        remediation_cost=120000, project_delay_daily_cost=15000, expected_delay_days=10,
        downtime_hourly_cost=5000, expected_downtime_hours=8, contract_exposure=75000,
        is_synthetic=True,
        label="Synthetic demo company inputs — not actual company data and not a regulatory penalty",
    ), db_path)
    return {**context, "pipeline_run_id": run["run_id"],
            "policy_document_id": policy_doc["company_document_id"],
            "dependencies": db.list_dependencies(company_document_id=policy_doc["company_document_id"], db_path=db_path)}


def _financial_exposure(review_id: str, snapshot_id: str, change_id: str | None, db_path=None) -> dict[str, Any]:
    item = db.get_financial_input(snapshot_id, db_path)
    if not item:
        return {"status": "not_enough_data", "message": "Not enough data"}
    breakdown: dict[str, Any] = {
        "direct_regulatory_penalty": {"status": "not_enough_data", "value": None,
            "reason": "No official penalty citation is present in the retrieved regulation."},
        "remediation_cost": item["remediation_cost"],
        "project_delay_exposure": (item["project_delay_daily_cost"] * item["expected_delay_days"]
                                   if item["project_delay_daily_cost"] is not None and item["expected_delay_days"] is not None else None),
        "downtime_exposure": (item["downtime_hourly_cost"] * item["expected_downtime_hours"]
                              if item["downtime_hourly_cost"] is not None and item["expected_downtime_hours"] is not None else None),
        "contract_exposure": item["contract_exposure"],
    }
    total = sum(v for v in breakdown.values() if isinstance(v, (int, float)))
    formula = {
        "remediation_cost": "input.remediation_cost",
        "project_delay_exposure": "input.project_delay_daily_cost × input.expected_delay_days",
        "downtime_exposure": "input.downtime_hourly_cost × input.expected_downtime_hours",
        "contract_exposure": "input.contract_exposure",
        "total": "sum(available non-penalty exposure components)",
    }
    exposure_id = db.stable_id("exposure", review_id)
    with db.connect(db_path) as connection:
        connection.execute(
            """INSERT OR REPLACE INTO financial_exposures
               (exposure_id, compliance_review_id, change_id, status, currency, total,
                breakdown_json, formula_json, is_synthetic, created_at)
               VALUES (?, ?, ?, 'calculated_from_synthetic_inputs', ?, ?, ?, ?, 1, ?)""",
            (exposure_id, review_id, change_id, item["currency"], total,
             _json(breakdown), _json(formula), _now()),
        )
    return {"status": "calculated_from_synthetic_inputs", "currency": item["currency"],
            "total": total, "breakdown": breakdown, "formula": formula, "is_synthetic": True,
            "label": item["label"]}


def create_compliance_review(request: ComplianceReviewCreate, db_path=None) -> dict[str, Any]:
    db.init_db(db_path)
    document = db.get_company_document(request.company_document_id, db_path)
    snapshot = db.get_company_snapshot(request.company_snapshot_id, db_path)
    if not document or not snapshot:
        raise KeyError("company document or snapshot not found")
    if document["company_snapshot_id"] != request.company_snapshot_id:
        raise ValueError("document does not belong to company snapshot")
    request_hash = hashlib.sha256(_json(request.model_dump(mode="json")).encode()).hexdigest()
    review_id = db.stable_id("creview", request.idempotency_key)
    with db.connect(db_path) as connection:
        existing = connection.execute(
            "SELECT compliance_review_id, request_hash FROM compliance_reviews WHERE idempotency_key=?",
            (request.idempotency_key,),
        ).fetchone()
        if existing:
            if existing["request_hash"] != request_hash:
                raise ValueError("idempotency key was already used with a different request")
            return db.get_compliance_review(existing["compliance_review_id"], db_path)
        connection.execute(
            """INSERT INTO compliance_reviews
               (compliance_review_id, company_document_id, company_snapshot_id, company_id,
                idempotency_key, request_hash, status, assessed_weight, summary_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'running', 0, '{}', ?)""",
            (review_id, request.company_document_id, request.company_snapshot_id,
             document["company_id"], request.idempotency_key, request_hash, _now()),
        )

    chunks = db.list_company_document_chunks(request.company_document_id, db_path)
    findings, weighted, assessed = [], 0.0, 0.0
    for change in _active_changes(db_path):
        old_numbers, new_numbers = _requirement_numbers(change["before_text"]), _requirement_numbers(change["after_text"])
        old_value = old_numbers[-1] if old_numbers else None
        new_value = new_numbers[-1] if new_numbers else None
        match = next((c for c in chunks if change["article_ref"] in c["text"] and old_value is not None
                      and re.search(rf"(?<![\d.]){re.escape(f'{old_value:g}')}(?![\d.])", c["text"])), None)
        if match:
            status, factor = "non_compliant", 0.0
            rationale = "The uploaded document cites the superseded threshold during the active 30-day watch window."
            warning = "recently_superseded_requirement"
        else:
            match = next((c for c in chunks if change["article_ref"] in c["text"]), None)
            if not match:
                continue
            has_new = new_value is not None and re.search(rf"(?<![\d.]){re.escape(f'{new_value:g}')}(?![\d.])", match["text"])
            status, factor = ("compliant", 1.0) if has_new else ("partially_compliant", 0.5)
            rationale = "The cited article was checked against the current requirement."
            warning = None
        weight = 3.0 if change["change_type"] in {"numeric_threshold", "deadline", "scope"} else 2.0
        assessed += weight; weighted += weight * factor
        requirement_id = db.stable_id("req", change["change_id"])
        recommended = (f"Replace the superseded {change['article_ref']} requirement with the current text: "
                       f"{change['after_text']}") if status != "compliant" else None
        finding_id = db.stable_id("crf", review_id, requirement_id)
        with db.connect(db_path) as connection:
            connection.execute(
                """INSERT INTO compliance_review_findings
                   (review_finding_id, compliance_review_id, requirement_id, source_id, version_id,
                    clause_id, change_id, article_ref, status, severity, weight, score_factor,
                    company_chunk_id, locator_json, document_quote, regulatory_quote, rationale,
                    recommended_fix, warning_code, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'high', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (finding_id, review_id, requirement_id, change["source_id"], change["new_version_id"],
                 change["after_clause_id"], change["change_id"], change["article_ref"], status,
                 weight, factor, match["chunk_id"], _json(match["locator"]), match["text"],
                 change["after_text"], rationale, recommended, warning, _now()),
            )
        findings.append({"status": status, "change_id": change["change_id"]})
        old_clause = db.get_clause(change["before_clause_id"], db_path) if change["before_clause_id"] else None
        if status == "non_compliant" and old_clause:
            db.insert_dependency({
                "company_id": document["company_id"], "company_document_id": document["company_document_id"],
                "chunk_id": match["chunk_id"], "source_id": change["source_id"],
                "version_id": change["old_version_id"], "clause_id": old_clause.clause_id,
                "obligation_key": requirement_id, "article_ref": change["article_ref"],
                "department": document.get("department") or "Needs Review",
                "project_id": document.get("project_id"), "relationship_type": "superseded_reference",
            }, db_path)

    score = round(weighted / assessed * 100, 1) if assessed else None
    overall = "completed" if findings else "needs_review"
    summary = {"requirements_assessed": len(findings), "warning":
               "Recently superseded requirement detected" if any(f["status"] == "non_compliant" for f in findings) else None,
               "score_method": "weighted deterministic requirement score"}
    with db.connect(db_path) as connection:
        connection.execute(
            """UPDATE compliance_reviews SET status=?, weighted_score=?, assessed_weight=?,
               summary_json=?, completed_at=? WHERE compliance_review_id=?""",
            (overall, score, assessed, _json(summary), _now(), review_id),
        )
    if any(f["status"] in {"non_compliant", "partially_compliant"} for f in findings):
        _financial_exposure(review_id, request.company_snapshot_id, findings[0]["change_id"], db_path)
    return db.get_compliance_review(review_id, db_path)


def impact_graph(db_path=None) -> dict[str, Any]:
    dependencies = db.list_dependencies(db_path=db_path)
    nodes, edges = {}, []
    for dep in dependencies:
        locator = dep.get("locator") or {}
        section_label = dep.get("section_ref")
        if not section_label:
            if locator.get("page"):
                section_label = f"Page {locator['page']}"
            elif locator.get("slide"):
                section_label = f"Slide {locator['slide']}"
            elif locator.get("sheet") and locator.get("cell"):
                section_label = f"{locator['sheet']} · {locator['cell']}"
            elif locator.get("line_start"):
                section_label = f"Line {locator['line_start']}"
            else:
                section_label = "Document section"
        chain = [
            (f"source:{dep['source_id']}", "Regulation", dep["authority"]),
            (f"article:{dep['version_id']}:{dep['article_ref']}", "Article", dep["article_ref"]),
            (f"obligation:{dep['obligation_key']}", "Obligation", f"Requirement — {dep['article_ref']}"),
            (f"document:{dep['company_document_id']}", "Internal Document", dep["document_title"]),
            (f"chunk:{dep['chunk_id']}", "Section", section_label),
            (f"department:{dep['department']}", "Department", dep["department"]),
        ]
        if dep.get("project_id"):
            chain.append((f"project:{dep['project_id']}", "Project", dep["project_id"]))
        for node_id, kind, label in chain:
            nodes[node_id] = {"id": node_id, "type": kind, "label": label}
        edges.extend({"from": chain[i][0], "to": chain[i + 1][0],
                      "relationship": dep["relationship_type"]} for i in range(len(chain) - 1))
    return {"nodes": list(nodes.values()), "edges": edges, "dependencies": dependencies}


def ui_overview(db_path=None) -> dict[str, Any]:
    """Build a sanitized, presentation-focused view without changing compliance logic."""
    context = seed_core_demo(db_path)
    bundle = db.fetch_run_bundle(context["pipeline_run_id"], db_path)
    source = db.get_source(context["source_id"], db_path) or {}
    new_version = db.get_document_version(context["new_version_id"], db_path) or {}
    obligations = {item["change_id"]: item for item in bundle["obligations"]}
    findings = {item["change_id"]: item for item in bundle["findings"]}
    tasks_by_finding = {item["finding_id"]: item for item in bundle["tasks"]}
    dependencies = db.list_dependencies(db_path=db_path)
    departments = sorted({item["department"] for item in dependencies if item.get("department")})
    financial = db.get_financial_input(context["company_snapshot_id"], db_path)
    exposure_total = None
    if financial:
        components = [financial.get("remediation_cost"), financial.get("contract_exposure")]
        if financial.get("project_delay_daily_cost") is not None and financial.get("expected_delay_days") is not None:
            components.append(financial["project_delay_daily_cost"] * financial["expected_delay_days"])
        if financial.get("downtime_hourly_cost") is not None and financial.get("expected_downtime_hours") is not None:
            components.append(financial["downtime_hourly_cost"] * financial["expected_downtime_hours"])
        exposure_total = sum(value for value in components if value is not None)

    change_rows = []
    for change in bundle["changes"]:
        obligation = obligations.get(change["change_id"])
        finding = findings.get(change["change_id"])
        applicability = db.get_applicability(context["pipeline_run_id"], obligation["obligation_id"], db_path) if obligation else None
        task = tasks_by_finding.get(finding["finding_id"]) if finding else None
        dep = next((item for item in dependencies if item["article_ref"] == change["article_ref"]), None)
        change_rows.append({
            "regulation_name": source.get("title", "Regulation"),
            "authority": source.get("authority", "—"), "jurisdiction": source.get("jurisdiction", "SA"),
            "domain": source.get("regulatory_domain") or "Environmental compliance",
            "published_date": new_version.get("published_at"), "effective_date": new_version.get("effective_at"),
            "article": change["article_ref"], "change_type": change["change_type"],
            "old_text": change.get("before_text"), "current_text": change.get("after_text"),
            "has_previous_version": change.get("before_text") is not None,
            "applicability": applicability.status.value if applicability else "needs_review",
            "applicability_reason": applicability.rationale_summary if applicability else "Additional company facts are required.",
            "priority": finding["priority"] if finding else "pending_review",
            "department": dep["department"] if dep else "Compliance",
            "estimated_exposure": exposure_total if change["article_ref"] == "Article 5.1" else None,
            "currency": financial.get("currency") if financial else None,
            "recommended_action": task["action"] if task else "Review the changed requirement and confirm affected internal controls.",
            "substantive": bool(change["substantive"]),
        })

    now = _now()
    with db.connect(db_path) as connection:
        watches = [dict(row) for row in connection.execute(
            """SELECT article_ref, starts_at, expires_at, old_requirement_text, new_requirement_text
                 FROM regulation_watch_windows WHERE status='active' AND expires_at>=?
                 ORDER BY starts_at DESC""", (now,)
        ).fetchall()]
        latest_scan = connection.execute(
            """SELECT r.scan_id FROM regulatory_scan_runs r
                 WHERE r.status IN ('completed','completed_with_errors')
                   AND EXISTS (SELECT 1 FROM scan_document_results d WHERE d.scan_id=r.scan_id)
                 ORDER BY r.started_at DESC LIMIT 1"""
        ).fetchone()
    official_items = []
    if latest_scan:
        for item in db.get_scan_results(latest_scan["scan_id"], db_path):
            if item["applicability_status"] == "not_applicable":
                continue
            doc = db.get_regulatory_document(item["document_id"], db_path)
            official_items.append({
                "regulation_name": item["title"], "authority": item["authority"],
                "jurisdiction": doc.jurisdiction if doc else "SA",
                "domain": doc.regulatory_domain if doc else "—",
                "published_date": doc.publication_date.isoformat() if doc and doc.publication_date else None,
                "effective_date": doc.mandatory_application_date.isoformat() if doc and doc.mandatory_application_date else None,
                "article": None, "change_type": item["outcome"], "old_text": None,
                "current_text": None, "has_previous_version": bool(item.get("previous_version_id")),
                "applicability": item["applicability_status"],
                "applicability_reason": item["applicability_rationale"], "priority": item["priority"],
                "department": ", ".join(item["department_ids"]) or "Compliance",
                "estimated_exposure": None, "currency": None,
                "recommended_action": "Review the current official regulation against the relevant product and activity scope.",
                "substantive": item["outcome"] in {"new", "changed"},
                "canonical_url": item["canonical_url"],
            })

    high_priority = sum(1 for item in bundle["findings"] if item["priority"] == "high")
    pending_tasks = [item for item in bundle["tasks"] if item["review_status"] == "pending_human_review"]
    task_views = []
    for item in bundle["tasks"]:
        reviews = db.list_reviews(item["task_id"], db_path)
        task_views.append({
            "task_id": item["task_id"], "action": item["action"], "owner_role": item.get("owner_role"),
            "proposed_due_date": item.get("proposed_due_date"), "review_status": item["review_status"],
            "revision": item["revision"],
            "reviews": [{"decision": review["decision"], "comment": review["comment"],
                         "reviewer": review["reviewer_id"], "created_at": review["created_at"]}
                        for review in reviews],
        })
    graph = impact_graph(db_path)
    graph_nodes = [{"type": node["type"], "label": node["label"]} for node in graph["nodes"]]
    return {
        "summary": {"regulatory_updates": sum(1 for item in change_rows if item["substantive"]),
                    "high_priority_issues": high_priority, "affected_departments": len(departments),
                    "estimated_financial_exposure": exposure_total, "currency": financial.get("currency") if financial else None},
        "changes": change_rows, "official_regulations": official_items[:40],
        "watch_windows": watches,
        "traceability": {"nodes": graph_nodes},
        "financial": {
            "remediation": financial.get("remediation_cost") if financial else None,
            "project_delay": financial["project_delay_daily_cost"] * financial["expected_delay_days"] if financial and financial.get("project_delay_daily_cost") is not None and financial.get("expected_delay_days") is not None else None,
            "downtime": financial["downtime_hourly_cost"] * financial["expected_downtime_hours"] if financial and financial.get("downtime_hourly_cost") is not None and financial.get("expected_downtime_hours") is not None else None,
            "contractual": financial.get("contract_exposure") if financial else None,
            "direct_penalty": None, "total": exposure_total,
            "currency": financial.get("currency") if financial else None, "is_estimate": True,
        },
        "human_review": {"tasks": task_views, "pending_count": len(pending_tasks),
                         "audit_events": bundle["audit_events"]},
    }
