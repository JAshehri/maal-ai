from __future__ import annotations

from collections import Counter
from pathlib import Path

from . import db


def generate_report(run_id: str, db_path: Path | str | None = None) -> dict:
    bundle = db.fetch_run_bundle(run_id, db_path)
    findings = bundle["findings"]
    tasks = bundle["tasks"]
    counts = Counter(item["assessment_status"] for item in findings)
    return {
        "run_id": run_id,
        "status": bundle["run"]["phase"],
        "scope": {
            "company_id": bundle["run"]["company_id"],
            "source_id": bundle["run"]["source_id"],
            "old_version_id": bundle["run"]["old_version_id"],
            "new_version_id": bundle["run"]["new_version_id"],
        },
        "summary": {
            "changes": len(bundle["changes"]),
            "obligations": len(bundle["obligations"]),
            "findings_by_status": dict(counts),
            "tasks": len(tasks),
            "pending_reviews": sum(t["review_status"] == "pending_human_review" for t in tasks),
        },
        "changes": bundle["changes"],
        "findings": findings,
        "tasks": tasks,
        "audit_events": bundle["audit_events"],
        "disclaimer": "مآل يدعم القرار ولا يضمن الامتثال. النتائج النهائية خاضعة لمراجعة بشرية مخولة.",
    }

