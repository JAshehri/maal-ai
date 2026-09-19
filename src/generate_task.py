from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from . import db
from .schemas import AssessmentStatus, Finding, Obligation, TaskDraft


def generate_task(
    finding: Finding,
    obligation: Obligation,
    *,
    db_path: Path | str | None = None,
) -> TaskDraft | None:
    if finding.assessment_status != AssessmentStatus.gap:
        return None
    assets = ", ".join(finding.affected_asset_ids) or "الأصل المتأثر"
    due_days = 7 if finding.priority == "high" else 30 if finding.priority == "medium" else 90
    source = db.get_source(finding.provenance.source_id, db_path) or {}
    authority = str(source.get("authority", "")).upper()
    owner_role = {
        "NCA": "Cybersecurity",
        "SASO": "Quality and Engineering",
    }.get(authority, "Compliance")
    acceptance_evidence = {
        "NCA": ["دليل تطبيق الضابط", "نتيجة اختبار أو تقييم فني", "اعتماد مسؤول الأمن السيبراني"],
        "SASO": ["تقرير مطابقة أو اختبار", "مواصفة المنتج أو المكون", "اعتماد الجودة والهندسة"],
    }.get(authority, ["دليل معالجة موثق", "اعتماد مسؤول الامتثال"])
    task = TaskDraft(
        task_id=db.stable_id("task", finding.provenance.run_id, finding.finding_id),
        provenance=finding.provenance,
        finding_id=finding.finding_id,
        action=f"تحقق من القياس وأساسه للأصل {assets}، ثم وثّق إجراء المعالجة المرتبط بـ{obligation.article_ref}.",
        owner_role=owner_role,
        proposed_due_date=date.today() + timedelta(days=due_days),
        due_date_basis=f"موعد إداري مقترح حسب أولوية {finding.priority}؛ ليس مهلة نظامية.",
        acceptance_evidence=acceptance_evidence,
    )
    return db.insert_task(task, db_path)
