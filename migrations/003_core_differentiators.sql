PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS company_documents (
  company_document_id TEXT PRIMARY KEY,
  company_snapshot_id TEXT NOT NULL REFERENCES company_snapshots(company_snapshot_id),
  company_id TEXT NOT NULL,
  title TEXT NOT NULL,
  filename TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  document_kind TEXT NOT NULL,
  department TEXT,
  project_id TEXT,
  sha256 TEXT NOT NULL,
  storage_uri TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  UNIQUE(company_snapshot_id, sha256, document_kind)
);

CREATE TABLE IF NOT EXISTS company_document_chunks (
  chunk_id TEXT PRIMARY KEY,
  company_document_id TEXT NOT NULL REFERENCES company_documents(company_document_id),
  sequence_no INTEGER NOT NULL,
  locator_type TEXT NOT NULL,
  locator_json TEXT NOT NULL,
  section_ref TEXT,
  text TEXT NOT NULL,
  text_sha256 TEXT NOT NULL,
  UNIQUE(company_document_id, sequence_no)
);

CREATE TABLE IF NOT EXISTS document_dependencies (
  dependency_id TEXT PRIMARY KEY,
  company_id TEXT NOT NULL,
  company_document_id TEXT NOT NULL REFERENCES company_documents(company_document_id),
  chunk_id TEXT NOT NULL REFERENCES company_document_chunks(chunk_id),
  source_id TEXT NOT NULL REFERENCES sources(source_id),
  version_id TEXT NOT NULL REFERENCES document_versions(version_id),
  clause_id TEXT NOT NULL REFERENCES clauses(clause_id),
  obligation_id TEXT,
  obligation_key TEXT NOT NULL,
  article_ref TEXT NOT NULL,
  department TEXT NOT NULL,
  project_id TEXT,
  relationship_type TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  established_at TEXT NOT NULL,
  UNIQUE(company_document_id, chunk_id, version_id, clause_id, obligation_key)
);

CREATE TABLE IF NOT EXISTS regulation_watch_windows (
  watch_id TEXT PRIMARY KEY,
  change_id TEXT NOT NULL UNIQUE REFERENCES regulatory_changes(change_id),
  source_id TEXT NOT NULL REFERENCES sources(source_id),
  old_version_id TEXT NOT NULL REFERENCES document_versions(version_id),
  new_version_id TEXT NOT NULL REFERENCES document_versions(version_id),
  article_ref TEXT NOT NULL,
  old_requirement_text TEXT,
  new_requirement_text TEXT,
  starts_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS compliance_reviews (
  compliance_review_id TEXT PRIMARY KEY,
  company_document_id TEXT NOT NULL REFERENCES company_documents(company_document_id),
  company_snapshot_id TEXT NOT NULL REFERENCES company_snapshots(company_snapshot_id),
  company_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  request_hash TEXT NOT NULL,
  status TEXT NOT NULL,
  weighted_score REAL,
  assessed_weight REAL NOT NULL DEFAULT 0,
  summary_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  completed_at TEXT
);

CREATE TABLE IF NOT EXISTS compliance_review_findings (
  review_finding_id TEXT PRIMARY KEY,
  compliance_review_id TEXT NOT NULL REFERENCES compliance_reviews(compliance_review_id),
  requirement_id TEXT NOT NULL,
  source_id TEXT NOT NULL REFERENCES sources(source_id),
  version_id TEXT NOT NULL REFERENCES document_versions(version_id),
  clause_id TEXT REFERENCES clauses(clause_id),
  change_id TEXT REFERENCES regulatory_changes(change_id),
  article_ref TEXT NOT NULL,
  status TEXT NOT NULL,
  severity TEXT NOT NULL,
  weight REAL NOT NULL,
  score_factor REAL,
  company_chunk_id TEXT REFERENCES company_document_chunks(chunk_id),
  locator_json TEXT,
  document_quote TEXT,
  regulatory_quote TEXT NOT NULL,
  rationale TEXT NOT NULL,
  recommended_fix TEXT,
  warning_code TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(compliance_review_id, requirement_id)
);

CREATE TABLE IF NOT EXISTS company_financial_inputs (
  financial_input_id TEXT PRIMARY KEY,
  company_snapshot_id TEXT NOT NULL UNIQUE REFERENCES company_snapshots(company_snapshot_id),
  currency TEXT NOT NULL,
  remediation_cost REAL,
  project_delay_daily_cost REAL,
  expected_delay_days REAL,
  downtime_hourly_cost REAL,
  expected_downtime_hours REAL,
  contract_exposure REAL,
  is_synthetic INTEGER NOT NULL DEFAULT 1,
  label TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS financial_exposures (
  exposure_id TEXT PRIMARY KEY,
  compliance_review_id TEXT REFERENCES compliance_reviews(compliance_review_id),
  change_id TEXT REFERENCES regulatory_changes(change_id),
  status TEXT NOT NULL,
  currency TEXT,
  total REAL,
  breakdown_json TEXT NOT NULL,
  formula_json TEXT NOT NULL,
  is_synthetic INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_company_chunks_document ON company_document_chunks(company_document_id, sequence_no);
CREATE INDEX IF NOT EXISTS idx_dependencies_requirement ON document_dependencies(source_id, version_id, article_ref, active);
CREATE INDEX IF NOT EXISTS idx_dependencies_document ON document_dependencies(company_document_id, chunk_id);
CREATE INDEX IF NOT EXISTS idx_watch_active ON regulation_watch_windows(status, expires_at);
CREATE INDEX IF NOT EXISTS idx_review_document ON compliance_reviews(company_document_id, created_at);
CREATE INDEX IF NOT EXISTS idx_review_findings_review ON compliance_review_findings(compliance_review_id, severity);
