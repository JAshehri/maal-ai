PRAGMA foreign_keys = ON;

-- 1. Temporal metadata for regulatory documents
ALTER TABLE regulatory_documents ADD COLUMN publication_date_text TEXT;
ALTER TABLE regulatory_documents ADD COLUMN mandatory_application_date_text TEXT;
ALTER TABLE regulatory_documents ADD COLUMN hijri_date TEXT;
ALTER TABLE regulatory_documents ADD COLUMN calendar_type TEXT DEFAULT 'gregorian';

-- 2. Legal status & temporal lifecycle for document versions
ALTER TABLE document_versions ADD COLUMN legal_status TEXT DEFAULT 'effective';
ALTER TABLE document_versions ADD COLUMN enforcement_date TEXT;
ALTER TABLE document_versions ADD COLUMN repealed_date TEXT;
ALTER TABLE document_versions ADD COLUMN grace_period_days INTEGER DEFAULT 0;

-- 3. Dual raw and normalized text preservation for clauses
ALTER TABLE clauses ADD COLUMN raw_text TEXT;
ALTER TABLE clauses ADD COLUMN normalized_text TEXT;
ALTER TABLE clauses ADD COLUMN language TEXT DEFAULT 'ar';

-- 4. Dual text, language & extraction quality for company chunks
ALTER TABLE company_document_chunks ADD COLUMN raw_text TEXT;
ALTER TABLE company_document_chunks ADD COLUMN normalized_text TEXT;
ALTER TABLE company_document_chunks ADD COLUMN language TEXT DEFAULT 'ar';
ALTER TABLE company_document_chunks ADD COLUMN extraction_quality TEXT DEFAULT 'extraction_success';

-- 5. Temporal support for compliance reviews (Current vs Historical as_of_date)
ALTER TABLE compliance_reviews ADD COLUMN as_of_date TEXT;
ALTER TABLE compliance_reviews ADD COLUMN review_mode TEXT DEFAULT 'current';

-- 6. Finding status extensions
ALTER TABLE compliance_review_findings ADD COLUMN legal_status TEXT DEFAULT 'effective';
ALTER TABLE compliance_review_findings ADD COLUMN transition_status TEXT DEFAULT 'currently_effective';
ALTER TABLE compliance_review_findings ADD COLUMN effective_date TEXT;

-- 7. Explainable edge metadata for document dependencies
ALTER TABLE document_dependencies ADD COLUMN matching_method TEXT DEFAULT 'exact_reference';
ALTER TABLE document_dependencies ADD COLUMN confidence REAL DEFAULT 1.0;
ALTER TABLE document_dependencies ADD COLUMN rationale TEXT DEFAULT '';

-- 8. Indexes for temporal queries and legal status
CREATE INDEX IF NOT EXISTS idx_versions_status ON document_versions(legal_status, effective_at);
CREATE INDEX IF NOT EXISTS idx_reviews_as_of ON compliance_reviews(as_of_date, review_mode);
