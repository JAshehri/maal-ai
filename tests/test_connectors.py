from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import httpx

from src import db
from src.demo import seed_demo
from src.regulatory.connectors.base import RegulatorySourceConnector
from src.regulatory.connectors.nca import NCAConnector
from src.regulatory.connectors.saso import SASOConnector
from src.regulatory.discovery import create_regulatory_scan, execute_regulatory_scan
from src.regulatory.registry import seed_regulatory_sources
from src.schemas import FetchedDocument, RegulatoryDocument, RegulatoryScanCreate


class _FakeConnector(RegulatorySourceConnector):
    connector_type = "nca_html"
    allowed_hosts = frozenset({"nca.gov.sa"})

    def __init__(self, source_id: str, content: str) -> None:
        super().__init__()
        self.source_id = source_id
        self.content = content

    def discover(self, source_id: str) -> list[RegulatoryDocument]:
        return [RegulatoryDocument(
            document_id=db.stable_id("regdoc", source_id, "https://nca.gov.sa/test"),
            source_id=source_id, authority="NCA", jurisdiction="SA",
            regulatory_domain="Cybersecurity", title="Essential Cybersecurity Controls",
            document_type="cybersecurity_controls", category="Essential Cybersecurity Controls",
            canonical_url="https://nca.gov.sa/test", download_url="https://nca.gov.sa/test.txt",
        )]

    def fetch_document(self, document: RegulatoryDocument) -> FetchedDocument:
        return FetchedDocument(
            document=document, content=self.content.encode(), content_type="text/plain",
            final_url=document.download_url or document.canonical_url,
            filename="test.txt", http_status=200,
        )


class _IrrelevantSASOConnector(RegulatorySourceConnector):
    connector_type = "saso_html"
    allowed_hosts = frozenset({"www.saso.gov.sa"})

    def __init__(self, source_id: str) -> None:
        super().__init__()
        self.source_id = source_id
        self.fetch_called = False

    def discover(self, source_id: str) -> list[RegulatoryDocument]:
        return [RegulatoryDocument(
            document_id=db.stable_id("regdoc", source_id, "https://www.saso.gov.sa/chemical.pdf"),
            source_id=source_id, authority="SASO", jurisdiction="SA",
            regulatory_domain="Product Standards / Technical Regulations / Conformity",
            title="لائحة كيميائية غير مرتبطة بمنتجات المنشأة التجريبية",
            document_type="technical_regulation", category="Chemical",
            canonical_url="https://www.saso.gov.sa/chemical.pdf",
            download_url="https://www.saso.gov.sa/chemical.pdf",
        )]

    def fetch_document(self, document: RegulatoryDocument) -> FetchedDocument:
        self.fetch_called = True
        raise AssertionError("irrelevant regulation must be filtered before download/impact analysis")


class _UnprovenNCAConnector(RegulatorySourceConnector):
    connector_type = "nca_html"
    allowed_hosts = frozenset({"nca.gov.sa"})

    def __init__(self, source_id: str) -> None:
        super().__init__()
        self.source_id = source_id
        self.fetch_called = False

    def discover(self, source_id: str) -> list[RegulatoryDocument]:
        return [RegulatoryDocument(
            document_id=db.stable_id("regdoc", source_id, "https://nca.gov.sa/cscc"),
            source_id=source_id, authority="NCA", jurisdiction="SA",
            regulatory_domain="Cybersecurity", title="Critical Systems Cybersecurity Controls",
            document_type="cybersecurity_controls", category="Critical Systems Cybersecurity Controls",
            canonical_url="https://nca.gov.sa/cscc", download_url="https://nca.gov.sa/cscc.pdf",
        )]

    def fetch_document(self, document: RegulatoryDocument) -> FetchedDocument:
        self.fetch_called = True
        raise AssertionError("unproven scope must stop for review before download/impact analysis")


class _GenericMechanicalSASOConnector(_IrrelevantSASOConnector):
    def discover(self, source_id: str) -> list[RegulatoryDocument]:
        return [RegulatoryDocument(
            document_id=db.stable_id("regdoc", source_id, "https://www.saso.gov.sa/tanks.pdf"),
            source_id=source_id, authority="SASO", jurisdiction="SA",
            regulatory_domain="Product Standards / Technical Regulations / Conformity",
            title="اللائحة الفنية لصهاريج نقل الغاز الجاف",
            document_type="technical_regulation", category="Mechanical",
            canonical_url="https://www.saso.gov.sa/tanks.pdf",
            download_url="https://www.saso.gov.sa/tanks.pdf",
        )]


class _ExcludedElectricalSASOConnector(_IrrelevantSASOConnector):
    def discover(self, source_id: str) -> list[RegulatoryDocument]:
        return [RegulatoryDocument(
            document_id=db.stable_id("regdoc", source_id, "https://www.saso.gov.sa/electric-vehicles.pdf"),
            source_id=source_id, authority="SASO", jurisdiction="SA",
            regulatory_domain="Product Standards / Technical Regulations / Conformity",
            title="اللائحة الفنية للمركبات الكهربائية",
            document_type="technical_regulation", category="Electrical",
            canonical_url="https://www.saso.gov.sa/electric-vehicles.pdf",
            download_url="https://www.saso.gov.sa/electric-vehicles.pdf",
        )]


class ConnectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "test.db"
        db.init_db(self.db_path)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_nca_discovers_requested_control_families(self) -> None:
        index = "".join(
            f'<a href="/ar/regulatory-documents/controls-list/{slug}/">{slug}</a>'
            for slug in ("ecc", "cscc", "ccc", "otcc", "dcc")
        )

        def handler(request: httpx.Request) -> httpx.Response:
            if "documentType=controls-list" in str(request.url):
                return httpx.Response(200, text=index, request=request)
            slug = str(request.url).rstrip("/").split("/")[-1]
            html = f"<h1>{slug.upper()}</h1><p>02/06/2022</p><p>تاريخ آخر تعديل: 03/11/2025</p>"
            html += f'<a href="https://cdn.nca.gov.sa/{slug}.pdf">{slug} controls</a>'
            return httpx.Response(200, text=html, request=request)

        connector = NCAConnector(transport=httpx.MockTransport(handler))
        documents = connector.discover("source_nca")
        self.assertEqual({item.metadata["slug"] for item in documents}, {"ecc", "cscc", "ccc", "otcc", "dcc"})
        self.assertTrue(all(item.download_url and item.download_url.endswith(".pdf") for item in documents))
        self.assertTrue(all(item.last_modified_at for item in documents))

    def test_saso_parses_dates_categories_and_expanded_page(self) -> None:
        initial = """<form><input name="__VIEWSTATE" value="x">
        <select id="x_DDL_PageSize" name="x$DDL_PageSize"><option value="12">12</option><option value="100">100</option></select></form>"""
        expanded = """
        <a class="rulesAndRegulationsListItem" href="/ar/Laws-And-Regulations/Technical_regulations/Documents/electrical.pdf">
          <h2>اللائحة الفنية للأجهزة الكهربائية والإلكترونية</h2>
          تاريخ الاعتماد: 28/09/2023 تاريخ النشر: 17/11/2023 التطبيق الإلزامي: 01/01/2024 تحميل
        </a>"""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=expanded if request.method == "POST" else initial, request=request)

        documents = SASOConnector(transport=httpx.MockTransport(handler)).discover("source_saso")
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0].category, "Electrical")
        self.assertEqual(documents[0].approval_date.isoformat(), "2023-09-28")
        self.assertEqual(documents[0].mandatory_application_date.isoformat(), "2024-01-01")

    def test_scan_stores_new_noops_then_versions_changed_content(self) -> None:
        seeded = seed_demo(self.db_path)
        sources = seed_regulatory_sources(self.db_path)
        source_id = sources["NCA"]

        def run(key: str, content: str) -> dict:
            request = RegulatoryScanCreate(
                company_snapshot_id=seeded["discovery_company_snapshot_id"], source_ids=[source_id],
                idempotency_key=key,
            )
            scan, created = create_regulatory_scan(request, self.db_path)
            self.assertTrue(created)
            return execute_regulatory_scan(
                scan["scan_id"], request=request, db_path=self.db_path,
                connector_overrides={source_id: _FakeConnector(source_id, content)},
            )

        first = run("connector-scan-one", "Article 1 The organization must retain logs for 12 months.")
        second = run("connector-scan-two", "Article 1 The organization must retain logs for 12 months.")
        third = run("connector-scan-three", "Article 1 The organization must retain logs for 18 months.")
        self.assertEqual(first["versions_created"], 1)
        self.assertEqual(second["unchanged_documents"], 1)
        self.assertEqual(third["versions_created"], 1)
        self.assertEqual(third["changes_created"], 1)
        third_result = db.get_scan_results(third["scan_id"], self.db_path)[0]
        self.assertIsNotNone(third_result["analysis_run_id"])
        self.assertIsNotNone(db.get_run(third_result["analysis_run_id"], self.db_path))
        versions = db.list_document_versions(source_id, self.db_path)
        self.assertEqual(len(versions), 2)
        self.assertEqual(versions[0]["supersedes_version_id"], versions[1]["version_id"])

    def test_irrelevant_saso_document_is_filtered_before_fetch(self) -> None:
        seeded = seed_demo(self.db_path)
        source_id = seed_regulatory_sources(self.db_path)["SASO"]
        connector = _IrrelevantSASOConnector(source_id)
        request = RegulatoryScanCreate(
            company_snapshot_id=seeded["discovery_company_snapshot_id"],
            source_ids=[source_id], idempotency_key="filtered-before-fetch",
        )
        scan, _ = create_regulatory_scan(request, self.db_path)
        result = execute_regulatory_scan(
            scan["scan_id"], request=request, db_path=self.db_path,
            connector_overrides={source_id: connector},
        )
        self.assertFalse(connector.fetch_called)
        self.assertEqual(result["filtered_documents"], 1)
        self.assertEqual(result["versions_created"], 0)
        self.assertEqual(db.get_scan_results(scan["scan_id"], self.db_path)[0]["outcome"], "filtered")

    def test_missing_scope_fact_stops_before_fetch_and_impact(self) -> None:
        seeded = seed_demo(self.db_path)
        source_id = seed_regulatory_sources(self.db_path)["NCA"]
        connector = _UnprovenNCAConnector(source_id)
        request = RegulatoryScanCreate(
            company_snapshot_id=seeded["discovery_company_snapshot_id"],
            source_ids=[source_id], idempotency_key="missing-scope-stops-before-fetch",
        )
        scan, _ = create_regulatory_scan(request, self.db_path)
        result = execute_regulatory_scan(
            scan["scan_id"], request=request, db_path=self.db_path,
            connector_overrides={source_id: connector},
        )
        self.assertFalse(connector.fetch_called)
        self.assertEqual(result["versions_created"], 0)
        row = db.get_scan_results(scan["scan_id"], self.db_path)[0]
        self.assertEqual(row["outcome"], "needs_review")
        self.assertEqual(row["applicability_status"], "needs_review")
        self.assertIsNone(row["analysis_run_id"])

    def test_generic_manufacturing_does_not_prove_specific_saso_product_scope(self) -> None:
        seeded = seed_demo(self.db_path)
        source_id = seed_regulatory_sources(self.db_path)["SASO"]
        connector = _GenericMechanicalSASOConnector(source_id)
        request = RegulatoryScanCreate(
            company_snapshot_id=seeded["discovery_company_snapshot_id"],
            source_ids=[source_id], idempotency_key="generic-manufacturing-not-product-scope",
        )
        scan, _ = create_regulatory_scan(request, self.db_path)
        result = execute_regulatory_scan(
            scan["scan_id"], request=request, db_path=self.db_path,
            connector_overrides={source_id: connector},
        )
        self.assertFalse(connector.fetch_called)
        self.assertEqual(result["versions_created"], 0)
        row = db.get_scan_results(scan["scan_id"], self.db_path)[0]
        self.assertEqual(row["outcome"], "needs_review")
        self.assertEqual(row["applicability_status"], "needs_review")

    def test_electrical_label_alone_does_not_prove_excluded_product_scope(self) -> None:
        seeded = seed_demo(self.db_path)
        source_id = seed_regulatory_sources(self.db_path)["SASO"]
        connector = _ExcludedElectricalSASOConnector(source_id)
        request = RegulatoryScanCreate(
            company_snapshot_id=seeded["discovery_company_snapshot_id"],
            source_ids=[source_id], idempotency_key="electric-label-not-product-scope",
        )
        scan, _ = create_regulatory_scan(request, self.db_path)
        execute_regulatory_scan(
            scan["scan_id"], request=request, db_path=self.db_path,
            connector_overrides={source_id: connector},
        )
        self.assertFalse(connector.fetch_called)
        row = db.get_scan_results(scan["scan_id"], self.db_path)[0]
        self.assertEqual(row["outcome"], "needs_review")
        self.assertEqual(row["applicability_status"], "needs_review")


if __name__ == "__main__":
    unittest.main()
