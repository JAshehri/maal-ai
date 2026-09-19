PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sources (
  source_id TEXT PRIMARY KEY,
  authority TEXT NOT NULL,
  canonical_url TEXT NOT NULL UNIQUE,
  jurisdiction TEXT NOT NULL,
  title TEXT NOT NULL,
  approval_status TEXT NOT NULL,
  source_quality TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS document_versions (
  version_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(source_id),
  sha256 TEXT NOT NULL,
  text_sha256 TEXT NOT NULL,
  content TEXT NOT NULL,
  published_at TEXT,
  effective_at TEXT,
  retrieved_at TEXT NOT NULL,
  supersedes_version_id TEXT REFERENCES document_versions(version_id),
  is_simulated INTEGER NOT NULL DEFAULT 0,
  simulation_notice TEXT,
  UNIQUE(source_id, sha256)
);

CREATE TABLE IF NOT EXISTS clauses (
  clause_id TEXT PRIMARY KEY,
  version_id TEXT NOT NULL REFERENCES document_versions(version_id),
  article_ref TEXT NOT NULL,
  heading TEXT,
  text TEXT NOT NULL,
  page_number INTEGER,
  start_offset INTEGER NOT NULL,
  end_offset INTEGER NOT NULL,
  text_sha256 TEXT NOT NULL,
  UNIQUE(version_id, article_ref, text_sha256)
);

CREATE TABLE IF NOT EXISTS regulatory_changes (
  change_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(source_id),
  old_version_id TEXT NOT NULL REFERENCES document_versions(version_id),
  new_version_id TEXT NOT NULL REFERENCES document_versions(version_id),
  before_clause_id TEXT REFERENCES clauses(clause_id),
  after_clause_id TEXT REFERENCES clauses(clause_id),
  article_ref TEXT NOT NULL,
  change_type TEXT NOT NULL,
  before_text TEXT,
  after_text TEXT,
  summary TEXT NOT NULL,
  substantive INTEGER NOT NULL,
  numeric_before_json TEXT NOT NULL,
  numeric_after_json TEXT NOT NULL,
  UNIQUE(old_version_id, new_version_id, article_ref)
);

CREATE TABLE IF NOT EXISTS company_snapshots (
  company_snapshot_id TEXT PRIMARY KEY,
  company_id TEXT NOT NULL,
  name TEXT NOT NULL,
  captured_at TEXT NOT NULL,
  jurisdiction TEXT NOT NULL,
  payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence (
  evidence_id TEXT PRIMARY KEY,
  company_snapshot_id TEXT NOT NULL REFERENCES company_snapshots(company_snapshot_id),
  company_id TEXT NOT NULL,
  evidence_type TEXT NOT NULL,
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  asset_id TEXT,
  observed_at TEXT,
  valid_from TEXT,
  valid_to TEXT,
  structured_data_json TEXT NOT NULL,
  source_quality TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  thread_id TEXT NOT NULL UNIQUE,
  company_snapshot_id TEXT NOT NULL REFERENCES company_snapshots(company_snapshot_id),
  company_id TEXT NOT NULL,
  source_id TEXT NOT NULL REFERENCES sources(source_id),
  old_version_id TEXT NOT NULL REFERENCES document_versions(version_id),
  new_version_id TEXT NOT NULL REFERENCES document_versions(version_id),
  idempotency_key TEXT NOT NULL UNIQUE,
  request_hash TEXT NOT NULL,
  phase TEXT NOT NULL,
  pipeline_version TEXT NOT NULL,
  model_id TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  error_code TEXT,
  error_message TEXT
);

CREATE TABLE IF NOT EXISTS run_states (
  run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
  state_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS obligations (
  obligation_id TEXT PRIMARY KEY,
  obligation_key TEXT NOT NULL,
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  company_id TEXT NOT NULL,
  source_id TEXT NOT NULL,
  version_id TEXT NOT NULL,
  model_id TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  clause_id TEXT NOT NULL REFERENCES clauses(clause_id),
  change_id TEXT NOT NULL REFERENCES regulatory_changes(change_id),
  article_ref TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  UNIQUE(run_id, change_id, obligation_key)
);

CREATE TABLE IF NOT EXISTS applicability_results (
  applicability_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  obligation_id TEXT NOT NULL REFERENCES obligations(obligation_id),
  company_snapshot_id TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  UNIQUE(run_id, obligation_id)
);

CREATE TABLE IF NOT EXISTS findings (
  finding_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  company_id TEXT NOT NULL,
  source_id TEXT NOT NULL,
  version_id TEXT NOT NULL,
  model_id TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  change_id TEXT NOT NULL REFERENCES regulatory_changes(change_id),
  obligation_id TEXT NOT NULL REFERENCES obligations(obligation_id),
  assessment_status TEXT NOT NULL,
  priority TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  UNIQUE(run_id, change_id, obligation_id)
);

CREATE TABLE IF NOT EXISTS task_drafts (
  task_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  company_id TEXT NOT NULL,
  source_id TEXT NOT NULL,
  version_id TEXT NOT NULL,
  model_id TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  finding_id TEXT NOT NULL UNIQUE REFERENCES findings(finding_id),
  review_status TEXT NOT NULL,
  revision INTEGER NOT NULL,
  payload_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reviews (
  review_id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES task_drafts(task_id),
  reviewer_id TEXT NOT NULL,
  decision TEXT NOT NULL,
  comment TEXT NOT NULL,
  reviewed_revision INTEGER NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
  event_id TEXT PRIMARY KEY,
  run_id TEXT REFERENCES runs(run_id),
  actor_id TEXT NOT NULL,
  actor_role TEXT NOT NULL,
  action TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  reason_summary TEXT NOT NULL,
  evidence_ids_json TEXT NOT NULL,
  tool_name TEXT,
  before_hash TEXT,
  after_hash TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_findings_run ON findings(run_id);
CREATE INDEX IF NOT EXISTS idx_audit_run ON audit_events(run_id, created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_run ON task_drafts(run_id);

