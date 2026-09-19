from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .schemas import AssessmentStatus, Evidence, Obligation


def compare_measurements(obligation: Obligation, evidence: list[Evidence]) -> tuple[AssessmentStatus, dict[str, Any], list[str]]:
    threshold = obligation.threshold
    if not threshold:
        return AssessmentStatus.insufficient_evidence, {}, ["no machine-readable threshold"]
    quote_upper = obligation.quote.upper()
    pollutant = next((name for name in ("NOX", "SO2", "PM") if name in quote_upper), None)
    measurements = []
    for item in evidence:
        data = item.structured_data
        if item.evidence_type != "measurement" or "value" not in data:
            continue
        if pollutant and str(data.get("pollutant", "")).upper() != pollutant:
            continue
        if str(data.get("unit", "")).casefold() != threshold.unit.casefold():
            continue
        if threshold.measurement_basis and str(data.get("measurement_basis", "")).casefold() != threshold.measurement_basis.casefold():
            continue
        measurements.append(item)
    if not measurements:
        unit_mismatch = any(item.evidence_type == "measurement" for item in evidence)
        reason = "measurement unit or basis is not comparable" if unit_mismatch else "measurement evidence is missing"
        return AssessmentStatus.insufficient_evidence, {}, [reason]

    grouped: dict[tuple[str | None, str | None], set[float]] = {}
    for item in measurements:
        key = (item.asset_id, item.observed_at.date().isoformat() if item.observed_at else None)
        grouped.setdefault(key, set()).add(float(item.structured_data["value"]))
    if any(len(values) > 1 for values in grouped.values()):
        return AssessmentStatus.conflicting_evidence, {
            "threshold": threshold.model_dump(mode="json"),
            "measurements": [item.structured_data for item in measurements],
        }, ["multiple incompatible measurements exist for the same asset and observation date"]

    violating = []
    compliant = []
    for item in measurements:
        value = float(item.structured_data["value"])
        is_gap = {
            "<=": value > threshold.value,
            "<": value >= threshold.value,
            ">=": value < threshold.value,
            ">": value <= threshold.value,
            "=": value != threshold.value,
        }[threshold.operator]
        (violating if is_gap else compliant).append({"evidence_id": item.evidence_id, "asset_id": item.asset_id, "value": value})
    details = {"threshold": threshold.model_dump(mode="json"), "violating": violating, "compliant": compliant}
    return (AssessmentStatus.gap if violating else AssessmentStatus.supported_compliant), details, []


def evidence_freshness(evidence: list[Evidence]) -> str:
    observed = [item.observed_at for item in evidence if item.observed_at]
    if not observed:
        return "unknown"
    newest = max(observed)
    age_days = (datetime.now(timezone.utc) - newest).days
    return "current" if age_days <= 365 else "stale"
