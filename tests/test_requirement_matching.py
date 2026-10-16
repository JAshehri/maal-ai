from src import db
from src.company_documents import ingest_company_document
from src.ingestion import register_document_version
from src.requirement_matching import assess_version_against_company, compare_requirement
from src.schemas import CompanySnapshot, DocumentVersionCreate, Source


def test_ratio_in_company_policy_is_compared_deterministically():
    result = compare_requirement(
        "يجب توفير متدرب واحد لكل 50 موظف.",
        "تنص سياسة التدريب على توفير متدرب واحد لكل 100 موظف.",
        "المادة 8",
    )

    assert result is not None
    assert result["status"] == "non_compliant"
    assert result["matching_method"] == "deterministic_ratio_comparison"
    assert result["comparison"]["required_ratio"]["employees"] == 50
    assert result["comparison"]["documented_ratio"]["employees"] == 100
    assert "50" in result["recommended_fix"]


def test_employee_and_trainee_counts_prove_non_compliance():
    result = compare_requirement(
        "يلزم وجود متدرب واحد لكل 50 موظف.",
        "عدد الموظفين 50 ولا يوجد ولا متدرب حاليًا.",
        "المادة 8",
    )

    assert result is not None
    assert result["status"] == "non_compliant"
    assert result["matching_method"] == "deterministic_headcount_comparison"
    assert result["comparison"]["minimum_required_trainees"] == 1
    assert result["comparison"]["trainee_count"] == 0


def test_arabic_indic_numbers_and_sufficient_counts_are_supported():
    result = compare_requirement(
        "يجب توفير متدرب واحد لكل ٥٠ موظف.",
        "عدد الموظفين: ١٠٠، وعدد المتدربين: ٢.",
        "المادة 8",
    )

    assert result is not None
    assert result["status"] == "compliant"
    assert result["comparison"]["minimum_required_trainees"] == 2


def test_generic_compliance_words_do_not_create_a_false_file_match():
    result = compare_requirement(
        "يجب على المنشأة تطبيق نظام إدارة البيانات وتوثيق متطلبات التحكم التشغيلي.",
        "هذه سياسة الشركة لإدارة المعلومات والبيانات والأنظمة والوثائق.",
        "المادة 12",
    )

    assert result is None


def test_exact_file_locator_is_persisted_and_same_evidence_feedback_is_reused(tmp_path):
    database = tmp_path / "requirement-evidence.db"
    db.init_db(database)
    source = Source(
        source_id="source-training", authority="Official Training Authority",
        canonical_url="https://regulator.example/official-training-rule", jurisdiction="SA",
        title="Official training requirements", regulatory_domain="Employment / Labor",
    )
    db.insert_source(source, database)
    version, clauses, _ = register_document_version(
        DocumentVersionCreate(
            source_id=source.source_id,
            content="المادة 8: يجب توفير متدرب واحد لكل 50 موظف.",
        ),
        db_path=database,
    )
    snapshot = CompanySnapshot(
        company_snapshot_id="snapshot-training", company_id="company-training",
        name="Evidence Company", jurisdiction="SA", activities=["manufacturing"], assets=[],
    )
    db.insert_company_snapshot(snapshot, database)
    document = ingest_company_document(
        raw="تنص سياسة التدريب على توفير متدرب واحد لكل 100 موظف.".encode(),
        filename="training-policy.txt", mime_type="text/plain",
        company_snapshot_id=snapshot.company_snapshot_id, document_kind="policy",
        title="Training Policy", department="Human Resources", db_path=database,
    )

    first = assess_version_against_company(
        company_snapshot_id=snapshot.company_snapshot_id, version_id=version.version_id,
        source_id=source.source_id, db_path=database,
    )
    assert first[0]["status"] == "non_compliant"
    assert first[0]["document"]["filename"] == "training-policy.txt"
    assert first[0]["chunk"]["locator"]["line_start"] == 1

    db.add_analysis_feedback({
        "company_id": snapshot.company_id,
        "target_type": "requirement_assessment",
        "target_id": first[0]["assessment_id"],
        "subject_key": f"requirement:{clauses[0].clause_id}",
        "evidence_fingerprint": first[0]["evidence_fingerprint"],
        "decision": "reject", "corrected_value": "needs_review",
        "comment": "This policy is a draft and has not been approved.",
        "reviewer_id": "employee-1", "reviewer_role": "analyst",
    }, database)
    second = assess_version_against_company(
        company_snapshot_id=snapshot.company_snapshot_id, version_id=version.version_id,
        source_id=source.source_id,
        company_document_id=document["document"]["company_document_id"], db_path=database,
    )
    assert second[0]["status"] == "needs_review"
    assert second[0]["matching_method"] == "reviewer_corrected_evidence_match"
