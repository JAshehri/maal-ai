from __future__ import annotations

import re
from pathlib import Path

from . import db
from .retrieval import retrieve_related_clauses
from .schemas import ChangeType, Obligation, Provenance, RegulatoryChange, Threshold
from .settings import settings


THRESHOLD_RE = re.compile(
    r"(?P<operator><=|>=|<|>|not exceed(?:ing)?|maximum(?: of)?|minimum(?: of)?)\s*"
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>mg/Nm3|mg/m3|ppm|%|tons/year)",
    re.IGNORECASE,
)


def _modality(text: str) -> str:
    lower = text.casefold()
    if "may allow" in lower or "يجوز" in lower:
        return "permission_option"
    if "prohibited" in lower or "must not" in lower or "يحظر" in lower:
        return "prohibited"
    if "required" in lower or "يتطلب" in lower:
        return "required"
    if "must" in lower or "shall" in lower or "يجب" in lower:
        return "must"
    return "unknown"


def _threshold(text: str) -> Threshold | None:
    match = THRESHOLD_RE.search(text)
    if not match:
        return None
    raw = match.group("operator").casefold()
    operator = "<=" if raw in {"not exceed", "not exceeding", "maximum", "maximum of", "<="} else raw
    if raw in {"minimum", "minimum of"}:
        operator = ">="
    return Threshold(
        operator=operator,
        value=float(match.group("value")),
        unit=match.group("unit"),
        averaging_period="quarterly average" if "quarter" in text.casefold() else None,
        measurement_basis="dry gas at reference conditions" if "reference conditions" in text.casefold() else None,
    )


def extract_obligation_from_change(
    change: RegulatoryChange,
    *,
    run_id: str,
    company_id: str,
    model_id: str,
    db_path: Path | str | None = None,
) -> Obligation | None:
    if not change.substantive or change.change_type == ChangeType.deleted or not change.after_clause_id:
        return None
    clause = db.get_clause(change.after_clause_id, db_path)
    if not clause:
        raise KeyError(change.after_clause_id)
    text = clause.text
    modality = _modality(text)
    if modality == "unknown" and change.change_type not in {ChangeType.numeric_threshold, ChangeType.deadline, ChangeType.scope}:
        return None
    related = retrieve_related_clauses(clause, db_path)
    version = db.get_document_version(change.new_version_id, db_path) or {}
    exceptions = [line.strip() for line in text.splitlines() if "except" in line.casefold() or "استثناء" in line]
    conditions: list[str] = []
    lower = text.casefold()
    if "stationary source" in lower:
        conditions.append("company operates a stationary emission source")
    if "marine discharge" in lower:
        conditions.append("company performs marine discharge activity")
    if "if " in lower:
        conditions.append(text[text.casefold().find("if "):].strip())
    obligation_key = db.stable_id("oblkey", clause.article_ref, text)
    provenance = Provenance(
        run_id=run_id,
        company_id=company_id,
        source_id=change.source_id,
        version_id=change.new_version_id,
        model_id=model_id,
        prompt_version=settings.prompt_version,
        schema_version=settings.schema_version,
    )
    return Obligation(
        obligation_id=db.stable_id("obl", run_id, change.change_id, obligation_key),
        obligation_key=obligation_key,
        provenance=provenance,
        clause_id=clause.clause_id,
        change_id=change.change_id,
        article_ref=clause.article_ref,
        quote=text,
        actor="facility" if "facility" in lower else None,
        action=text,
        modality=modality,
        applicability_conditions=conditions,
        exceptions=exceptions,
        related_clause_ids=[item.clause_id for item in related],
        effective_at=version.get("effective_at"),
        citation_ids=[clause.clause_id],
        threshold=_threshold(text),
    )


def extract_affected_obligations(
    changes: list[RegulatoryChange],
    *,
    run_id: str,
    company_id: str,
    model_id: str,
    db_path: Path | str | None = None,
) -> list[Obligation]:
    result: list[Obligation] = []
    for change in changes:
        item = extract_obligation_from_change(
            change, run_id=run_id, company_id=company_id, model_id=model_id, db_path=db_path
        )
        if item:
            result.append(db.insert_obligation(item, db_path))
    return result


def extract_obligations(regulation_text: str) -> list[dict]:
    """Compatibility adapter: returns deterministic clause candidates without external calls."""
    from .ingestion import extract_clauses
    clauses = extract_clauses("adhoc", regulation_text)
    return [{"article_ref": clause.article_ref, "quote": clause.text} for clause in clauses]
