PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS company_profiles (
  company_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  current_version_id TEXT,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS company_profile_versions (
  profile_version_id TEXT PRIMARY KEY,
  company_id TEXT NOT NULL REFERENCES company_profiles(company_id),
  version_no INTEGER NOT NULL,
  status TEXT NOT NULL,
  company_snapshot_id TEXT REFERENCES company_snapshots(company_snapshot_id),
  payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  approved_at TEXT,
  UNIQUE(company_id, version_no)
);

CREATE TABLE IF NOT EXISTS onboarding_documents (
  onboarding_document_id TEXT PRIMARY KEY,
  company_id TEXT NOT NULL REFERENCES company_profiles(company_id),
  profile_version_id TEXT NOT NULL REFERENCES company_profile_versions(profile_version_id),
  filename TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  document_kind TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  storage_uri TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(profile_version_id, sha256)
);

CREATE TABLE IF NOT EXISTS onboarding_document_chunks (
  onboarding_chunk_id TEXT PRIMARY KEY,
  onboarding_document_id TEXT NOT NULL REFERENCES onboarding_documents(onboarding_document_id),
  sequence_no INTEGER NOT NULL,
  locator_json TEXT NOT NULL,
  text TEXT NOT NULL,
  text_sha256 TEXT NOT NULL,
  UNIQUE(onboarding_document_id, sequence_no)
);

CREATE TABLE IF NOT EXISTS extracted_company_facts (
  fact_id TEXT PRIMARY KEY,
  profile_version_id TEXT NOT NULL REFERENCES company_profile_versions(profile_version_id),
  fact_type TEXT NOT NULL,
  value_json TEXT NOT NULL,
  source_document_id TEXT NOT NULL REFERENCES onboarding_documents(onboarding_document_id),
  source_chunk_id TEXT NOT NULL REFERENCES onboarding_document_chunks(onboarding_chunk_id),
  locator_json TEXT NOT NULL,
  confidence REAL NOT NULL,
  extraction_method TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(profile_version_id, fact_type, source_chunk_id, value_json)
);

CREATE TABLE IF NOT EXISTS regulatory_domains (
  domain_id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name_ar TEXT NOT NULL,
  name_en TEXT NOT NULL,
  connector_authority TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS company_regulatory_scope (
  scope_id TEXT PRIMARY KEY,
  profile_version_id TEXT NOT NULL REFERENCES company_profile_versions(profile_version_id),
  domain_id TEXT NOT NULL REFERENCES regulatory_domains(domain_id),
  classification TEXT NOT NULL,
  status TEXT NOT NULL,
  admin_override INTEGER NOT NULL DEFAULT 0,
  rationale TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(profile_version_id, domain_id)
);

CREATE TABLE IF NOT EXISTS regulatory_scope_evidence (
  scope_evidence_id TEXT PRIMARY KEY,
  scope_id TEXT NOT NULL REFERENCES company_regulatory_scope(scope_id),
  fact_id TEXT REFERENCES extracted_company_facts(fact_id),
  source_document_id TEXT REFERENCES onboarding_documents(onboarding_document_id),
  source_chunk_id TEXT REFERENCES onboarding_document_chunks(onboarding_chunk_id),
  locator_json TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS onboarding_status (
  company_id TEXT PRIMARY KEY REFERENCES company_profiles(company_id),
  status TEXT NOT NULL,
  current_step TEXT NOT NULL,
  last_error TEXT,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_profile_versions_company ON company_profile_versions(company_id, version_no);
CREATE INDEX IF NOT EXISTS idx_onboarding_docs_version ON onboarding_documents(profile_version_id);
CREATE INDEX IF NOT EXISTS idx_company_facts_version_type ON extracted_company_facts(profile_version_id, fact_type);
CREATE INDEX IF NOT EXISTS idx_company_scope_version ON company_regulatory_scope(profile_version_id, classification, status);
