from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from src import db
from src.onboarding import (
    approve_profile,
    create_profile_from_documents,
    get_onboarding,
    live_ui_overview,
    remove_profile_document,
    seed_regulatory_domains,
)
from src.regulatory.registry import seed_regulatory_sources
from src.settings import settings


COMPANY_OVERVIEW = b"""Business activities: Advanced electronics manufacturing, embedded systems engineering
Products: electronic control systems, embedded controllers
Departments: Engineering, Quality, Human Resources, Procurement, Information Technology
Technologies: embedded systems, operational technology, cloud services
Jurisdiction: Kingdom of Saudi Arabia
We employ 120 employees and use information systems.
We process employee personal data for human resources operations.
We manufacture electronic control systems in a production facility.
"""

SUPPLY_CHAIN = b"""Suppliers: electronic component suppliers, local logistics provider
The company has suppliers and a managed supply chain.
Import and export activity is not confirmed in this document.
"""


@pytest.fixture()
def clean_database(tmp_path):
    path = tmp_path / "real-company.db"
    db.init_db(path)
    seed_regulatory_sources(path)
    seed_regulatory_domains(path)
    return path


def _files():
    return [
        ("company-overview.txt", "text/plain", COMPANY_OVERVIEW),
        ("supply-chain.txt", "text/plain", SUPPLY_CHAIN),
    ]


def test_clean_database_starts_with_real_empty_onboarding(clean_database):
    state = get_onboarding(db_path=clean_database)
    assert state["status"] == "not_started"
    assert state["company"] is None


def test_multiple_documents_create_evidenced_profile_and_mandatory_scope(clean_database):
    state = create_profile_from_documents(company_name="Real Electronics Co", files=_files(), db_path=clean_database)

    assert state["status"] == "in_progress"
    assert len(state["documents"]) == 2
    assert state["fact_summary"]["has_employees"] is True
    assert state["fact_summary"]["uses_information_systems"] is True
    assert state["fact_summary"]["processes_personal_data"] is True
    assert state["fact_summary"]["manufactures_products"] is True
    assert state["fact_summary"]["has_suppliers"] is True
    assert state["fact_summary"]["uses_cloud"] is True
    assert state["fact_summary"]["handles_electronics"] is True
    assert all(fact["source_document"] and fact["locator"] for fact in state["facts"])
    assert all(0 <= fact["confidence"] <= 1 and fact["extraction_method"] for fact in state["facts"])

    scopes = {item["code"]: item for item in state["scope"]}
    for code in ("employment_labor", "data_privacy", "cybersecurity", "product_conformity", "procurement_supply"):
        assert scopes[code]["classification"] == "mandatory"
    # The statement explicitly says the activity is not confirmed, so it is not promoted to a fact.
    assert scopes["export_control"]["classification"] == "needs_confirmation"


def test_analyst_cannot_remove_mandatory_scope_and_approval_has_no_demo_values(clean_database):
    state = create_profile_from_documents(company_name="Real Electronics Co", files=_files(), db_path=clean_database)
    company_id = state["company"]["company_id"]
    with pytest.raises(PermissionError):
        approve_profile(
            company_id,
            expected_version=1,
            profile_edits={},
            scope_updates=[{"code": "employment_labor", "status": "removed"}],
            role="analyst",
            db_path=clean_database,
        )

    approved = approve_profile(
        company_id,
        expected_version=1,
        profile_edits={
            "activities": ["Advanced electronics manufacturing"],
            "products_services": ["Electronic control systems"],
            "departments": ["Engineering", "Quality", "Human Resources"],
            "technologies": ["Embedded systems", "Operational technology"],
            "jurisdictions": ["SA"],
        },
        scope_updates=[{"code": item["code"], "status": "confirmed"} for item in state["scope"]],
        role="analyst",
        db_path=clean_database,
    )
    assert approved["status"] == "completed"

    overview = live_ui_overview(company_id, clean_database)
    assert overview["scan"] is None
    assert overview["regulations"] == []
    assert overview["financial"]["total"] is None
    assert {source["authority"] for source in overview["sources"]} == {"NCA", "SASO"}


def test_later_upload_creates_immutable_version_and_retains_prior_evidence(clean_database):
    first = create_profile_from_documents(company_name="Real Electronics Co", files=_files(), db_path=clean_database)
    second = create_profile_from_documents(
        company_name="Real Electronics Co",
        files=[("quality-policy.txt", "text/plain", b"Departments: Quality\nTechnologies: test automation\n")],
        db_path=clean_database,
    )
    assert first["profile_version"]["version_no"] == 1
    assert second["profile_version"]["version_no"] == 2
    assert len(second["documents"]) == 3
    assert second["fact_summary"]["has_employees"] is True
    with db.connect(clean_database) as connection:
        versions = connection.execute(
            "SELECT version_no, status, payload_json FROM company_profile_versions ORDER BY version_no"
        ).fetchall()
    assert [row["version_no"] for row in versions] == [1, 2]
    assert all(json.loads(row["payload_json"])["document_count"] >= 2 for row in versions)


def test_empty_upload_is_rejected_without_poisoning_profile_and_can_be_retried(clean_database):
    with pytest.raises(ValueError, match="empty company document was removed"):
        create_profile_from_documents(
            company_name="Retry Electronics Co",
            files=[("empty.txt", "text/plain", b"")],
            db_path=clean_database,
        )

    state = get_onboarding(db_path=clean_database)
    assert state["status"] == "not_started"
    assert state["company"] is None

    retried = create_profile_from_documents(
        company_name="Retry Electronics Co",
        files=[("company.txt", "text/plain", COMPANY_OVERVIEW)],
        db_path=clean_database,
    )
    assert retried["status"] == "in_progress"
    assert [item["filename"] for item in retried["documents"]] == ["company.txt"]


def test_removing_document_rebuilds_current_profile_without_stale_facts(clean_database):
    state = create_profile_from_documents(company_name="Real Electronics Co", files=_files(), db_path=clean_database)
    company_id = state["company"]["company_id"]
    supply_document = next(item for item in state["documents"] if item["filename"] == "supply-chain.txt")

    rebuilt = remove_profile_document(company_id, supply_document["onboarding_document_id"], clean_database)
    assert [item["filename"] for item in rebuilt["documents"]] == ["company-overview.txt"]
    assert rebuilt["fact_summary"].get("has_suppliers") is not True
    assert rebuilt["profile_version"]["version_no"] == 2

    reuploaded = create_profile_from_documents(
        company_name="Real Electronics Co",
        files=[("supply-chain.txt", "text/plain", SUPPLY_CHAIN)],
        db_path=clean_database,
    )
    assert {item["filename"] for item in reuploaded["documents"]} == {
        "company-overview.txt",
        "supply-chain.txt",
    }
    assert reuploaded["fact_summary"]["has_suppliers"] is True


def test_removing_last_document_returns_to_upload_and_allows_clean_reupload(clean_database):
    initial = create_profile_from_documents(
        company_name="Single File Co",
        files=[("company.txt", "text/plain", COMPANY_OVERVIEW)],
        db_path=clean_database,
    )
    company_id = initial["company"]["company_id"]
    document_id = initial["documents"][0]["onboarding_document_id"]

    empty = remove_profile_document(company_id, document_id, clean_database)
    assert empty["current_step"] == "upload"
    assert empty["documents"] == []
    assert empty["facts"] == []

    reuploaded = create_profile_from_documents(
        company_name="Single File Co",
        files=[("company.txt", "text/plain", COMPANY_OVERVIEW)],
        db_path=clean_database,
    )
    assert len(reuploaded["documents"]) == 1
    assert reuploaded["profile_version"]["version_no"] == 3


def test_normal_mode_api_uses_onboarding_and_never_exposes_demo(tmp_path):
    from app import app

    original_path, original_demo = settings.database_path, settings.demo_mode
    object.__setattr__(settings, "database_path", tmp_path / "normal-mode.db")
    object.__setattr__(settings, "demo_mode", False)
    headers = {"X-Role": "analyst", "X-User-Id": "analyst-test"}
    try:
        with TestClient(app) as client:
            assert client.get("/demo/context", headers=headers).status_code == 404
            empty = client.get("/onboarding/status", headers=headers)
            assert empty.status_code == 200
            assert empty.json()["status"] == "not_started"

            uploaded = client.post(
                "/onboarding/documents",
                headers=headers,
                data={"company_name": "API Electronics Co"},
                files=[
                    ("files", ("company.txt", COMPANY_OVERVIEW, "text/plain")),
                    ("files", ("suppliers.txt", SUPPLY_CHAIN, "text/plain")),
                ],
            )
            assert uploaded.status_code == 201
            profile = uploaded.json()
            updates = [{"code": item["code"], "status": "confirmed"} for item in profile["scope"]]
            approved = client.post(
                f"/onboarding/{profile['company']['company_id']}/approve",
                headers=headers,
                json={"expected_version": 1, "profile_edits": {}, "scope_updates": updates},
            )
            assert approved.status_code == 200
            overview = client.get(
                "/ui/live-overview",
                headers=headers,
                params={"company_id": profile["company"]["company_id"]},
            )
            assert overview.status_code == 200
            payload = overview.json()
            assert payload["scan"] is None
            assert payload["regulations"] == []
            assert payload["summary"]["estimated_financial_exposure"] is None
    finally:
        object.__setattr__(settings, "database_path", original_path)
        object.__setattr__(settings, "demo_mode", original_demo)


def test_company_document_delete_api_and_reupload(tmp_path):
    from app import app

    original_path, original_demo = settings.database_path, settings.demo_mode
    object.__setattr__(settings, "database_path", tmp_path / "document-delete.db")
    object.__setattr__(settings, "demo_mode", False)
    headers = {"X-Role": "analyst", "X-User-Id": "analyst-test"}
    try:
        with TestClient(app) as client:
            uploaded = client.post(
                "/onboarding/documents",
                headers=headers,
                data={"company_name": "Delete API Co"},
                files=[("files", ("company.txt", COMPANY_OVERVIEW, "text/plain"))],
            )
            assert uploaded.status_code == 201
            state = uploaded.json()
            company_id = state["company"]["company_id"]
            document_id = state["documents"][0]["onboarding_document_id"]

            deleted = client.delete(
                f"/onboarding/{company_id}/documents/{document_id}",
                headers=headers,
            )
            assert deleted.status_code == 200
            assert deleted.json()["documents"] == []
            assert deleted.json()["current_step"] == "upload"

            retried = client.post(
                "/onboarding/documents",
                headers=headers,
                data={"company_name": "Delete API Co"},
                files=[("files", ("company.txt", COMPANY_OVERVIEW, "text/plain"))],
            )
            assert retried.status_code == 201
            assert [item["filename"] for item in retried.json()["documents"]] == ["company.txt"]
    finally:
        object.__setattr__(settings, "database_path", original_path)
        object.__setattr__(settings, "demo_mode", original_demo)
