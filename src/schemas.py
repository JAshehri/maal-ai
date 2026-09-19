from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SourceQuality(str, Enum):
    official_approved = "official_approved"
    approved_copy = "approved_copy"
    unverified = "unverified"


class ChangeType(str, Enum):
    added = "added"
    deleted = "deleted"
    numeric_threshold = "numeric_threshold"
    deadline = "deadline"
    scope = "scope"
    editorial = "editorial"
    modified = "modified"


class ApplicabilityStatus(str, Enum):
    applicable = "applicable"
    potentially_applicable = "potentially_applicable"
    not_applicable = "not_applicable"
    needs_review = "needs_review"
    unknown = "unknown"


class AssessmentStatus(str, Enum):
    supported_compliant = "supported_compliant"
    gap = "gap"
    insufficient_evidence = "insufficient_evidence"
    conflicting_evidence = "conflicting_evidence"
    unknown = "unknown"


class ReviewDecision(str, Enum):
    approve = "approve"
    edit = "edit"
    reject = "reject"


class RunPhase(str, Enum):
    queued = "queued"
    ingesting = "ingesting"
    comparing = "comparing"
    extracting = "extracting"
    assessing = "assessing"
    retrieving = "retrieving"
    verifying = "verifying"
    drafting = "drafting"
    awaiting_review = "awaiting_review"
    no_change = "no_change"
    completed = "completed"
    failed = "failed"


class Provenance(StrictModel):
    run_id: str
    company_id: str
    source_id: str
    version_id: str
    model_id: str
    prompt_version: str
    schema_version: str


class SourceCreate(StrictModel):
    authority: str = Field(min_length=2)
    canonical_url: str = Field(min_length=4)
    jurisdiction: str
    title: str
    approval_status: Literal["approved", "pending", "rejected"] = "approved"
    source_quality: SourceQuality = SourceQuality.official_approved
    regulatory_domain: str = ""
    connector_type: Literal["nca_html", "saso_html", "manual_export_sector", "manual"] = "manual"
    document_types: list[str] = Field(default_factory=list)
    enabled: bool = True
    fetch_config: dict[str, Any] = Field(default_factory=dict)


class Source(SourceCreate):
    source_id: str
    created_at: datetime = Field(default_factory=utc_now)


class DocumentVersionCreate(StrictModel):
    source_id: str
    content: str = Field(min_length=1, max_length=1_000_000)
    published_at: date | None = None
    effective_at: date | None = None
    supersedes_version_id: str | None = None
    is_simulated: bool = False
    simulation_notice: str | None = None

    @model_validator(mode="after")
    def require_simulation_notice(self) -> "DocumentVersionCreate":
        if self.is_simulated and not self.simulation_notice:
            raise ValueError("simulation_notice is required for simulated versions")
        return self


class DocumentVersion(StrictModel):
    version_id: str
    source_id: str
    sha256: str
    text_sha256: str
    content: str
    published_at: date | None = None
    effective_at: date | None = None
    retrieved_at: datetime = Field(default_factory=utc_now)
    supersedes_version_id: str | None = None
    is_simulated: bool = False
    simulation_notice: str | None = None
    document_id: str | None = None
    storage_uri: str | None = None
    mime_type: str | None = None
    original_filename: str | None = None
    source_last_modified_at: datetime | None = None


class Clause(StrictModel):
    clause_id: str
    version_id: str
    article_ref: str
    heading: str | None = None
    text: str
    page_number: int | None = None
    start_offset: int
    end_offset: int
    text_sha256: str


class RegulatoryChange(StrictModel):
    change_id: str
    source_id: str
    old_version_id: str
    new_version_id: str
    before_clause_id: str | None = None
    after_clause_id: str | None = None
    article_ref: str
    change_type: ChangeType
    before_text: str | None = None
    after_text: str | None = None
    summary: str
    substantive: bool
    numeric_before: list[float] = Field(default_factory=list)
    numeric_after: list[float] = Field(default_factory=list)


class Threshold(StrictModel):
    operator: Literal["<", "<=", ">", ">=", "="]
    value: float
    unit: str
    averaging_period: str | None = None
    measurement_basis: str | None = None


class Obligation(StrictModel):
    obligation_id: str
    obligation_key: str
    provenance: Provenance
    clause_id: str
    change_id: str
    article_ref: str
    quote: str
    actor: str | None = None
    action: str
    modality: Literal["must", "prohibited", "required", "permission_option", "unknown"]
    applicability_conditions: list[str] = Field(default_factory=list)
    exceptions: list[str] = Field(default_factory=list)
    related_clause_ids: list[str] = Field(default_factory=list)
    effective_at: date | None = None
    citation_ids: list[str] = Field(default_factory=list)
    threshold: Threshold | None = None


class CompanySnapshot(StrictModel):
    company_snapshot_id: str
    company_id: str
    name: str
    captured_at: datetime = Field(default_factory=utc_now)
    jurisdiction: str
    activities: list[str]
    assets: list[dict[str, Any]]
    policies: list[dict[str, Any]] = Field(default_factory=list)
    permits: list[dict[str, Any]] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)


class Evidence(StrictModel):
    evidence_id: str
    company_snapshot_id: str
    company_id: str
    evidence_type: str
    title: str
    content: str
    asset_id: str | None = None
    observed_at: datetime | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    structured_data: dict[str, Any] = Field(default_factory=dict)
    source_quality: SourceQuality = SourceQuality.approved_copy


class ApplicabilityResult(StrictModel):
    applicability_id: str
    provenance: Provenance
    obligation_id: str
    company_snapshot_id: str
    status: ApplicabilityStatus
    matched_conditions: list[str] = Field(default_factory=list)
    missing_facts: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    rationale_summary: str
    applicability_sufficiency: Literal["sufficient", "insufficient", "conflicting"]


class Finding(StrictModel):
    finding_id: str
    provenance: Provenance
    change_id: str
    obligation_id: str
    affected_asset_ids: list[str] = Field(default_factory=list)
    assessment_status: AssessmentStatus
    evidence_ids: list[str] = Field(default_factory=list)
    comparison_details: dict[str, Any] = Field(default_factory=dict)
    uncertainty_reasons: list[str] = Field(default_factory=list)
    priority: Literal["high", "medium", "low", "pending_review"]
    rationale_summary: str
    source_quality: SourceQuality
    evidence_freshness: Literal["current", "stale", "unknown"]
    citation_validity: Literal["valid", "invalid", "not_applicable"]
    applicability_sufficiency: Literal["sufficient", "insufficient", "conflicting"]


class TaskDraft(StrictModel):
    task_id: str
    provenance: Provenance
    finding_id: str
    action: str
    owner_role: str | None = None
    proposed_due_date: date | None = None
    due_date_basis: str
    acceptance_evidence: list[str]
    review_status: Literal["pending_human_review", "approved", "rejected"] = "pending_human_review"
    revision: int = 1


class ReviewRequest(StrictModel):
    decision: ReviewDecision
    expected_revision: int = Field(ge=1)
    comment: str = Field(min_length=1, max_length=2000)
    edited_fields: dict[str, Any] = Field(default_factory=dict)


class Review(StrictModel):
    review_id: str
    task_id: str
    reviewer_id: str
    decision: ReviewDecision
    comment: str
    reviewed_revision: int
    created_at: datetime = Field(default_factory=utc_now)


class AuditEvent(StrictModel):
    event_id: str
    run_id: str | None = None
    actor_id: str
    actor_role: str
    action: str
    entity_type: str
    entity_id: str
    reason_summary: str
    evidence_ids: list[str] = Field(default_factory=list)
    tool_name: str | None = None
    before_hash: str | None = None
    after_hash: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class RunCreate(StrictModel):
    company_snapshot_id: str
    old_version_id: str
    new_version_id: str
    idempotency_key: str = Field(min_length=8, max_length=120)


class RunState(StrictModel):
    run_id: str
    thread_id: str
    phase: RunPhase
    company_snapshot_id: str
    old_version_id: str
    new_version_id: str
    change_ids: list[str] = Field(default_factory=list)
    obligation_ids: list[str] = Field(default_factory=list)
    finding_ids: list[str] = Field(default_factory=list)
    task_ids: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    attempts: dict[str, int] = Field(default_factory=dict)
    last_tool: str | None = None
    decision_summary: str | None = None
    errors: list[str] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=utc_now)


class RegulatoryDocument(StrictModel):
    document_id: str
    source_id: str
    authority: str
    jurisdiction: str
    regulatory_domain: str
    title: str
    document_type: str
    category: str | None = None
    canonical_url: str
    download_url: str | None = None
    publication_date: date | None = None
    approval_date: date | None = None
    mandatory_application_date: date | None = None
    last_modified_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    discovered_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class FetchedDocument(StrictModel):
    document: RegulatoryDocument
    content: bytes
    content_type: str
    final_url: str
    filename: str
    http_status: int
    etag: str | None = None
    last_modified_header: str | None = None


class RegulatoryScanCreate(StrictModel):
    company_snapshot_id: str
    source_ids: list[str] | None = None
    jurisdictions: list[str] | None = None
    domains: list[str] | None = None
    force_refresh: bool = False
    idempotency_key: str = Field(min_length=8, max_length=120)


class ExportSectorRegulationCreate(StrictModel):
    authority: str
    jurisdiction: str
    controlled_technology_category: str
    restriction_type: Literal["export", "import", "both", "other"]
    destination_country: str | None = None
    effective_date: date | None = None
    licensing_requirement: str
    official_source_url: str
    title: str
    content: str | None = None


class GRCTaskCreate(StrictModel):
    local_task_id: str | None = None
    title: str
    description: str
    owner: str | None = None
    priority: Literal["critical", "high", "medium", "low"] | None = None
    due_date: date | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class DocumentLocator(StrictModel):
    locator_type: Literal["page", "section", "slide", "sheet_cell", "line", "csv_cell"]
    page: int | None = None
    section: str | None = None
    paragraph: int | None = None
    slide: int | None = None
    sheet: str | None = None
    cell: str | None = None
    row: int | None = None
    column: str | None = None
    line_start: int | None = None
    line_end: int | None = None


class CompanyDocumentChunk(StrictModel):
    chunk_id: str
    company_document_id: str
    sequence_no: int
    locator: DocumentLocator
    section_ref: str | None = None
    text: str
    text_sha256: str


class CompanyDocument(StrictModel):
    company_document_id: str
    company_snapshot_id: str
    company_id: str
    title: str
    filename: str
    mime_type: str
    document_kind: Literal["policy", "project_proposal", "contract", "procedure", "evidence", "other"]
    department: str | None = None
    project_id: str | None = None
    sha256: str
    storage_uri: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class ComplianceReviewCreate(StrictModel):
    company_document_id: str
    company_snapshot_id: str
    idempotency_key: str = Field(min_length=8, max_length=120)


class DocumentDependencyCreate(StrictModel):
    company_document_id: str
    chunk_id: str
    source_id: str
    version_id: str
    clause_id: str
    obligation_id: str | None = None
    obligation_key: str
    article_ref: str
    department: str
    project_id: str | None = None
    relationship_type: Literal["implements", "references", "depends_on", "superseded_reference"] = "depends_on"


class FinancialInput(StrictModel):
    company_snapshot_id: str
    currency: str = "SAR"
    remediation_cost: float | None = Field(default=None, ge=0)
    project_delay_daily_cost: float | None = Field(default=None, ge=0)
    expected_delay_days: float | None = Field(default=None, ge=0)
    downtime_hourly_cost: float | None = Field(default=None, ge=0)
    expected_downtime_hours: float | None = Field(default=None, ge=0)
    contract_exposure: float | None = Field(default=None, ge=0)
    is_synthetic: bool = True
    label: str
