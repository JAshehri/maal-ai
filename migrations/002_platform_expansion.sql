PRAGMA foreign_keys = ON;

ALTER TABLE sources ADD COLUMN regulatory_domain TEXT NOT NULL DEFAULT '';
ALTER TABLE sources ADD COLUMN connector_type TEXT NOT NULL DEFAULT 'manual';
ALTER TABLE sources ADD COLUMN document_types_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE sources ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1;
ALTER TABLE sources ADD COLUMN last_checked_at TEXT;
ALTER TABLE sources ADD COLUMN last_success_at TEXT;
ALTER TABLE sources ADD COLUMN fetch_config_json TEXT NOT NULL DEFAULT '{}';

ALTER TABLE document_versions ADD COLUMN document_id TEXT;
ALTER TABLE document_versions ADD COLUMN storage_uri TEXT;
ALTER TABLE document_versions ADD COLUMN mime_type TEXT;
ALTER TABLE document_versions ADD COLUMN original_filename TEXT;
ALTER TABLE document_versions ADD COLUMN source_last_modified_at TEXT;

CREATE TABLE IF NOT EXISTS regulatory_documents (
  document_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(source_id),
  authority TEXT NOT NULL,
  jurisdiction TEXT NOT NULL,
  regulatory_domain TEXT NOT NULL,
  title TEXT NOT NULL,
  document_type TEXT NOT NULL,
  category TEXT,
  canonical_url TEXT NOT NULL,
  download_url TEXT,
  publication_date TEXT,
  approval_date TEXT,
  mandatory_application_date TEXT,
  last_modified_at TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  discovered_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(source_id, canonical_url)
);

CREATE TABLE IF NOT EXISTS regulatory_scan_runs (
  scan_id TEXT PRIMARY KEY,
  company_snapshot_id TEXT REFERENCES company_snapshots(company_snapshot_id),
  company_id TEXT,
  idempotency_key TEXT NOT NULL UNIQUE,
  request_hash TEXT NOT NULL,
  status TEXT NOT NULL,
  sources_checked INTEGER NOT NULL DEFAULT 0,
  documents_discovered INTEGER NOT NULL DEFAULT 0,
  versions_created INTEGER NOT NULL DEFAULT 0,
  unchanged_documents INTEGER NOT NULL DEFAULT 0,
  changes_created INTEGER NOT NULL DEFAULT 0,
  relevant_documents INTEGER NOT NULL DEFAULT 0,
  filtered_documents INTEGER NOT NULL DEFAULT 0,
  error_count INTEGER NOT NULL DEFAULT 0,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  summary_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS source_fetch_events (
  fetch_event_id TEXT PRIMARY KEY,
  scan_id TEXT NOT NULL REFERENCES regulatory_scan_runs(scan_id),
  source_id TEXT NOT NULL REFERENCES sources(source_id),
  document_id TEXT REFERENCES regulatory_documents(document_id),
  status TEXT NOT NULL,
  http_status INTEGER,
  canonical_url TEXT NOT NULL,
  content_sha256 TEXT,
  error_code TEXT,
  error_message TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS scan_document_results (
  scan_id TEXT NOT NULL REFERENCES regulatory_scan_runs(scan_id),
  document_id TEXT NOT NULL REFERENCES regulatory_documents(document_id),
  version_id TEXT REFERENCES document_versions(version_id),
  previous_version_id TEXT REFERENCES document_versions(version_id),
  outcome TEXT NOT NULL,
  applicability_status TEXT NOT NULL,
  applicability_rationale TEXT NOT NULL,
  change_count INTEGER NOT NULL DEFAULT 0,
  priority TEXT NOT NULL DEFAULT 'pending_review',
  department_ids_json TEXT NOT NULL DEFAULT '[]',
  analysis_run_id TEXT REFERENCES runs(run_id),
  created_at TEXT NOT NULL,
  PRIMARY KEY(scan_id, document_id)
);

CREATE TABLE IF NOT EXISTS export_sector_regulations (
  export_regulation_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(source_id),
  authority TEXT NOT NULL,
  jurisdiction TEXT NOT NULL,
  controlled_technology_category TEXT NOT NULL,
  restriction_type TEXT NOT NULL,
  destination_country TEXT,
  effective_date TEXT,
  licensing_requirement TEXT,
  official_source_url TEXT NOT NULL,
  document_id TEXT REFERENCES regulatory_documents(document_id),
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS grc_tasks (
  grc_task_id TEXT PRIMARY KEY,
  local_task_id TEXT,
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  status TEXT NOT NULL,
  owner TEXT,
  priority TEXT,
  due_date TEXT,
  evidence_refs_json TEXT NOT NULL DEFAULT '[]',
  adapter_name TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sources_registry ON sources(jurisdiction, regulatory_domain, enabled);
CREATE INDEX IF NOT EXISTS idx_reg_docs_source ON regulatory_documents(source_id, category, publication_date);
CREATE INDEX IF NOT EXISTS idx_versions_document ON document_versions(document_id, retrieved_at);
CREATE INDEX IF NOT EXISTS idx_scan_company ON regulatory_scan_runs(company_id, started_at);
CREATE INDEX IF NOT EXISTS idx_fetch_scan ON source_fetch_events(scan_id, source_id, status);
CREATE INDEX IF NOT EXISTS idx_scan_results_status ON scan_document_results(scan_id, applicability_status, priority);
