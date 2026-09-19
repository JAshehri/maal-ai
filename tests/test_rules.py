from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src import db
from src.demo import seed_demo
from src.pipeline import create_run, execute_run
from src.risk_rules import compare_measurements
from src.schemas import (
    AssessmentStatus, Evidence, Obligation, Provenance, RunCreate, SourceQuality, Threshold,
)


class RuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "test.db"
        self.seeded = seed_demo(self.db_path)
        request = RunCreate(
            company_snapshot_id=self.seeded["company_snapshot_id"],
            old_version_id=self.seeded["old_version_id"],
            new_version_id=self.seeded["new_version_id"],
            idempotency_key="rules-0001",
        )
        self.run, _ = create_run(request, self.db_path)
        execute_run(self.run["run_id"], db_path=self.db_path)
        obligations = db.list_obligations(self.run["run_id"], self.db_path)
        self.by_article = {item.article_ref: item for item in obligations}
        by_id = {item.obligation_id: item for item in obligations}
        findings = db.list_findings(self.run["run_id"], self.db_path)
        self.finding_by_article = {by_id[item.obligation_id].article_ref: item for item in findings}

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_not_applicable_has_no_task(self) -> None:
        self.assertEqual(AssessmentStatus.supported_compliant, self.finding_by_article["Article 7"].assessment_status)
        task_findings = {task.finding_id for task in db.list_tasks(self.run["run_id"], self.db_path)}
        self.assertNotIn(self.finding_by_article["Article 7"].finding_id, task_findings)

    def test_missing_permission_is_insufficient_not_gap(self) -> None:
        self.assertEqual(AssessmentStatus.insufficient_evidence, self.finding_by_article["Article 5.10"].assessment_status)

    def test_conflicting_measurements_stop_decision(self) -> None:
        self.assertEqual(AssessmentStatus.conflicting_evidence, self.finding_by_article["Article 5.2"].assessment_status)

    def test_comparable_measurement_can_support_compliance(self) -> None:
        self.assertEqual(AssessmentStatus.supported_compliant, self.finding_by_article["Article 5.3"].assessment_status)

    def test_unit_mismatch_is_insufficient_evidence(self) -> None:
        obligation = self.by_article["Article 5.1"]
        mismatched = Evidence(
            evidence_id="unit-mismatch",
            company_snapshot_id=self.seeded["company_snapshot_id"],
            company_id="company_demo_gci",
            evidence_type="measurement",
            title="Different unit",
            content="Synthetic unit mismatch.",
            asset_id="S-2",
            structured_data={"pollutant": "NOx", "value": 0.09, "unit": "g/Nm3", "measurement_basis": "dry gas at reference conditions"},
            source_quality=SourceQuality.approved_copy,
        )
        status, _, reasons = compare_measurements(obligation, [mismatched])
        self.assertEqual(AssessmentStatus.insufficient_evidence, status)
        self.assertIn("measurement unit or basis is not comparable", reasons)

    def test_negation_and_exception_are_preserved(self) -> None:
        from src.change_detection import compare_clause_sets
        from src.extract_obligations import extract_obligation_from_change
        from src.ingestion import extract_clauses
        old = extract_clauses(self.seeded["old_version_id"], "Article 20 Safety: A facility must store records.")
        new = extract_clauses(self.seeded["new_version_id"], "Article 20 Safety: A facility must not disclose records except to an authorized reviewer.")
        # Persist the clauses because extraction resolves the source span from the database.
        for clause in old + new:
            db.insert_clause(clause, self.db_path)
        changes = compare_clause_sets(source_id=self.seeded["source_id"], old_version_id=self.seeded["old_version_id"],
                                      new_version_id=self.seeded["new_version_id"], old_clauses=old, new_clauses=new,
                                      db_path=self.db_path)
        change = changes[0]
        obligation = extract_obligation_from_change(change, run_id=self.run["run_id"], company_id="company_demo_gci",
                                                    model_id="deterministic-rules-1.0", db_path=self.db_path)
        self.assertEqual("prohibited", obligation.modality)
        self.assertTrue(obligation.exceptions)


if __name__ == "__main__":
    unittest.main()
