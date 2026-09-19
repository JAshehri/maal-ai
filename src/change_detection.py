from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from . import db
from .schemas import ChangeType, Clause, RegulatoryChange


NUMBER_RE = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")
PUNCT_RE = re.compile(r"[^\w\d]+", re.UNICODE)
DEADLINE_WORDS = {"day", "days", "date", "deadline", "effective", "يوم", "أيام", "تاريخ", "مهلة"}
SCOPE_WORDS = {"scope", "applies", "facility", "activity", "jurisdiction", "نطاق", "ينطبق", "منشأة", "نشاط"}
THRESHOLD_WORDS = {"limit", "threshold", "maximum", "minimum", "mg", "ppm", "حد", "أقصى", "أدنى"}


def _semantic_tokens(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return [token for token in PUNCT_RE.sub(" ", normalized).split() if token]


def _numbers(text: str | None) -> list[float]:
    body = re.sub(r"^(?:Article|Section|Clause|المادة|القسم)\s+[\w.-]+", "", text or "", flags=re.IGNORECASE)
    return [float(value) for value in NUMBER_RE.findall(body)]


def _classify(before: str | None, after: str | None) -> tuple[ChangeType, bool, str]:
    if before is None:
        return ChangeType.added, True, "أضيفت مادة جديدة."
    if after is None:
        return ChangeType.deleted, True, "حُذفت المادة من النسخة الجديدة."
    if before == after:
        return ChangeType.editorial, False, "لا يوجد تغيير."
    old_tokens, new_tokens = _semantic_tokens(before), _semantic_tokens(after)
    if old_tokens == new_tokens:
        return ChangeType.editorial, False, "تغيير تنسيقي أو تحريري غير جوهري."
    old_numbers, new_numbers = _numbers(before), _numbers(after)
    token_set = set(old_tokens + new_tokens)
    if old_numbers != new_numbers:
        if token_set & DEADLINE_WORDS:
            return ChangeType.deadline, True, f"تغيرت قيمة زمنية من {old_numbers} إلى {new_numbers}."
        if token_set & THRESHOLD_WORDS:
            return ChangeType.numeric_threshold, True, f"تغيرت قيمة رقمية أو حد من {old_numbers} إلى {new_numbers}."
    if token_set & SCOPE_WORDS:
        return ChangeType.scope, True, "تغير نطاق المادة أو شرط انطباقها."
    return ChangeType.modified, True, "تغير نص المادة تغييرًا جوهريًا يحتاج تحليل أثر."


def compare_clause_sets(
    *,
    source_id: str,
    old_version_id: str,
    new_version_id: str,
    old_clauses: list[Clause],
    new_clauses: list[Clause],
    db_path: Path | str | None = None,
) -> list[RegulatoryChange]:
    old_by_ref = {clause.article_ref.casefold(): clause for clause in old_clauses}
    new_by_ref = {clause.article_ref.casefold(): clause for clause in new_clauses}
    changes: list[RegulatoryChange] = []
    for key in sorted(set(old_by_ref) | set(new_by_ref)):
        before_clause, after_clause = old_by_ref.get(key), new_by_ref.get(key)
        before = before_clause.text if before_clause else None
        after = after_clause.text if after_clause else None
        if before == after:
            continue
        change_type, substantive, summary = _classify(before, after)
        article_ref = (after_clause or before_clause).article_ref
        change = RegulatoryChange(
            change_id=db.stable_id("chg", old_version_id, new_version_id, article_ref),
            source_id=source_id,
            old_version_id=old_version_id,
            new_version_id=new_version_id,
            before_clause_id=before_clause.clause_id if before_clause else None,
            after_clause_id=after_clause.clause_id if after_clause else None,
            article_ref=article_ref,
            change_type=change_type,
            before_text=before,
            after_text=after,
            summary=summary,
            substantive=substantive,
            numeric_before=_numbers(before),
            numeric_after=_numbers(after),
        )
        changes.append(db.insert_change(change, db_path))
    return changes


def compare_versions(old_version_id: str, new_version_id: str, db_path: Path | str | None = None) -> list[RegulatoryChange]:
    old_version = db.get_document_version(old_version_id, db_path)
    new_version = db.get_document_version(new_version_id, db_path)
    if not old_version or not new_version:
        raise KeyError("document version not found")
    if old_version["source_id"] != new_version["source_id"]:
        raise ValueError("versions must belong to the same source")
    existing = db.list_changes(old_version_id, new_version_id, db_path)
    if existing:
        return existing
    if old_version["text_sha256"] == new_version["text_sha256"]:
        return []
    return compare_clause_sets(
        source_id=old_version["source_id"],
        old_version_id=old_version_id,
        new_version_id=new_version_id,
        old_clauses=db.list_clauses(old_version_id, db_path),
        new_clauses=db.list_clauses(new_version_id, db_path),
        db_path=db_path,
    )
