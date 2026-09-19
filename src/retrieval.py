from __future__ import annotations

import re
from pathlib import Path

from . import db
from .schemas import Clause, Evidence, Obligation


REFERENCE_RE = re.compile(r"(?:Article|المادة)\s+[\w.-]+", re.IGNORECASE)


def retrieve_related_clauses(clause: Clause, db_path: Path | str | None = None) -> list[Clause]:
    clauses = db.list_clauses(clause.version_id, db_path)
    references = {value.casefold() for value in REFERENCE_RE.findall(clause.text)}
    result: dict[str, Clause] = {}
    for candidate in clauses:
        lower = candidate.text.casefold()
        if candidate.clause_id == clause.clause_id:
            continue
        if candidate.article_ref.casefold() in references:
            result[candidate.clause_id] = candidate
        elif any(marker in lower for marker in ("definition", "exception", "تعريف", "استثناء")):
            tokens = set(re.findall(r"\w+", clause.text.casefold()))
            candidate_tokens = set(re.findall(r"\w+", lower))
            if len(tokens & candidate_tokens) >= 2:
                result[candidate.clause_id] = candidate
    return list(result.values())


def retrieve_company_evidence(
    snapshot_id: str,
    obligation: Obligation,
    *,
    attempt: int = 1,
    db_path: Path | str | None = None,
) -> list[Evidence]:
    all_items = db.list_evidence(snapshot_id, db_path)
    text = f"{obligation.quote} {obligation.action}".casefold()
    keywords = set(re.findall(r"[\w.-]+", text))
    pollutant = next((name for name in ("nox", "so2", "pm") if name in text), None)
    scored: list[tuple[int, Evidence]] = []
    for item in all_items:
        haystack = f"{item.title} {item.content} {item.evidence_type} {item.asset_id or ''}".casefold()
        if obligation.threshold:
            if item.evidence_type != "measurement":
                continue
            if pollutant and str(item.structured_data.get("pollutant", "")).casefold() != pollutant:
                continue
        elif "publish" in text or "permission" in text:
            if item.evidence_type not in {"permit", "permission", "publication"}:
                continue
        elif "marine discharge" in text and item.evidence_type != "activity_record":
            continue
        score = sum(1 for keyword in keywords if len(keyword) > 3 and keyword in haystack)
        data = item.structured_data
        if obligation.threshold and data.get("pollutant") and str(data["pollutant"]).casefold() in text:
            score += 5
        if "permission" in text and item.evidence_type in {"permit", "permission", "publication"}:
            score += 5
        if "stationary" in text and item.asset_id:
            score += 2
        if score:
            scored.append((score, item))
    scored.sort(key=lambda pair: (pair[0], pair[1].evidence_id), reverse=True)
    return [item for _, item in scored[:8]]
