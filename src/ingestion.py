from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timezone
from pathlib import Path

from . import db
from .arabic_processing import (
    ARABIC_LEGAL_ARTICLE_PATTERN,
    extract_canonical_article_number,
    process_text,
)
from .schemas import Clause, DocumentVersion, DocumentVersionCreate


# نمط متقدم يجمع الترقيم الإنجليزي والعربي للمواد والبنود القانونية
ARTICLE_PATTERN = re.compile(
    r"^(?P<ref>"
    r"(?:Article|Section|Clause)\s*(?:\([\d٠-٩.-]+\)|[\d٠-٩.-]+)"
    r"|"
    r"(?:المادة|القسم|البند|الفقرة)\s*(?:\([\d٠-٩.-]+\)|[\d٠-٩.-]+|"
    r"(?:الاولى|الاول|الثانية|الثاني|الثالثة|الثالث|الرابعة|الرابع|"
    r"الخامسة|الخامس|السادسة|السادس|السابعة|السابع|الثامنة|الثامن|"
    r"التاسعة|التاسع|العاشرة|العاشر|الحادية عشرة|الحادي عشر|"
    r"الثانية عشرة|الثاني عشر))"
    r"|"
    r"(?:أولاً|ثانياً|ثالثاً|رابعاً|خامساً|سادساً|سابعاً|ثامناً|تاسعاً|عاشراً)"
    r")"
    r"(?:\s*[-–—:]\s*|\s+|$)(?P<body>.*)$",
    re.IGNORECASE | re.MULTILINE,
)

INJECTION_MARKERS = (
    "ignore previous instructions",
    "reveal the api key",
    "system prompt",
    "تجاهل التعليمات السابقة",
    "اكشف مفتاح",
)


def normalize_text(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")).strip()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def detect_prompt_injection(text: str) -> list[str]:
    lowered = text.casefold()
    return [marker for marker in INJECTION_MARKERS if marker in lowered]


def extract_clauses(version_id: str, content: str) -> list[Clause]:
    text = normalize_text(content)
    matches = list(ARTICLE_PATTERN.finditer(text))
    if not matches:
        processed = process_text(text)
        return [Clause(
            clause_id=db.stable_id("clause", version_id, "Document", sha256_text(text)),
            version_id=version_id,
            article_ref="Document",
            text=text,
            start_offset=0,
            end_offset=len(text),
            text_sha256=sha256_text(text),
            raw_text=text,
            normalized_text=processed.normalized_text,
            language=processed.language,
        )]
    clauses: list[Clause] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        raw = text[start:end].strip()
        article_ref = match.group("ref").strip()
        processed = process_text(raw)
        clauses.append(Clause(
            clause_id=db.stable_id("clause", version_id, article_ref, sha256_text(raw)),
            version_id=version_id,
            article_ref=article_ref,
            text=raw,
            start_offset=start,
            end_offset=end,
            text_sha256=sha256_text(raw),
            raw_text=raw,
            normalized_text=processed.normalized_text,
            language=processed.language,
        ))
    return clauses


def register_document_version(
    payload: DocumentVersionCreate,
    *,
    db_path: Path | str | None = None,
) -> tuple[DocumentVersion, list[Clause], list[str]]:
    source = db.get_source(payload.source_id, db_path)
    if not source:
        raise KeyError(f"unknown source: {payload.source_id}")
    if source["approval_status"] != "approved":
        raise PermissionError("only approved sources can enter analysis")
    content = normalize_text(payload.content)
    raw_hash = sha256_text(payload.content)
    text_hash = sha256_text(content)
    version = DocumentVersion(
        version_id=db.stable_id("ver", payload.source_id, raw_hash),
        source_id=payload.source_id,
        sha256=raw_hash,
        text_sha256=text_hash,
        content=content,
        published_at=payload.published_at,
        effective_at=payload.effective_at,
        retrieved_at=datetime.now(timezone.utc),
        supersedes_version_id=payload.supersedes_version_id,
        is_simulated=payload.is_simulated,
        simulation_notice=payload.simulation_notice,
        legal_status="effective",
    )
    stored = db.insert_document_version(version, db_path)
    clauses = extract_clauses(stored.version_id, stored.content)
    for clause in clauses:
        db.insert_clause(clause, db_path)
    return stored, clauses, detect_prompt_injection(content)


def load_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")
