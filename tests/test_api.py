from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from src.settings import settings


class ApiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        cls.original_db_path = settings.database_path
        object.__setattr__(settings, "database_path", Path(cls.temp.name) / "api.db")
        from app import app
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()
        cls.analyst = {"X-Role": "analyst", "X-User-Id": "analyst-test"}
        cls.reviewer = {"X-Role": "reviewer", "X-User-Id": "reviewer-test"}
        cls.admin = {"X-Role": "admin", "X-User-Id": "admin-test"}

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client_context.__exit__(None, None, None)
        object.__setattr__(settings, "database_path", cls.original_db_path)
        cls.temp.cleanup()

    def _start_run(self, key: str) -> str:
        context = self.client.get("/demo/context", headers=self.analyst).json()
        response = self.client.post("/runs", headers=self.analyst, json={
            "company_snapshot_id": context["company_snapshot_id"],
            "old_version_id": context["old_version_id"],
            "new_version_id": context["new_version_id"],
            "idempotency_key": key,
        })
        self.assertEqual(202, response.status_code, response.text)
        return response.json()["run_id"]

    def test_health_ready_and_async_run_contract(self) -> None:
        self.assertEqual(200, self.client.get("/health").status_code)
        self.assertEqual("ready", self.client.get("/ready").json()["status"])
        run_id = self._start_run("api-contract-0001")
        status_response = self.client.get(f"/runs/{run_id}", headers=self.analyst)
        self.assertEqual(200, status_response.status_code)
        self.assertIn(status_response.json()["run"]["phase"], {"queued", "awaiting_review", "completed"})
        findings = self.client.get(f"/runs/{run_id}/findings", headers=self.analyst).json()
        self.assertEqual(1, len(findings["tasks"]))

    def test_unauthorized_and_stale_review_status_codes(self) -> None:
        run_id = self._start_run("api-review-0001")
        task = self.client.get(f"/runs/{run_id}/findings", headers=self.analyst).json()["tasks"][0]
        payload = {"decision": "approve", "expected_revision": task["revision"], "comment": "Reviewed evidence", "edited_fields": {}}
        forbidden = self.client.post(f"/tasks/{task['task_id']}/review", headers=self.analyst, json=payload)
        self.assertEqual(403, forbidden.status_code)
        accepted = self.client.post(f"/tasks/{task['task_id']}/review", headers=self.reviewer, json=payload)
        self.assertEqual(200, accepted.status_code, accepted.text)
        stale = self.client.post(f"/tasks/{task['task_id']}/review", headers=self.reviewer, json=payload)
        self.assertEqual(409, stale.status_code)

    def test_cors_is_restricted(self) -> None:
        response = self.client.options("/runs", headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "POST",
        })
        self.assertNotEqual("*", response.headers.get("access-control-allow-origin"))

    def test_upload_and_review_from_api(self) -> None:
        context = self.client.get("/demo/context", headers=self.analyst).json()
        proposal = (Path(__file__).parents[1] / "data" / "demo" / "new_project_proposal.txt").read_bytes()
        response = self.client.post(
            "/compliance-reviews/upload", headers=self.analyst,
            data={"company_snapshot_id": context["company_snapshot_id"], "document_kind": "project_proposal",
                  "department": "Environmental Engineering", "project_id": "Advanced Manufacturing Expansion",
                  "idempotency_key": "api-core-review-0001"},
            files={"file": ("proposal.txt", proposal, "text/plain")},
        )
        self.assertEqual(201, response.status_code, response.text)
        review = response.json()["review"]
        self.assertEqual("non_compliant", review["findings"][0]["status"])
        self.assertEqual("Recently superseded requirement detected", review["summary"]["warning"])
        graph = self.client.get("/impact-graph", headers=self.analyst)
        self.assertEqual(200, graph.status_code)
        self.assertTrue(graph.json()["edges"])

    def test_demo_project_file_is_available_to_the_ui(self) -> None:
        response = self.client.get("/demo/files/new-project-proposal", headers=self.analyst)
        self.assertEqual(200, response.status_code)
        self.assertIn("Article 5.1", response.text)
        self.assertIn("100 mg/Nm3", response.text)

    def test_enterprise_ui_overview_is_sanitized(self) -> None:
        response = self.client.get("/ui/overview", headers=self.analyst)
        self.assertEqual(200, response.status_code, response.text)
        payload = response.json()
        self.assertEqual(385000.0, payload["summary"]["estimated_financial_exposure"])
        self.assertTrue(payload["changes"])
        self.assertNotIn("run_id", payload["changes"][0])
        self.assertEqual("Requirement — Article 5.1", next(
            node["label"] for node in payload["traceability"]["nodes"]
            if node["type"] == "Obligation"
        ))

    def test_regulatory_registry_manual_export_and_local_grc(self) -> None:
        sources = self.client.get("/regulatory-sources", headers=self.analyst)
        self.assertEqual(200, sources.status_code)
        authorities = {item["authority"] for item in sources.json()["sources"]}
        self.assertTrue({"NCA", "SASO", "Manual Export/Sector Source"}.issubset(authorities))

        payload = {
            "authority": "Demo Export Authority",
            "jurisdiction": "SA",
            "controlled_technology_category": "embedded systems",
            "restriction_type": "export",
            "destination_country": "DEMO",
            "effective_date": "2026-10-01",
            "licensing_requirement": "Manual review required",
            "official_source_url": "https://official.example/regulation",
            "title": "Demo official export rule",
            "content": "Article 1 Export requires a documented license.",
        }
        manual = self.client.post("/export-sector/manual", headers=self.admin, json=payload)
        self.assertEqual(201, manual.status_code, manual.text)
        self.assertIsNotNone(manual.json()["version"])

        grc = self.client.post("/grc/tasks", headers=self.analyst, json={
            "title": "Review export license", "description": "Local demo adapter task",
            "priority": "high", "evidence_refs": [manual.json()["document"]["document_id"]],
        })
        self.assertEqual(201, grc.status_code, grc.text)
        updated = self.client.post(
            f"/grc/tasks/{grc.json()['grc_task_id']}/status?status_value=in_progress",
            headers=self.analyst,
        )
        self.assertEqual("in_progress", updated.json()["status"])


if __name__ == "__main__":
    unittest.main()
