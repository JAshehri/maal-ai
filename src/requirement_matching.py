from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from . import db


OBLIGATION_PATTERN = re.compile(
    r"\b(?:must|shall|required|employee|trainee|worker)\b|(?:يجب|يلتزم|يتعين|موظف|عامل|متدرب|لكل)",
    re.I,
)
STOP_WORDS = {
    "the", "and", "for", "with", "from", "this", "that", "must", "shall", "required",
    "على", "في", "من", "إلى", "الى", "أن", "ان", "هذا", "هذه", "يجب", "يلتزم", "يتعين",
}
GENERIC_MATCH_TERMS = {
    "company", "organization", "document", "policy", "procedure", "requirement",
    "regulation", "control", "system", "data", "information", "management",
    "الشركة", "المنشأة", "المؤسسة", "وثيقة", "سياسة", "إجراء", "متطلب",
    "لائحة", "ضابط", "نظام", "بيانات", "معلومات", "إدارة",
}
SYNONYMS = {
    "employees": "employee", "employee": "employee", "staff": "employee", "workers": "employee",
    "موظف": "employee", "موظفين": "employee", "الموظفين": "employee", "العاملين": "employee", "عامل": "employee",
    "trainee": "trainee", "trainees": "trainee", "متدرب": "trainee", "متدربين": "trainee", "المتدربين": "trainee",
    "training": "training", "تدريب": "training", "التدريب": "training",
    "policy": "policy", "سياسة": "policy", "السياسة": "policy",
}
DIGIT_TRANSLATION = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@lru_cache(maxsize=8192)
def _tokens(text: str) -> frozenset[str]:
    values = re.findall(r"[A-Za-z\u0600-\u06FF]{3,}", text.casefold())
    return frozenset(SYNONYMS.get(value, value) for value in values if value not in STOP_WORDS)


@lru_cache(maxsize=8192)
def _numbers(text: str) -> tuple[float, ...]:
    text = text.translate(DIGIT_TRANSLATION)
    return tuple(float(value) for value in re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?", text))


@lru_cache(maxsize=8192)
def _ratio(text: str) -> tuple[float, float] | None:
    text = text.translate(DIGIT_TRANSLATION)
    patterns = [
        r"(?:one|1|واحد|واحدة)\s+(?:trainee|متدرب\w*)\s+(?:for\s+every|per|لكل)\s+(\d+(?:\.\d+)?)\s+(?:employees?|workers?|موظف\w*|عامل\w*)",
        r"(?:لكل|for\s+every|per)\s+(\d+(?:\.\d+)?)\s+(?:employees?|workers?|موظف\w*|عامل\w*).{0,35}?(?:one|1|واحد|واحدة)\s+(?:trainee|متدرب\w*)",
        r"(?:trainee|متدرب\w*)\s+(?:one|1|واحد|واحدة)\s+(?:for\s+every|per|لكل)\s+(\d+(?:\.\d+)?)\s+(?:employees?|workers?|موظف\w*|عامل\w*)",
        r"(?:لكل|for\s+every|per)\s+(\d+(?:\.\d+)?)\s+(?:employees?|workers?|موظف\w*|عامل\w*).{0,35}?(?:trainee|متدرب\w*)\s+(?:one|1|واحد|واحدة)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return 1.0, float(match.group(1))
    return None


@lru_cache(maxsize=16384)
def _count(text: str, subject: str) -> float | None:
    text = text.translate(DIGIT_TRANSLATION)
    labels = {
        "employee": r"(?:employees?|workers?|staff|موظف\w*|عامل\w*)",
        "trainee": r"(?:trainees?|متدرب\w*)",
    }[subject]
    patterns = [rf"(\d+(?:\.\d+)?)\s*{labels}", rf"{labels}\s*[:=]?\s*(\d+(?:\.\d+)?)"]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return float(match.group(1))
    if subject == "trainee" and re.search(r"(?:no|zero|without|لا يوجد(?:\s+ولا)?|بدون)\s+(?:أي\s+)?(?:trainees?|متدرب\w*)", text, re.I):
        return 0.0
    return None


def compare_requirement(requirement: str, company_text: str, article_ref: str) -> dict[str, Any] | None:
    regulatory_tokens, company_tokens = _tokens(requirement), _tokens(company_text)
    shared = regulatory_tokens & company_tokens
    discriminative_shared = shared - GENERIC_MATCH_TERMS
    semantic_score = len(shared) / max(1, min(len(regulatory_tokens), len(company_tokens)))
    normalized_ref = article_ref.casefold().strip()
    explicit_reference = (
        normalized_ref not in {"document", "الوثيقة", "document section"}
        and normalized_ref in company_text.casefold()
    )
    regulatory_ratio, company_ratio = _ratio(requirement), _ratio(company_text)
    employees, trainees = _count(company_text, "employee"), _count(company_text, "trainee")
    evidenced_numeric_match = bool(regulatory_ratio and (company_ratio or employees is not None))
    evidenced_term_match = semantic_score >= 0.34 and len(shared) >= 3 and len(discriminative_shared) >= 2
    if not explicit_reference and not evidenced_numeric_match and not evidenced_term_match:
        return None

    comparison: dict[str, Any] = {
        "explicit_article_reference": explicit_reference,
        "shared_terms": sorted(shared),
        "discriminative_shared_terms": sorted(discriminative_shared),
        "regulatory_numbers": list(_numbers(requirement)),
        "company_numbers": list(_numbers(company_text)),
    }
    method = "exact_article_reference" if explicit_reference else "deterministic_term_match"
    status, fix = "insufficient_evidence", None
    rationale = "وجد النظام مقطعًا ذا صلة، لكن الأدلة الرقمية أو التشغيلية غير كافية لإثبات التطبيق."

    if regulatory_ratio:
        required_numerator, required_denominator = regulatory_ratio
        comparison["required_ratio"] = {"trainees": required_numerator, "employees": required_denominator}
        if company_ratio:
            actual_numerator, actual_denominator = company_ratio
            comparison["documented_ratio"] = {"trainees": actual_numerator, "employees": actual_denominator}
            compliant = actual_numerator / actual_denominator >= required_numerator / required_denominator
            status = "compliant" if compliant else "non_compliant"
            rationale = ("النسبة الموثقة في ملف الشركة تحقق الحد التنظيمي."
                         if compliant else "النسبة الموثقة في ملف الشركة أقل من الحد التنظيمي المطلوب.")
            if not compliant:
                fix = f"حدّث السياسة لتوثيق متدرب واحد على الأقل لكل {required_denominator:g} موظف."
            method = "deterministic_ratio_comparison"
        elif employees is not None and trainees is not None:
            required_count = math.ceil(employees / required_denominator * required_numerator)
            comparison.update({"employee_count": employees, "trainee_count": trainees,
                               "minimum_required_trainees": required_count})
            status = "compliant" if trainees >= required_count else "non_compliant"
            rationale = ("العدد الفعلي الموثق يحقق النسبة التنظيمية."
                         if status == "compliant" else "العدد الفعلي الموثق لا يحقق النسبة التنظيمية.")
            if status == "non_compliant":
                fix = f"وفّر ووثّق ما لا يقل عن {required_count} متدرب/متدربين لهذا العدد من الموظفين."
            method = "deterministic_headcount_comparison"
    elif explicit_reference:
        required_numbers, company_numbers = _numbers(requirement), _numbers(company_text)
        if required_numbers and company_numbers:
            if set(required_numbers) & set(company_numbers):
                status, rationale = "compliant", "القيمة الموثقة في ملف الشركة تطابق قيمة المتطلب المشار إليه."
            else:
                status, rationale = "partially_compliant", "تم العثور على إحالة للمادة لكن القيم الرقمية تحتاج مراجعة بشرية."
                fix = "راجع القيمة في هذا الموضع مقابل النص التنظيمي الحالي وحدّثها بعد الاعتماد."
            method = "exact_reference_numeric_comparison"
        else:
            status, rationale = "needs_review", "تم العثور على إحالة صريحة للمادة دون دليل كافٍ لإثبات التنفيذ الفعلي."

    return {"status": status, "matching_method": method, "match_score": round(max(semantic_score, 1.0 if explicit_reference else 0.0), 3),
            "comparison": comparison, "rationale": rationale, "recommended_fix": fix}


def assess_version_against_company(
    *, company_snapshot_id: str, version_id: str, source_id: str,
    regulatory_document_id: str | None = None, company_document_id: str | None = None,
    db_path=None,
) -> list[dict[str, Any]]:
    clauses = [item for item in db.list_clauses(version_id, db_path) if OBLIGATION_PATTERN.search(item.text)]
    documents = ([db.get_company_document(company_document_id, db_path)] if company_document_id
                 else db.list_company_documents(company_snapshot_id, db_path))
    documents = [item for item in documents if item]
    with db.connect(db_path) as connection:
        if company_document_id:
            connection.execute(
                """DELETE FROM requirement_assessments
                    WHERE company_snapshot_id=? AND version_id=? AND company_document_id=?""",
                (company_snapshot_id, version_id, company_document_id),
            )
        else:
            connection.execute(
                "DELETE FROM requirement_assessments WHERE company_snapshot_id=? AND version_id=?",
                (company_snapshot_id, version_id),
            )
    stored: list[dict[str, Any]] = []
    document_chunks = [
        (document, db.list_company_document_chunks(document["company_document_id"], db_path))
        for document in documents
    ]
    for clause in clauses:
        candidates = []
        for document, chunks in document_chunks:
            document_candidates = []
            for chunk in chunks:
                result = compare_requirement(clause.text, chunk["text"], clause.article_ref)
                if result:
                    document_candidates.append((result["match_score"], document, chunk, result))
            if document_candidates:
                candidates.append(max(document_candidates, key=lambda item: item[0]))
        if not candidates:
            continue
        exact_methods = {
            "exact_article_reference", "exact_reference_numeric_comparison",
            "deterministic_ratio_comparison", "deterministic_headcount_comparison",
        }
        exact = [item for item in candidates if item[3]["matching_method"] in exact_methods]
        semantic = sorted(
            (item for item in candidates if item[3]["matching_method"] not in exact_methods),
            key=lambda item: item[0], reverse=True,
        )
        selected = exact + semantic[:3]
        for _, document, chunk, result in selected:
            fingerprint = hashlib.sha256(
                f"{clause.text_sha256}:{chunk['text_sha256']}".encode("utf-8")
            ).hexdigest()
            reviewer_feedback = db.latest_analysis_feedback(
                company_id=document["company_id"], subject_key=f"requirement:{clause.clause_id}",
                evidence_fingerprint=fingerprint, db_path=db_path,
            )
            if (reviewer_feedback and reviewer_feedback["decision"] == "reject"
                    and reviewer_feedback.get("corrected_value") in {
                        "compliant", "partially_compliant", "non_compliant",
                        "needs_review", "insufficient_evidence"
                    }):
                result["status"] = reviewer_feedback["corrected_value"]
                result["rationale"] = f"تصحيح بشري محفوظ لنفس بصمة الأدلة: {reviewer_feedback['comment']}"
                result["matching_method"] = "reviewer_corrected_evidence_match"
            assessment_id = db.stable_id("reqassess", company_snapshot_id, clause.clause_id, chunk["chunk_id"])
            now = _now()
            with db.connect(db_path) as connection:
                connection.execute(
                    """INSERT INTO requirement_assessments
                       (assessment_id, company_snapshot_id, company_document_id, company_chunk_id,
                        source_id, regulatory_document_id, version_id, clause_id, article_ref, status,
                        matching_method, match_score, regulatory_quote, company_quote, locator_json,
                        comparison_json, rationale, recommended_fix, evidence_fingerprint, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(company_snapshot_id, clause_id, company_chunk_id) DO UPDATE SET
                         status=excluded.status, matching_method=excluded.matching_method,
                         match_score=excluded.match_score, regulatory_quote=excluded.regulatory_quote,
                         company_quote=excluded.company_quote, locator_json=excluded.locator_json,
                         comparison_json=excluded.comparison_json, rationale=excluded.rationale,
                         recommended_fix=excluded.recommended_fix,
                         evidence_fingerprint=excluded.evidence_fingerprint, updated_at=excluded.updated_at""",
                    (assessment_id, company_snapshot_id, document["company_document_id"], chunk["chunk_id"],
                     source_id, regulatory_document_id, version_id, clause.clause_id, clause.article_ref,
                     result["status"], result["matching_method"], result["match_score"], clause.text,
                     chunk["text"], _json(chunk["locator"]), _json(result["comparison"]),
                     result["rationale"], result["recommended_fix"], fingerprint, now, now),
                )
            stored.append({"assessment_id": assessment_id, **result, "document": document,
                           "chunk": chunk, "clause": clause, "evidence_fingerprint": fingerprint})
    return stored


def list_assessments(*, company_snapshot_id: str, version_id: str | None = None,
                     company_document_id: str | None = None, db_path=None) -> list[dict[str, Any]]:
    sql = """SELECT a.*, d.filename, d.title AS document_title, d.department, d.project_id
               FROM requirement_assessments a JOIN company_documents d USING(company_document_id)
              WHERE a.company_snapshot_id=?"""
    params: list[Any] = [company_snapshot_id]
    if version_id:
        sql += " AND a.version_id=?"; params.append(version_id)
    if company_document_id:
        sql += " AND a.company_document_id=?"; params.append(company_document_id)
    sql += " ORDER BY a.article_ref, d.filename"
    with db.connect(db_path) as connection:
        rows = connection.execute(sql, params).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["locator"] = json.loads(item.pop("locator_json"))
        item["comparison"] = json.loads(item.pop("comparison_json"))
        result.append(item)
    return result
