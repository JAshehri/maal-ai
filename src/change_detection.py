from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from . import db
from .arabic_processing import (
    are_articles_equivalent,
    extract_canonical_article_number,
    extract_numbers_all_scripts,
    normalize_arabic_letters,
)
from .schemas import ChangeType, Clause, RegulatoryChange


PUNCT_RE = re.compile(r"[^\w\d]+", re.UNICODE)
DEADLINE_WORDS = {"day", "days", "date", "deadline", "effective", "يوم", "أيام", "تاريخ", "مهلة", "سنة", "سنوات", "أشهر", "شهر"}
SCOPE_WORDS = {"scope", "applies", "facility", "activity", "jurisdiction", "نطاق", "ينطبق", "منشأة", "نشاط", "استثناء", "تسري"}
THRESHOLD_WORDS = {"limit", "threshold", "maximum", "minimum", "mg", "ppm", "حد", "أقصى", "أدنى", "نسبة", "معدل", "تركيز"}
RESPONSIBILITY_WORDS = {"مسؤول", "مسؤولية", "جهة", "إدارة", "department", "officer", "authority", "responsibility", "ضابط", "لجنة"}
EVIDENCE_WORDS = {"دليل", "سجل", "إثبات", "شهادة", "evidence", "certificate", "audit", "record", "توثيق", "مستند", "ترخيص"}


def _semantic_tokens(text: str) -> list[str]:
    normalized = normalize_arabic_letters(unicodedata.normalize("NFKC", text)).casefold()
    return [token for token in PUNCT_RE.sub(" ", normalized).split() if token]


def _numbers(text: str | None) -> list[float]:
    body = re.sub(
        r"^(?:Article|Section|Clause|المادة|القسم|البند|الفقرة)\s*(?:\([^)]+\)|[\w.-]+)?",
        "",
        text or "",
        flags=re.IGNORECASE,
    )
    return extract_numbers_all_scripts(body)


def _classify(before: str | None, after: str | None) -> tuple[ChangeType, bool, str]:
    if before is None:
        return ChangeType.added, True, "أضيفت مادة جديدة في اللائحة."
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
            return ChangeType.deadline, True, f"تغيرت مهلة زمنية أو تاريخ من {old_numbers} إلى {new_numbers}."
        if token_set & THRESHOLD_WORDS:
            return ChangeType.numeric_threshold, True, f"تغير حد رقمي ملزم من {old_numbers} إلى {new_numbers}."
    if token_set & SCOPE_WORDS:
        return ChangeType.scope, True, "تغير نطاق انطباق المادة أو استثناءاتها."
    if token_set & RESPONSIBILITY_WORDS:
        return ChangeType.responsibility_changed, True, "تغيرت الجهة أو الدور المسؤول عن الامتثال."
    if token_set & EVIDENCE_WORDS:
        return ChangeType.evidence_requirement_changed, True, "تغيرت متطلبات الإثبات والتوثيق والسجلات."
    return ChangeType.modified, True, "تغير نص المادة جوهرياً مما يتطلب مراجعة الأثر الداخلي."


def compare_clause_sets(
    *,
    source_id: str,
    old_version_id: str,
    new_version_id: str,
    old_clauses: list[Clause],
    new_clauses: list[Clause],
    db_path: Path | str | None = None,
) -> list[RegulatoryChange]:
    # مطابقة ذكية تدعم الترقيم العربي والإنجليزي والأرقام الهندية
    matched_pairs: list[tuple[Clause | None, Clause | None, str]] = []
    unmatched_new = list(new_clauses)

    for old_c in old_clauses:
        # البحث عن المادة المقابلة في النسخة الجديدة
        found_idx = None
        for idx, new_c in enumerate(unmatched_new):
            if are_articles_equivalent(old_c.article_ref, new_c.article_ref):
                found_idx = idx
                break
        if found_idx is not None:
            new_c = unmatched_new.pop(found_idx)
            matched_pairs.append((old_c, new_c, new_c.article_ref))
        else:
            matched_pairs.append((old_c, None, old_c.article_ref))

    for new_c in unmatched_new:
        matched_pairs.append((None, new_c, new_c.article_ref))

    changes: list[RegulatoryChange] = []
    for before_clause, after_clause, article_ref in matched_pairs:
        before = before_clause.text if before_clause else None
        after = after_clause.text if after_clause else None
        if before == after:
            continue
        change_type, substantive, summary = _classify(before, after)
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
