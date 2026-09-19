from __future__ import annotations

from pathlib import Path

from . import db
from .schemas import (
    ApplicabilityResult, ApplicabilityStatus, CompanySnapshot, Evidence, Obligation,
)


def check_applicability(
    obligation: Obligation,
    snapshot: CompanySnapshot,
    evidence: list[Evidence],
    *,
    db_path: Path | str | None = None,
) -> ApplicabilityResult:
    text = f"{obligation.quote} {' '.join(obligation.applicability_conditions)}".casefold()
    asset_types = {str(asset.get("type", "")).casefold() for asset in snapshot.assets}
    evidence_ids: list[str] = []
    matched: list[str] = []
    missing: list[str] = []
    status = ApplicabilityStatus.unknown
    sufficiency = "insufficient"
    source = db.get_source(obligation.provenance.source_id, db_path)
    authority = (source or {}).get("authority", "").upper()
    company_text = " ".join([
        snapshot.name,
        snapshot.jurisdiction,
        *snapshot.activities,
        *(str(value) for asset in snapshot.assets for value in asset.values() if value is not None),
        *(str(value) for value in snapshot.attributes.values() if value not in (None, False)),
    ]).casefold()

    if authority == "NCA":
        relevant = any(token in company_text for token in (
            "cyber", "data", "بيانات", "operational technology", "ics", "embedded", "cloud", "سحاب",
        ))
        if relevant and snapshot.jurisdiction == "SA":
            status, sufficiency = ApplicabilityStatus.applicable, "sufficient"
            matched.extend(["Saudi jurisdiction", "documented cyber/data/technology activity"])
        else:
            status = ApplicabilityStatus.needs_review
            missing.append("documented NCA scope fact")
    elif authority == "SASO":
        relevant = any(token in company_text for token in (
            "manufactur", "تصنيع", "electr", "إلكترون", "embedded", "quality", "جودة", "procurement", "مشتريات",
        ))
        if relevant and snapshot.jurisdiction == "SA":
            status, sufficiency = ApplicabilityStatus.applicable, "sufficient"
            matched.extend(["Saudi jurisdiction", "documented manufacturing/product/quality activity"])
        else:
            status = ApplicabilityStatus.needs_review
            missing.append("documented SASO product or conformity scope fact")
    elif "stationary" in text:
        matches = [asset for asset in snapshot.assets if str(asset.get("type", "")).casefold() == "stationary_source"]
        if matches:
            status, sufficiency = ApplicabilityStatus.applicable, "sufficient"
            matched.append("stationary_source assets are recorded")
            evidence_ids.extend(item.evidence_id for item in evidence if item.asset_id in {a.get("asset_id") for a in matches})
        elif snapshot.attributes.get("stationary_sources_present") is False:
            status, sufficiency = ApplicabilityStatus.not_applicable, "sufficient"
            matched.append("snapshot explicitly records no stationary sources")
        else:
            missing.append("stationary_sources_present")
    elif "marine discharge" in text:
        flag = snapshot.attributes.get("marine_discharge_activity")
        if flag is True:
            status, sufficiency = ApplicabilityStatus.applicable, "sufficient"
            matched.append("marine discharge activity is explicitly recorded")
        elif flag is False:
            status, sufficiency = ApplicabilityStatus.not_applicable, "sufficient"
            matched.append("snapshot explicitly records no marine discharge activity")
        else:
            missing.append("marine_discharge_activity")
    elif "publish" in text or "public website" in text or "نشر" in text:
        flag = snapshot.attributes.get("publishes_environmental_readings")
        if flag is True:
            status, sufficiency = ApplicabilityStatus.applicable, "sufficient"
            matched.append("publication activity is explicitly recorded")
        elif flag is False:
            status, sufficiency = ApplicabilityStatus.not_applicable, "sufficient"
            matched.append("snapshot explicitly records no publication activity")
        else:
            missing.append("publishes_environmental_readings")
    elif obligation.modality == "permission_option":
        status, sufficiency = ApplicabilityStatus.applicable, "sufficient"
        matched.append("optional privilege assessed without treating non-eligibility as a breach")
    else:
        status, sufficiency = ApplicabilityStatus.unknown, "insufficient"
        missing.append("explicit activity or scope fact")

    result = ApplicabilityResult(
        applicability_id=db.stable_id("app", obligation.provenance.run_id, obligation.obligation_id),
        provenance=obligation.provenance,
        obligation_id=obligation.obligation_id,
        company_snapshot_id=snapshot.company_snapshot_id,
        status=status,
        matched_conditions=matched,
        missing_facts=missing,
        evidence_ids=sorted(set(evidence_ids)),
        rationale_summary=(
            "انطبق الشرط على حقائق منشأة موثقة." if status == ApplicabilityStatus.applicable
            else "يوجد دليل صريح على عدم الانطباق." if status == ApplicabilityStatus.not_applicable
            else "لا تكفي حقائق المنشأة لحسم الانطباق."
        ),
        applicability_sufficiency=sufficiency,
    )
    return db.insert_applicability(result, db_path)
