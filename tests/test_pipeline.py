from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src import db
from src.demo import seed_demo
from src.pipeline import create_run, execute_run
from src.schemas import RunCreate, RunPhase


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "test.db"
        self.seeded = seed_demo(self.db_path)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def request(self, key: str) -> RunCreate:
        return RunCreate(
            company_snapshot_id=self.seeded["company_snapshot_id"],
            old_version_id=self.seeded["old_version_id"],
            new_version_id=self.seeded["new_version_id"],
            idempotency_key=key,
        )

    def test_complete_demo_journey(self) -> None:
        run, created = create_run(self.request("journey-0001"), self.db_path)
        self.assertTrue(created)
        state = execute_run(run["run_id"], db_path=self.db_path)
        self.assertEqual(RunPhase.awaiting_review, state.phase)
        findings = db.list_findings(run["run_id"], self.db_path)
        statuses = {item.assessment_status.value for item in findings}
        self.assertTrue({"gap", "supported_compliant", "insufficient_evidence", "conflicting_evidence"}.issubset(statuses))
        tasks = db.list_tasks(run["run_id"], self.db_path)
        self.assertEqual(1, len(tasks))

    def test_interruption_resume_and_task_deduplication(self) -> None:
        run, _ = create_run(self.request("resume-0001"), self.db_path)
        interrupted = execute_run(run["run_id"], db_path=self.db_path, stop_after=RunPhase.extracting)
        self.assertEqual(RunPhase.extracting, interrupted.phase)
        resumed = execute_run(run["run_id"], db_path=self.db_path)
        self.assertEqual(RunPhase.awaiting_review, resumed.phase)
        execute_run(run["run_id"], db_path=self.db_path)
        self.assertEqual(1, len(db.list_tasks(run["run_id"], self.db_path)))

    def test_idempotency_key_returns_same_run(self) -> None:
        first, created_first = create_run(self.request("idempotent-0001"), self.db_path)
        second, created_second = create_run(self.request("idempotent-0001"), self.db_path)
        self.assertTrue(created_first)
        self.assertFalse(created_second)
        self.assertEqual(first["run_id"], second["run_id"])


if __name__ == "__main__":
    unittest.main()

