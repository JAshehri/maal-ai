from __future__ import annotations

from pathlib import Path

from . import db
from .risk_rules import compare_measurements, evidence_freshness
from .schemas import (
    ApplicabilityResult, ApplicabilityStatus, AssessmentStatus, Evidence, Finding,
    Obligation, SourceQuality,
)


def analyze_gap(
    obligation: Obligation,
    applicability: ApplicabilityResult,
    evidence: list[Evidence],
    *,
    db_path: Path | str | None = None,
) -> Finding:
    status = AssessmentStatus.unknown
    details: dict = {}
    uncertainty: list[str] = []
    rationale = "تعذر حسم النتيجة."
    priority = "pending_review"

    if applicability.status == ApplicabilityStatus.not_applicable:
        status = AssessmentStatus.supported_compliant
        rationale = "الالتزام غير منطبق وفق حقيقة منشأة صريحة؛ لم تُنشأ مهمة."
        priority = "low"
    elif applicability.status in {
        ApplicabilityStatus.unknown,
        ApplicabilityStatus.needs_review,
        ApplicabilityStatus.potentially_applicable,
    }:
        status = AssessmentStatus.insufficient_evidence
        uncertainty = list(applicability.missing_facts)
        rationale = "لا يمكن تحليل الفجوة قبل استكمال حقائق الانطباق."
    elif obligation.modality == "permission_option":
        status = AssessmentStatus.supported_compliant
        rationale = "النص يمنح خيارًا أو امتيازًا؛ عدم استيفائه لا يُعامل كمخالفة."
        priority = "low"
    elif obligation.threshold:
        status, details, uncertainty = compare_measurements(obligation, evidence)
        if status == AssessmentStatus.gap:
            rationale, priority = "تجاوز قياس قابل للمقارنة الحد الموجود في مادة المحاكاة.", "high"
        elif status == AssessmentStatus.supported_compliant:
            rationale, priority = "القياسات القابلة للمقارنة لا تتجاوز الحد في المادة.", "low"
        elif status == AssessmentStatus.conflicting_evidence:
            rationale = "توجد قياسات متعارضة؛ أُوقف القرار للمراجعة."
        else:
            rationale = "لا يوجد قياس مكافئ في الوحدة وأساس القياس."
    else:
        permission_items = [item for item in evidence if item.evidence_type == "permission"]
        if permission_items and any(item.structured_data.get("status") == "valid" for item in permission_items):
            status, rationale, priority = AssessmentStatus.supported_compliant, "وُجد تصريح صالح مرتبط.", "low"
        else:
            status = AssessmentStatus.insufficient_evidence
            uncertainty = ["absence from repository is not proof of non-existence"]
            rationale = "لم يُعثر على دليل كافٍ؛ لا يُعتبر غياب المستند إثباتًا للمخالفة."

    cited = set(obligation.citation_ids)
    citation_validity = "valid" if obligation.clause_id in cited and bool(obligation.quote) else "invalid"
    evidence_ids = [item.evidence_id for item in evidence]
    affected_assets = sorted({item.asset_id for item in evidence if item.asset_id})
    source = db.get_source(obligation.provenance.source_id, db_path)
    source_quality = SourceQuality(source["source_quality"]) if source else SourceQuality.unverified
    finding = Finding(
        finding_id=db.stable_id("finding", obligation.provenance.run_id, obligation.change_id, obligation.obligation_id),
        provenance=obligation.provenance,
        change_id=obligation.change_id,
        obligation_id=obligation.obligation_id,
        affected_asset_ids=affected_assets,
        assessment_status=status,
        evidence_ids=evidence_ids,
        comparison_details=details,
        uncertainty_reasons=uncertainty,
        priority=priority,
        rationale_summary=rationale,
        source_quality=source_quality,
        evidence_freshness=evidence_freshness(evidence),
        citation_validity=citation_validity,
        applicability_sufficiency=applicability.applicability_sufficiency,
    )
    return db.insert_finding(finding, db_path)
