"""وحدة استخراج المستندات الموحدة وتجريد الـ OCR (Unified Document Processing & OCR Abstraction) لمشروع مآل.

تضمن هذه الوحدة:
1. استخراج النصوص بدقة متناهية مع كامل بيانات الموضع (Exact Locators).
2. الحفاظ على النص الخام (raw_text) وتوليد النص المعياري (normalized_text) وتحديد اللغة.
3. تقييم جودة الاستخراج وتصنيف المستندات إلى:
   - extraction_success: استخراج ناجح وكثافة نصية قياسية.
   - partial_extraction: استخراج جزئي لبعض الصفحات أو المقاطع.
   - low_quality: جودة منخفضة وتشويش نصي.
   - OCR_required: مستند مصور بالكامل يتطلب معالجة ضوئية، مع الامتناع الصارم عن ادعاء قراءته.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from pypdf import PdfReader

from .arabic_processing import normalize_arabic_letters, process_text


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".csv"}

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


@dataclass(frozen=True)
class ExtractedChunk:
    locator: dict[str, Any]
    raw_text: str
    normalized_text: str
    language: str
    section_ref: str | None = None
    extraction_quality: str = "extraction_success"


@dataclass(frozen=True)
class DocumentExtractionResult:
    chunks: list[ExtractedChunk]
    overall_quality: str  # extraction_success, partial_extraction, low_quality, OCR_required
    total_words: int
    page_count: int
    quality_summary: str


def _clean_raw(text: str) -> str:
    """تنظيف المحارف الصفرية والمسافات الزائدة مع الحفاظ على الكلمات الأصلية."""
    return " ".join(text.replace("\x00", " ").split())


def _build_chunk(
    locator: dict[str, Any],
    raw_text: str,
    section: str | None = None,
    quality: str = "extraction_success",
) -> ExtractedChunk:
    cleaned = _clean_raw(raw_text)
    processed = process_text(cleaned)
    return ExtractedChunk(
        locator=locator,
        raw_text=processed.raw_text,
        normalized_text=processed.normalized_text,
        language=processed.language,
        section_ref=section,
        extraction_quality=quality,
    )


def _parse_pdf(raw: bytes) -> DocumentExtractionResult:
    reader = PdfReader(io.BytesIO(raw))
    pages = reader.pages
    page_count = len(pages)
    if page_count == 0:
        return DocumentExtractionResult([], "low_quality", 0, 0, "الملف فارغ من الصفحات")

    chunks: list[ExtractedChunk] = []
    empty_pages = 0
    total_words = 0

    for i, page in enumerate(pages, 1):
        extracted = page.extract_text() or ""
        cleaned = _clean_raw(extracted)
        words = len(cleaned.split())
        total_words += words

        if not cleaned:
            empty_pages += 1
            continue

        # فحص جودة استخراج الصفحة
        quality = "extraction_success"
        if words < 5:
            quality = "low_quality"

        chunks.append(_build_chunk(
            {"locator_type": "page", "page": i},
            cleaned,
            f"Page {i}",
            quality=quality,
        ))

    # تقييم جودة المستند الإجمالية
    if len(chunks) == 0 or total_words == 0:
        return DocumentExtractionResult(
            [],
            "OCR_required",
            0,
            page_count,
            "المستند مصور بالكامل ولا يحتوي نصوصاً قابلة للاستخراج برمجياً. يلزم التعرف الضوئي (OCR).",
        )

    if empty_pages > 0 and empty_pages == page_count:
        return DocumentExtractionResult([], "OCR_required", 0, page_count, "الملف يحتاج OCR.")

    if empty_pages > 0:
        overall = "partial_extraction"
        summary = f"تم استخراج نصوص {len(chunks)} صفحة من أصل {page_count}، وتوجد صفحات ممسوحة تحتاج OCR."
    elif total_words / page_count < 15:
        overall = "low_quality"
        summary = "كثافة النصوص المستخرجة منخفضة جداً وقد تكون ناتجة عن مسح غير واضح."
    else:
        overall = "extraction_success"
        summary = f"تم استخراج نصوص كاملة لـ {len(chunks)} صفحة بجودة قياسية."

    return DocumentExtractionResult(chunks, overall, total_words, page_count, summary)


def _parse_docx(raw: bytes) -> DocumentExtractionResult:
    chunks: list[ExtractedChunk] = []
    section = None
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))

    paragraph_no = 0
    total_words = 0
    for node in root.iter():
        if node.tag == W + "p":
            text = _clean_raw("".join(item.text or "" for item in node.iter(W + "t")))
            if not text:
                continue
            paragraph_no += 1
            total_words += len(text.split())
            style = node.find(f".//{W}pStyle")
            style_name = style.get(W + "val", "") if style is not None else ""
            if style_name.casefold().startswith("heading") or "عنوان" in style_name:
                section = text

            chunks.append(_build_chunk(
                {
                    "locator_type": "section",
                    "section": section,
                    "paragraph": paragraph_no,
                },
                text,
                section,
            ))

    overall = "extraction_success" if chunks else "low_quality"
    summary = f"تم استخراج {len(chunks)} فقرة مهيكلة بنجاح." if chunks else "الملف لا يحتوي على فقرات نصية."
    return DocumentExtractionResult(chunks, overall, total_words, 1, summary)


def _xlsx_shared(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return [_clean_raw("".join(t.text or "" for t in item.iter(S + "t"))) for item in root]


def _parse_xlsx(raw: bytes) -> DocumentExtractionResult:
    chunks: list[ExtractedChunk] = []
    total_words = 0
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        shared = _xlsx_shared(archive)
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_map = {item.get("Id"): item.get("Target") for item in rels}

        for sheet in workbook.findall(f".//{S}sheet"):
            name = sheet.get("name", "Sheet")
            rel_id = sheet.get(R + "id")
            target = rel_map.get(rel_id, "")
            path = "xl/" + target.lstrip("/") if not target.startswith("xl/") else target
            if path not in archive.namelist():
                continue
            root = ET.fromstring(archive.read(path))
            for cell in root.findall(f".//{S}c"):
                ref = cell.get("r", "")
                kind = cell.get("t")
                value_node = cell.find(S + "v")
                inline = cell.find(f".//{S}t")
                value = inline.text if inline is not None else (value_node.text if value_node is not None else "")
                if kind == "s" and value:
                    try:
                        value = shared[int(value)]
                    except (ValueError, IndexError):
                        pass
                value = _clean_raw(value or "")
                if value:
                    total_words += len(value.split())
                    row_match = re.search(r"\d+", ref)
                    col_match = re.match(r"[A-Z]+", ref)
                    chunks.append(_build_chunk(
                        {
                            "locator_type": "sheet_cell",
                            "sheet": name,
                            "cell": ref,
                            "row": int(row_match.group()) if row_match else None,
                            "column": col_match.group() if col_match else None,
                        },
                        value,
                        name,
                    ))

    overall = "extraction_success" if chunks else "low_quality"
    summary = f"تم استخراج {len(chunks)} خلية جدولية بنجاح." if chunks else "جدول البيانات فارغ."
    return DocumentExtractionResult(chunks, overall, total_words, 1, summary)


def _parse_pptx(raw: bytes) -> DocumentExtractionResult:
    chunks: list[ExtractedChunk] = []
    total_words = 0
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        slides = sorted(
            (p for p in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", p)),
            key=lambda p: int(re.search(r"\d+", Path(p).stem).group()),
        )
        for number, path in enumerate(slides, 1):
            root = ET.fromstring(archive.read(path))
            texts = [_clean_raw(t.text or "") for t in root.iter(A + "t") if _clean_raw(t.text or "")]
            if texts:
                slide_text = " ".join(texts)
                total_words += len(slide_text.split())
                chunks.append(_build_chunk(
                    {"locator_type": "slide", "slide": number},
                    slide_text,
                    f"Slide {number}",
                ))

    overall = "extraction_success" if chunks else "low_quality"
    summary = f"تم استخراج {len(chunks)} شريحة عرض." if chunks else "العرض التقديمي لا يحتوي نصوصاً."
    return DocumentExtractionResult(chunks, overall, total_words, len(chunks), summary)


def _parse_text(raw: bytes) -> DocumentExtractionResult:
    text = raw.decode("utf-8-sig", errors="replace")
    chunks: list[ExtractedChunk] = []
    total_words = 0
    for i, line in enumerate(text.splitlines(), 1):
        cleaned = _clean_raw(line)
        if cleaned:
            total_words += len(cleaned.split())
            chunks.append(_build_chunk(
                {"locator_type": "line", "line_start": i, "line_end": i},
                cleaned,
                f"Line {i}",
            ))
    overall = "extraction_success" if chunks else "low_quality"
    summary = f"تم استخراج {len(chunks)} سطراً نصياً."
    return DocumentExtractionResult(chunks, overall, total_words, 1, summary)


def _column_name(index: int) -> str:
    value = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        value = chr(65 + remainder) + value
    return value


def _parse_csv(raw: bytes) -> DocumentExtractionResult:
    text = raw.decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096])
    except csv.Error:
        dialect = csv.excel
    chunks: list[ExtractedChunk] = []
    total_words = 0
    for row_no, row in enumerate(csv.reader(io.StringIO(text), dialect), 1):
        for col_no, value in enumerate(row, 1):
            cleaned = _clean_raw(value)
            if cleaned:
                col = _column_name(col_no)
                total_words += len(cleaned.split())
                chunks.append(_build_chunk(
                    {
                        "locator_type": "csv_cell",
                        "sheet": "CSV",
                        "cell": f"{col}{row_no}",
                        "row": row_no,
                        "column": col,
                    },
                    cleaned,
                    "CSV",
                ))
    overall = "extraction_success" if chunks else "low_quality"
    summary = f"تم استخراج {len(chunks)} خلية CSV بنجاح."
    return DocumentExtractionResult(chunks, overall, total_words, 1, summary)


PARSERS = {
    ".pdf": _parse_pdf,
    ".docx": _parse_docx,
    ".xlsx": _parse_xlsx,
    ".pptx": _parse_pptx,
    ".txt": _parse_text,
    ".csv": _parse_csv,
}


def extract_document_content(raw: bytes, filename: str) -> DocumentExtractionResult:
    """استخراج محتوى المستند بدقة متناهية وتحديد جودته وتجريد الـ OCR."""
    suffix = Path(filename).suffix.lower()
    if suffix not in PARSERS:
        raise ValueError(f"صيغة الملف غير مدعومة: {suffix}")
    return PARSERS[suffix](raw)
