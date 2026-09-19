from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from . import db
from .schemas import AuditEvent, ReviewDecision, ReviewRequest, RunPhase, TaskDraft


class ReviewForbidden(PermissionError):
    pass


class RevisionConflict(RuntimeError):
    pass


EDITABLE_FIELDS = {"action", "owner_role", "proposed_due_date", "acceptance_evidence"}


def review_task(
    task_id: str,
    request: ReviewRequest,
    *,
    reviewer_id: str,
    role: str,
    db_path: Path | str | None = None,
) -> TaskDraft:
    if role not in {"reviewer", "admin"}:
        raise ReviewForbidden("reviewer or admin role required")
    task = db.get_task(task_id, db_path)
    if not task:
        raise KeyError(task_id)
    if task.revision != request.expected_revision:
        raise RevisionConflict(f"expected revision {request.expected_revision}, current revision {task.revision}")
    unknown = set(request.edited_fields) - EDITABLE_FIELDS
    if unknown:
        raise ValueError(f"fields cannot be edited: {sorted(unknown)}")
    updates = dict(request.edited_fields)
    if "proposed_due_date" in updates and isinstance(updates["proposed_due_date"], str):
        updates["proposed_due_date"] = date.fromisoformat(updates["proposed_due_date"])
    updates["review_status"] = (
        "approved" if request.decision == ReviewDecision.approve
        else "rejected" if request.decision == ReviewDecision.reject
        else "pending_human_review"
    )
    updates["revision"] = task.revision + 1
    updated = TaskDraft.model_validate(task.model_copy(update=updates).model_dump())
    before_hash = hashlib.sha256(json.dumps(task.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()
    after_hash = hashlib.sha256(json.dumps(updated.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()
    review_id = db.stable_id("review", task_id, reviewer_id, str(task.revision), request.decision.value)
    payload = {
        "review_id": review_id,
        "reviewer_id": reviewer_id,
        "decision": request.decision.value,
        "comment": request.comment,
        "reviewed_revision": task.revision,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        db.update_task_and_add_review(updated, payload, db_path)
    except sqlite3.IntegrityError as exc:
        raise RevisionConflict("task changed during review") from exc
    event = AuditEvent(
        event_id=db.stable_id("evt", task.provenance.run_id, "task_reviewed", review_id),
        run_id=task.provenance.run_id,
        actor_id=reviewer_id,
        actor_role=role,
        action=f"task_{request.decision.value}",
        entity_type="task",
        entity_id=task_id,
        reason_summary=request.comment,
        evidence_ids=[],
        tool_name="review_service",
        before_hash=before_hash,
        after_hash=after_hash,
    )
    db.add_audit_event(event, db_path)
    tasks = db.list_tasks(task.provenance.run_id, db_path)
    if tasks and all(item.review_status in {"approved", "rejected"} for item in tasks):
        state = db.load_run_state(task.provenance.run_id, db_path)
        if state:
            state.phase = RunPhase.completed
            state.decision_summary = "اكتملت جميع قرارات المراجعة البشرية."
            db.save_run_state(state, db_path)
            db.update_run_phase(task.provenance.run_id, RunPhase.completed, db_path=db_path)
    return updated

