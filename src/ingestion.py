from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timezone
from pathlib import Path

from . import db
from .schemas import Clause, DocumentVersion, DocumentVersionCreate


ARTICLE_PATTERN = re.compile(
    r"^(?P<ref>(?:Article|Section|Clause|المادة|القسم)\s+[\w.-]+)(?:\s*[-–—:]\s*|\s+)(?P<body>.*)$",
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
        return [Clause(
            clause_id=db.stable_id("clause", version_id, "Document", sha256_text(text)),
            version_id=version_id,
            article_ref="Document",
            text=text,
            start_offset=0,
            end_offset=len(text),
            text_sha256=sha256_text(text),
        )]
    clauses: list[Clause] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        raw = text[start:end].strip()
        article_ref = match.group("ref").strip()
        clauses.append(Clause(
            clause_id=db.stable_id("clause", version_id, article_ref, sha256_text(raw)),
            version_id=version_id,
            article_ref=article_ref,
            text=raw,
            start_offset=start,
            end_offset=end,
            text_sha256=sha256_text(raw),
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
    )
    stored = db.insert_document_version(version, db_path)
    clauses = extract_clauses(stored.version_id, stored.content)
    for clause in clauses:
        db.insert_clause(clause, db_path)
    return stored, clauses, detect_prompt_injection(content)


def load_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")
