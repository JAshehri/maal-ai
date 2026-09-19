from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src import db
from src.demo import seed_demo
from src.pipeline import create_run, execute_run
from src.review_service import ReviewForbidden, RevisionConflict, review_task
from src.schemas import ReviewDecision, ReviewRequest, RunCreate


class ReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "test.db"
        seeded = seed_demo(self.db_path)
        run, _ = create_run(RunCreate(
            company_snapshot_id=seeded["company_snapshot_id"],
            old_version_id=seeded["old_version_id"],
            new_version_id=seeded["new_version_id"],
            idempotency_key="review-0001",
        ), self.db_path)
        execute_run(run["run_id"], db_path=self.db_path)
        self.run_id = run["run_id"]
        self.task = db.list_tasks(self.run_id, self.db_path)[0]

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_unauthorized_role_is_rejected(self) -> None:
        request = ReviewRequest(decision=ReviewDecision.approve, expected_revision=1, comment="Attempt")
        with self.assertRaises(ReviewForbidden):
            review_task(self.task.task_id, request, reviewer_id="analyst-1", role="analyst", db_path=self.db_path)

    def test_stale_revision_is_rejected(self) -> None:
        approve = ReviewRequest(decision=ReviewDecision.approve, expected_revision=1, comment="Evidence reviewed")
        updated = review_task(self.task.task_id, approve, reviewer_id="reviewer-1", role="reviewer", db_path=self.db_path)
        self.assertEqual(2, updated.revision)
        with self.assertRaises(RevisionConflict):
            review_task(self.task.task_id, approve, reviewer_id="reviewer-2", role="reviewer", db_path=self.db_path)

    def test_edit_creates_new_pending_revision(self) -> None:
        request = ReviewRequest(
            decision=ReviewDecision.edit,
            expected_revision=1,
            comment="Clarify the action",
            edited_fields={"action": "تحقق من قياس S-2 وارفق تقريرًا معتمدًا قبل اعتماد المهمة."},
        )
        updated = review_task(self.task.task_id, request, reviewer_id="reviewer-1", role="reviewer", db_path=self.db_path)
        self.assertEqual("pending_human_review", updated.review_status)
        self.assertEqual(2, updated.revision)
        self.assertEqual(1, len(db.list_reviews(self.task.task_id, self.db_path)))


if __name__ == "__main__":
    unittest.main()

