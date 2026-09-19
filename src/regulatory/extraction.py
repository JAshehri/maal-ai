from __future__ import annotations

import hashlib
from io import BytesIO

from bs4 import BeautifulSoup
from pypdf import PdfReader

from ..ingestion import normalize_text


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def extract_official_text(content: bytes, content_type: str, filename: str) -> tuple[str, list[str]]:
    lowered = filename.casefold()
    warnings: list[str] = []
    if content_type == "application/pdf" or lowered.endswith(".pdf"):
        reader = PdfReader(BytesIO(content))
        pages = []
        for number, page in enumerate(reader.pages, start=1):
            extracted = page.extract_text() or ""
            pages.append(f"Page {number}\n{extracted}")
        text = normalize_text("\n\n".join(pages))
        if not text:
            warnings.append("pdf_has_no_extractable_text_ocr_required")
        return text, warnings
    if content_type in {"text/html", "application/xhtml+xml"} or lowered.endswith((".html", ".htm")):
        soup = BeautifulSoup(content, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "noscript"]):
            tag.decompose()
        return normalize_text(soup.get_text("\n", strip=True)), warnings
    if content_type.startswith("text/") or lowered.endswith((".txt", ".csv")):
        return normalize_text(content.decode("utf-8-sig", errors="replace")), warnings
    raise ValueError(f"unsupported regulatory document type: {content_type or filename}")
