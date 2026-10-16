PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS requirement_assessments (
  assessment_id TEXT PRIMARY KEY,
  company_snapshot_id TEXT NOT NULL REFERENCES company_snapshots(company_snapshot_id),
  company_document_id TEXT NOT NULL REFERENCES company_documents(company_document_id),
  company_chunk_id TEXT NOT NULL REFERENCES company_document_chunks(chunk_id),
  source_id TEXT NOT NULL REFERENCES sources(source_id),
  regulatory_document_id TEXT REFERENCES regulatory_documents(document_id),
  version_id TEXT NOT NULL REFERENCES document_versions(version_id),
  clause_id TEXT NOT NULL REFERENCES clauses(clause_id),
  article_ref TEXT NOT NULL,
  status TEXT NOT NULL,
  matching_method TEXT NOT NULL,
  match_score REAL NOT NULL,
  regulatory_quote TEXT NOT NULL,
  company_quote TEXT NOT NULL,
  locator_json TEXT NOT NULL,
  comparison_json TEXT NOT NULL DEFAULT '{}',
  rationale TEXT NOT NULL,
  recommended_fix TEXT,
  evidence_fingerprint TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(company_snapshot_id, clause_id, company_chunk_id)
);

CREATE TABLE IF NOT EXISTS analysis_feedback (
  feedback_id TEXT PRIMARY KEY,
  company_id TEXT NOT NULL,
  target_type TEXT NOT NULL,
  target_id TEXT NOT NULL,
  subject_key TEXT NOT NULL,
  evidence_fingerprint TEXT,
  decision TEXT NOT NULL,
  corrected_value TEXT,
  comment TEXT NOT NULL,
  reviewer_id TEXT NOT NULL,
  reviewer_role TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_requirement_assessments_snapshot
  ON requirement_assessments(company_snapshot_id, status, version_id);
CREATE INDEX IF NOT EXISTS idx_requirement_assessments_document
  ON requirement_assessments(company_document_id, article_ref);
CREATE INDEX IF NOT EXISTS idx_analysis_feedback_target
  ON analysis_feedback(target_type, target_id, created_at);
CREATE INDEX IF NOT EXISTS idx_analysis_feedback_subject
  ON analysis_feedback(company_id, subject_key, evidence_fingerprint, created_at);
