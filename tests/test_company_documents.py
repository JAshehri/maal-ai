from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from src import db
from src.company_documents import ingest_company_document
from src.compliance_review import create_compliance_review, impact_graph, seed_core_demo
from src.schemas import ComplianceReviewCreate


def zipped(files: dict[str, str]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()


def pdf_bytes() -> bytes:
    output = io.BytesIO()
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 72 720 Td (Article 5.1 limit 100 mg/Nm3) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.write(output)
    return output.getvalue()


class CompanyDocumentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "test.db"
        self.context = seed_core_demo(self.db_path)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _ingest(self, raw: bytes, filename: str) -> dict:
        return ingest_company_document(
            raw=raw, filename=filename, mime_type="application/octet-stream",
            company_snapshot_id=self.context["company_snapshot_id"], document_kind="evidence",
            db_path=self.db_path,
        )

    def test_supported_formats_preserve_exact_locators(self) -> None:
        docx = zipped({"word/document.xml": """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Controls</w:t></w:r></w:p><w:p><w:r><w:t>Requirement evidence</w:t></w:r></w:p></w:body></w:document>"""})
        xlsx = zipped({
            "xl/workbook.xml": """<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Risk" sheetId="1" r:id="rId1"/></sheets></workbook>""",
            "xl/_rels/workbook.xml.rels": """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>""",
            "xl/worksheets/sheet1.xml": """<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="2"><c r="B2" t="inlineStr"><is><t>Requirement evidence</t></is></c></row></sheetData></worksheet>""",
        })
        pptx = zipped({"ppt/slides/slide1.xml": """<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><a:t>Requirement evidence</a:t></p:cSld></p:sld>"""})
        cases = [
            (pdf_bytes(), "test.pdf", "page"),
            (docx, "test.docx", "section"),
            (xlsx, "test.xlsx", "sheet_cell"),
            (pptx, "test.pptx", "slide"),
            (b"line one\nline two", "test.txt", "line"),
            (b"control,value\nNOx,100", "test.csv", "csv_cell"),
        ]
        for raw, filename, locator_type in cases:
            with self.subTest(filename=filename):
                result = self._ingest(raw, filename)
                self.assertTrue(result["chunks"])
                self.assertEqual(locator_type, result["chunks"][0]["locator"]["locator_type"])

    def test_end_to_end_superseded_requirement_review(self) -> None:
        raw = (Path(__file__).parents[1] / "data" / "demo" / "new_project_proposal.txt").read_bytes()
        ingested = ingest_company_document(
            raw=raw, filename="proposal.txt", mime_type="text/plain",
            company_snapshot_id=self.context["company_snapshot_id"], document_kind="project_proposal",
            department="Environmental Engineering", project_id="Advanced Manufacturing Expansion",
            db_path=self.db_path,
        )
        review = create_compliance_review(ComplianceReviewCreate(
            company_document_id=ingested["document"]["company_document_id"],
            company_snapshot_id=self.context["company_snapshot_id"], idempotency_key="e2e-review-0001",
        ), self.db_path)
        self.assertEqual(0.0, review["weighted_score"])
        self.assertEqual("Recently superseded requirement detected", review["summary"]["warning"])
        self.assertEqual("non_compliant", review["findings"][0]["status"])
        self.assertEqual(5, review["findings"][0]["locator"]["line_start"])
        self.assertIn("Article 5.1", review["findings"][0]["regulatory_quote"])
        self.assertEqual(385000.0, review["financial_exposure"]["total"])
        self.assertEqual("not_enough_data", review["financial_exposure"]["breakdown"]["direct_regulatory_penalty"]["status"])
        graph = impact_graph(self.db_path)
        self.assertTrue({"Regulation", "Article", "Obligation", "Internal Document", "Section", "Department", "Project"}.issubset({n["type"] for n in graph["nodes"]}))

