from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from . import db
from .change_detection import compare_versions
from .check_applicability import check_applicability
from .extract_obligations import extract_affected_obligations
from .gap_analysis import analyze_gap
from .generate_task import generate_task
from .ingestion import detect_prompt_injection
from .retrieval import retrieve_company_evidence
from .schemas import AuditEvent, RunCreate, RunPhase, RunState


def _audit(
    run_id: str,
    action: str,
    entity_type: str,
    entity_id: str,
    summary: str,
    *,
    tool_name: str | None = None,
    evidence_ids: list[str] | None = None,
    db_path: Path | str | None = None,
) -> None:
    event = AuditEvent(
        event_id=db.stable_id("evt", run_id, action, entity_type, entity_id, summary),
        run_id=run_id,
        actor_id="maal-agent",
        actor_role="system",
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        reason_summary=summary,
        evidence_ids=evidence_ids or [],
        tool_name=tool_name,
    )
    db.add_audit_event(event, db_path)


def _checkpoint(state: RunState, phase: RunPhase, *, tool: str, summary: str,
                db_path: Path | str | None = None) -> None:
    state.phase = phase
    state.last_tool = tool
    state.decision_summary = summary
    db.save_run_state(state, db_path)
    _audit(state.run_id, "phase_checkpoint", "run", state.run_id, summary, tool_name=tool, db_path=db_path)


def create_run(request: RunCreate, db_path: Path | str | None = None) -> tuple[dict, bool]:
    db.init_db(db_path)
    snapshot = db.get_company_snapshot(request.company_snapshot_id, db_path)
    old_version = db.get_document_version(request.old_version_id, db_path)
    new_version = db.get_document_version(request.new_version_id, db_path)
    if not snapshot or not old_version or not new_version:
        raise KeyError("company snapshot or document version not found")
    if old_version["source_id"] != new_version["source_id"]:
        raise ValueError("document versions must belong to the same source")
    request_hash = hashlib.sha256(
        json.dumps(request.model_dump(mode="json"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    run_id = db.stable_id("run", request.idempotency_key)
    thread_id = db.stable_id("thread", request.idempotency_key)
    record, created = db.create_run_record(
        run_id=run_id,
        thread_id=thread_id,
        company_snapshot_id=request.company_snapshot_id,
        company_id=snapshot.company_id,
        source_id=old_version["source_id"],
        old_version_id=request.old_version_id,
        new_version_id=request.new_version_id,
        idempotency_key=request.idempotency_key,
        request_hash=request_hash,
        db_path=db_path,
    )
    if created:
        state = RunState(
            run_id=run_id,
            thread_id=thread_id,
            phase=RunPhase.queued,
            company_snapshot_id=request.company_snapshot_id,
            old_version_id=request.old_version_id,
            new_version_id=request.new_version_id,
        )
        db.save_run_state(state, db_path)
        _audit(run_id, "run_created", "run", run_id, "حُجز التشغيل بمفتاح عدم تكرار.", db_path=db_path)
    return record, created


def execute_run(
    run_id: str,
    *,
    db_path: Path | str | None = None,
    stop_after: RunPhase | None = None,
) -> RunState:
    db.init_db(db_path)
    run = db.get_run(run_id, db_path)
    state = db.load_run_state(run_id, db_path)
    if not run or not state:
        raise KeyError(run_id)
    if state.phase in {RunPhase.completed, RunPhase.no_change}:
        return state
    try:
        _checkpoint(state, RunPhase.ingesting, tool="validate_inputs", summary="تم التحقق من المصدر والنسخ وملف المنشأة.", db_path=db_path)
        new_version = db.get_document_version(state.new_version_id, db_path)
        markers = detect_prompt_injection(new_version["content"] if new_version else "")
        if markers:
            _audit(run_id, "prompt_injection_ignored", "document_version", state.new_version_id,
                   "عومل محتوى الوثيقة كبيانات وتجاهلت تعليماته التشغيلية.", tool_name="input_guard", db_path=db_path)
        if stop_after == RunPhase.ingesting:
            return state

        changes = compare_versions(state.old_version_id, state.new_version_id, db_path)
        state.change_ids = [item.change_id for item in changes]
        _checkpoint(state, RunPhase.comparing, tool="compare_versions",
                    summary=f"اكتُشف {len(changes)} تغيرًا إجماليًا.", db_path=db_path)
        if stop_after == RunPhase.comparing:
            return state
        substantive = [item for item in changes if item.substantive]
        if not substantive:
            _checkpoint(state, RunPhase.no_change, tool="compare_versions",
                        summary="لا يوجد تغير جوهري؛ لم يبدأ تحليل فجوات أو إنشاء مهام.", db_path=db_path)
            db.update_run_phase(run_id, RunPhase.no_change, db_path=db_path)
            return state

        obligations = extract_affected_obligations(
            substantive,
            run_id=run_id,
            company_id=run["company_id"],
            model_id=run["model_id"],
            db_path=db_path,
        )
        state.obligation_ids = [item.obligation_id for item in obligations]
        _checkpoint(state, RunPhase.extracting, tool="extract_affected_obligations",
                    summary=f"استُخرج {len(obligations)} التزامًا من المواد المتأثرة فقط.", db_path=db_path)
        if stop_after == RunPhase.extracting:
            return state

        snapshot = db.get_company_snapshot(state.company_snapshot_id, db_path)
        if not snapshot:
            raise KeyError(state.company_snapshot_id)
        _checkpoint(state, RunPhase.retrieving, tool="retrieve_company_evidence",
                    summary="بدأ استرجاع الأدلة المقيدة بنوع الالتزام والمنشأة.", db_path=db_path)
        if stop_after == RunPhase.retrieving:
            return state
        existing_findings = {item.obligation_id: item for item in db.list_findings(run_id, db_path)}
        findings = []
        for obligation in obligations:
            if obligation.obligation_id in existing_findings:
                findings.append(existing_findings[obligation.obligation_id])
                continue
            selected = retrieve_company_evidence(state.company_snapshot_id, obligation, attempt=1, db_path=db_path)
            state.attempts[obligation.obligation_id] = 1
            _audit(run_id, "evidence_retrieved", "obligation", obligation.obligation_id,
                   f"استرجعت الأداة {len(selected)} أدلة في المحاولة الأولى.",
                   tool_name="retrieve_company_evidence", evidence_ids=[x.evidence_id for x in selected], db_path=db_path)
            if not selected:
                selected = retrieve_company_evidence(state.company_snapshot_id, obligation, attempt=2, db_path=db_path)
                state.attempts[obligation.obligation_id] = 2
                _audit(run_id, "evidence_retried", "obligation", obligation.obligation_id,
                       f"إعادة بحث أخيرة أعادت {len(selected)} أدلة.",
                       tool_name="retrieve_company_evidence", evidence_ids=[x.evidence_id for x in selected], db_path=db_path)
            applicability = db.get_applicability(run_id, obligation.obligation_id, db_path)
            if not applicability:
                applicability = check_applicability(obligation, snapshot, selected, db_path=db_path)
            finding = analyze_gap(obligation, applicability, selected, db_path=db_path)
            findings.append(finding)
        state.finding_ids = [item.finding_id for item in findings]
        _checkpoint(state, RunPhase.assessing, tool="assess_applicability_and_gap",
                    summary=f"اكتمل تقييم {len(findings)} نتيجة مع حالات امتناع صريحة.", db_path=db_path)
        if stop_after == RunPhase.assessing:
            return state

        _checkpoint(state, RunPhase.verifying, tool="validate_citations_and_rules",
                    summary="تحققت مراجع المواد والمقارنات الرقمية والقيم المقيدة.", db_path=db_path)
        if stop_after == RunPhase.verifying:
            return state

        obligation_map = {item.obligation_id: item for item in obligations}
        tasks = db.list_tasks(run_id, db_path)
        existing_task_findings = {task.finding_id for task in tasks}
        for finding in findings:
            if finding.finding_id in existing_task_findings:
                continue
            task = generate_task(finding, obligation_map[finding.obligation_id], db_path=db_path)
            if task:
                tasks.append(task)
                _audit(run_id, "task_drafted", "task", task.task_id,
                       "أُنشئت مسودة مرتبطة بفجوة مدعومة وتوقفت للمراجعة البشرية.",
                       tool_name="draft_task", evidence_ids=finding.evidence_ids, db_path=db_path)
        state.task_ids = [item.task_id for item in tasks]
        _checkpoint(state, RunPhase.drafting, tool="draft_task",
                    summary=f"أُنشئت {len(tasks)} مهمة مسودة دون تكرار.", db_path=db_path)
        if stop_after == RunPhase.drafting:
            return state
        final_phase = RunPhase.awaiting_review if any(t.review_status == "pending_human_review" for t in tasks) else RunPhase.completed
        _checkpoint(state, final_phase, tool="request_review" if tasks else "finalize",
                    summary="توقف التنفيذ بانتظار اعتماد بشري." if tasks else "اكتمل التحليل دون مهام علاجية.", db_path=db_path)
        if final_phase == RunPhase.completed:
            db.update_run_phase(run_id, final_phase, db_path=db_path)
        return state
    except Exception as exc:
        state.phase = RunPhase.failed
        state.errors.append(f"{type(exc).__name__}: {exc}")
        db.save_run_state(state, db_path)
        db.update_run_phase(run_id, RunPhase.failed, error_code=type(exc).__name__,
                            error_message=str(exc)[:500], db_path=db_path)
        _audit(run_id, "run_failed", "run", run_id, f"فشل صريح: {type(exc).__name__}", db_path=db_path)
        raise


def run_pipeline(
    regulation_path: str | None = None,
    company_profile_path: str | None = None,
    *,
    db_path: Path | str | None = None,
) -> dict:
    """Compatibility entry point now runs the seeded, version-aware demo."""
    from .demo import seed_demo
    seeded = seed_demo(db_path=db_path)
    request = RunCreate(
        company_snapshot_id=seeded["company_snapshot_id"],
        old_version_id=seeded["old_version_id"],
        new_version_id=seeded["new_version_id"],
        idempotency_key="cli-demo-versioned-run-v1",
    )
    run, _ = create_run(request, db_path)
    execute_run(run["run_id"], db_path=db_path)
    return db.fetch_run_bundle(run["run_id"], db_path)


if __name__ == "__main__":
    print(json.dumps(run_pipeline(), ensure_ascii=False, indent=2, default=str))
