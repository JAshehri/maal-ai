from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from pypdf import PdfReader

from . import db
from .ingestion import detect_prompt_injection
from .schemas import CompanyDocument, CompanyDocumentChunk, DocumentLocator
from .settings import settings


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".csv"}
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def _clean(text: str) -> str:
    return " ".join(text.replace("\x00", " ").split())


def _chunk(locator: dict, text: str, section: str | None = None) -> dict:
    return {"locator": locator, "text": _clean(text), "section_ref": section}


def _parse_pdf(raw: bytes) -> list[dict]:
    reader = PdfReader(io.BytesIO(raw))
    return [_chunk({"locator_type": "page", "page": i}, page.extract_text() or "")
            for i, page in enumerate(reader.pages, 1) if _clean(page.extract_text() or "")]


def _parse_docx(raw: bytes) -> list[dict]:
    result, section = [], None
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    paragraph_no = 0
    for node in root.iter():
        if node.tag == W + "p":
            text = _clean("".join(item.text or "" for item in node.iter(W + "t")))
            if not text:
                continue
            paragraph_no += 1
            style = node.find(f".//{W}pStyle")
            style_name = style.get(W + "val", "") if style is not None else ""
            if style_name.casefold().startswith("heading"):
                section = text
            result.append(_chunk({"locator_type": "section", "section": section,
                                  "paragraph": paragraph_no}, text, section))
    return result


def _xlsx_shared(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return [_clean("".join(t.text or "" for t in item.iter(S + "t"))) for item in root]


def _parse_xlsx(raw: bytes) -> list[dict]:
    result = []
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        shared = _xlsx_shared(archive)
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_map = {item.get("Id"): item.get("Target") for item in rels}
        for sheet in workbook.findall(f".//{S}sheet"):
            name, rel_id = sheet.get("name", "Sheet"), sheet.get(R + "id")
            target = rel_map.get(rel_id, "")
            path = "xl/" + target.lstrip("/") if not target.startswith("xl/") else target
            if path not in archive.namelist():
                continue
            root = ET.fromstring(archive.read(path))
            for cell in root.findall(f".//{S}c"):
                ref, kind = cell.get("r", ""), cell.get("t")
                value_node = cell.find(S + "v")
                inline = cell.find(f".//{S}t")
                value = inline.text if inline is not None else (value_node.text if value_node is not None else "")
                if kind == "s" and value:
                    try: value = shared[int(value)]
                    except (ValueError, IndexError): pass
                value = _clean(value or "")
                if value:
                    row_match = re.search(r"\d+", ref)
                    col_match = re.match(r"[A-Z]+", ref)
                    result.append(_chunk({"locator_type": "sheet_cell", "sheet": name, "cell": ref,
                                          "row": int(row_match.group()) if row_match else None,
                                          "column": col_match.group() if col_match else None}, value, name))
    return result


def _parse_pptx(raw: bytes) -> list[dict]:
    result = []
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        slides = sorted((p for p in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", p)),
                        key=lambda p: int(re.search(r"\d+", Path(p).stem).group()))
        for number, path in enumerate(slides, 1):
            root = ET.fromstring(archive.read(path))
            texts = [_clean(t.text or "") for t in root.iter(A + "t") if _clean(t.text or "")]
            if texts:
                result.append(_chunk({"locator_type": "slide", "slide": number}, " ".join(texts), f"Slide {number}"))
    return result


def _parse_text(raw: bytes) -> list[dict]:
    text = raw.decode("utf-8-sig", errors="replace")
    return [_chunk({"locator_type": "line", "line_start": i, "line_end": i}, line)
            for i, line in enumerate(text.splitlines(), 1) if _clean(line)]


def _column_name(index: int) -> str:
    value = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        value = chr(65 + remainder) + value
    return value


def _parse_csv(raw: bytes) -> list[dict]:
    text = raw.decode("utf-8-sig", errors="replace")
    try: dialect = csv.Sniffer().sniff(text[:4096])
    except csv.Error: dialect = csv.excel
    result = []
    for row_no, row in enumerate(csv.reader(io.StringIO(text), dialect), 1):
        for col_no, value in enumerate(row, 1):
            value = _clean(value)
            if value:
                col = _column_name(col_no)
                result.append(_chunk({"locator_type": "csv_cell", "sheet": "CSV", "cell": f"{col}{row_no}",
                                      "row": row_no, "column": col}, value, "CSV"))
    return result


PARSERS = {".pdf": _parse_pdf, ".docx": _parse_docx, ".xlsx": _parse_xlsx,
           ".pptx": _parse_pptx, ".txt": _parse_text, ".csv": _parse_csv}


def ingest_company_document(*, raw: bytes, filename: str, mime_type: str,
                            company_snapshot_id: str, document_kind: str,
                            title: str | None = None, department: str | None = None,
                            project_id: str | None = None, db_path=None) -> dict:
    snapshot = db.get_company_snapshot(company_snapshot_id, db_path)
    if not snapshot:
        raise KeyError("company snapshot not found")
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"unsupported company document format: {suffix or 'none'}")
    digest = hashlib.sha256(raw).hexdigest()
    document_id = db.stable_id("cdoc", company_snapshot_id, digest, document_kind)
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(filename).name).strip("-") or f"document{suffix}"
    root = (settings.root_dir / "data" / "company" / "raw").resolve()
    storage = (root / document_id / f"{digest}-{safe_name}").resolve()
    if root not in storage.parents:
        raise ValueError("unsafe company document storage path")
    storage.parent.mkdir(parents=True, exist_ok=True)
    if not storage.exists(): storage.write_bytes(raw)
    parsed = PARSERS[suffix](raw)
    if not parsed:
        raise ValueError("document contains no extractable text")
    document = CompanyDocument(
        company_document_id=document_id, company_snapshot_id=company_snapshot_id,
        company_id=snapshot.company_id, title=title or Path(filename).stem,
        filename=Path(filename).name, mime_type=mime_type, document_kind=document_kind,
        department=department, project_id=project_id, sha256=digest,
        storage_uri=str(storage.relative_to(settings.root_dir)).replace("\\", "/"),
        metadata={"format": suffix[1:], "chunk_count": len(parsed)},
    )
    stored = db.insert_company_document(document, db_path)
    chunks = []
    for index, item in enumerate(parsed, 1):
        chunk = CompanyDocumentChunk(
            chunk_id=db.stable_id("chunk", document_id, str(index), item["text"]),
            company_document_id=document_id, sequence_no=index,
            locator=DocumentLocator.model_validate(item["locator"]),
            section_ref=item.get("section_ref"), text=item["text"],
            text_sha256=hashlib.sha256(item["text"].encode("utf-8")).hexdigest(),
        )
        chunks.append(db.insert_company_document_chunk(chunk, db_path))
    warnings = sorted(set(w for item in chunks for w in detect_prompt_injection(item.text)))
    return {"document": stored.model_dump(mode="json"),
            "chunks": [item.model_dump(mode="json") for item in chunks],
            "security_warnings": warnings}
