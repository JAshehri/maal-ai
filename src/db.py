from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .schemas import (
    ApplicabilityResult, AuditEvent, Clause, CompanySnapshot, DocumentVersion,
    Evidence, Finding, Obligation, RegulatoryChange, RegulatoryDocument,
    GRCTaskCreate, RunPhase, RunState, Source, TaskDraft,
    CompanyDocument, CompanyDocumentChunk, FinancialInput,
)
from .settings import settings


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


@contextmanager
def connect(db_path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    path = Path(db_path or settings.database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=20)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=5000")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def _prepare_legacy_tables(connection: sqlite3.Connection) -> None:
    required = {"obligations": "run_id", "applicability": "run_id", "gaps": "run_id", "tasks": "run_id"}
    suffix = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    for table, required_column in required.items():
        cols = _columns(connection, table)
        if cols and required_column not in cols:
            connection.execute(f'ALTER TABLE "{table}" RENAME TO "legacy_{table}_{suffix}"')


def init_db(db_path: Path | str | None = None) -> None:
    migration_dir = settings.root_dir / "migrations"
    with connect(db_path) as connection:
        _prepare_legacy_tables(connection)
        connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        applied = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
        for migration in sorted(migration_dir.glob("*.sql")):
            if migration.name not in applied:
                connection.executescript(migration.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (migration.name, _now()),
                )


def insert_source(source: Source, db_path: Path | str | None = None) -> Source:
    with connect(db_path) as connection:
        existing = connection.execute("SELECT * FROM sources WHERE canonical_url=?", (source.canonical_url,)).fetchone()
        if existing:
            data = dict(existing)
            return Source(
                source_id=data["source_id"], authority=data["authority"], canonical_url=data["canonical_url"],
                jurisdiction=data["jurisdiction"], title=data["title"], approval_status=data["approval_status"],
                source_quality=data["source_quality"], regulatory_domain=data.get("regulatory_domain") or "",
                connector_type=data.get("connector_type") or "manual",
                document_types=json.loads(data.get("document_types_json") or "[]"),
                enabled=bool(data.get("enabled", 1)), fetch_config=json.loads(data.get("fetch_config_json") or "{}"),
                created_at=data["created_at"],
            )
        connection.execute(
            """INSERT INTO sources
               (source_id, authority, canonical_url, jurisdiction, title, approval_status, source_quality,
                created_at, regulatory_domain, connector_type, document_types_json, enabled, fetch_config_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (source.source_id, source.authority, source.canonical_url, source.jurisdiction,
             source.title, source.approval_status, source.source_quality.value, source.created_at.isoformat(),
             source.regulatory_domain, source.connector_type, _json(source.document_types), int(source.enabled),
             _json(source.fetch_config)),
        )
    return source


def get_source(source_id: str, db_path: Path | str | None = None) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        row = connection.execute("SELECT * FROM sources WHERE source_id=?", (source_id,)).fetchone()
    return dict(row) if row else None


def list_sources(db_path: Path | str | None = None) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        rows = connection.execute("SELECT * FROM sources ORDER BY created_at DESC").fetchall()
    result = []
    for row in rows:
        data = dict(row)
        data["document_types"] = json.loads(data.pop("document_types_json", "[]"))
        data["fetch_config"] = json.loads(data.pop("fetch_config_json", "{}"))
        data["enabled"] = bool(data.get("enabled", 1))
        result.append(data)
    return result


def insert_document_version(version: DocumentVersion, db_path: Path | str | None = None) -> DocumentVersion:
    with connect(db_path) as connection:
        existing = connection.execute(
            "SELECT * FROM document_versions WHERE source_id=? AND sha256=?", (version.source_id, version.sha256)
        ).fetchone()
        if existing:
            data = dict(existing)
            data["is_simulated"] = bool(data["is_simulated"])
            return DocumentVersion(**data)
        connection.execute(
            """INSERT INTO document_versions
               (version_id, source_id, sha256, text_sha256, content, published_at, effective_at,
                retrieved_at, supersedes_version_id, is_simulated, simulation_notice, document_id,
                storage_uri, mime_type, original_filename, source_last_modified_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (version.version_id, version.source_id, version.sha256, version.text_sha256, version.content,
             version.published_at.isoformat() if version.published_at else None,
             version.effective_at.isoformat() if version.effective_at else None,
             version.retrieved_at.isoformat(), version.supersedes_version_id, int(version.is_simulated),
             version.simulation_notice, version.document_id, version.storage_uri, version.mime_type,
             version.original_filename,
             version.source_last_modified_at.isoformat() if version.source_last_modified_at else None),
        )
    return version


def get_document_version(version_id: str, db_path: Path | str | None = None) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        row = connection.execute("SELECT * FROM document_versions WHERE version_id=?", (version_id,)).fetchone()
    return dict(row) if row else None


def list_document_versions(source_id: str | None = None, db_path: Path | str | None = None) -> list[dict[str, Any]]:
    sql, params = "SELECT * FROM document_versions", ()
    if source_id:
        sql, params = sql + " WHERE source_id=?", (source_id,)
    with connect(db_path) as connection:
        rows = connection.execute(sql + " ORDER BY retrieved_at DESC", params).fetchall()
    return [dict(row) for row in rows]


def latest_document_version(document_id: str, db_path: Path | str | None = None) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM document_versions WHERE document_id=? ORDER BY retrieved_at DESC LIMIT 1",
            (document_id,),
        ).fetchone()
    return dict(row) if row else None


def update_source_scan_time(
    source_id: str,
    *,
    checked_at: str,
    successful: bool,
    db_path: Path | str | None = None,
) -> None:
    with connect(db_path) as connection:
        connection.execute(
            """UPDATE sources SET last_checked_at=?,
               last_success_at=CASE WHEN ? THEN ? ELSE last_success_at END WHERE source_id=?""",
            (checked_at, int(successful), checked_at, source_id),
        )


def upsert_regulatory_document(
    item: RegulatoryDocument, db_path: Path | str | None = None
) -> RegulatoryDocument:
    with connect(db_path) as connection:
        connection.execute(
            """INSERT INTO regulatory_documents
               (document_id, source_id, authority, jurisdiction, regulatory_domain, title,
                document_type, category, canonical_url, download_url, publication_date,
                approval_date, mandatory_application_date, last_modified_at, metadata_json,
                discovered_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(source_id, canonical_url) DO UPDATE SET
                 title=excluded.title, document_type=excluded.document_type,
                 category=excluded.category, download_url=excluded.download_url,
                 publication_date=COALESCE(excluded.publication_date, regulatory_documents.publication_date),
                 approval_date=COALESCE(excluded.approval_date, regulatory_documents.approval_date),
                 mandatory_application_date=COALESCE(excluded.mandatory_application_date, regulatory_documents.mandatory_application_date),
                 last_modified_at=COALESCE(excluded.last_modified_at, regulatory_documents.last_modified_at),
                 metadata_json=excluded.metadata_json, updated_at=excluded.updated_at""",
            (item.document_id, item.source_id, item.authority, item.jurisdiction,
             item.regulatory_domain, item.title, item.document_type, item.category,
             item.canonical_url, item.download_url,
             item.publication_date.isoformat() if item.publication_date else None,
             item.approval_date.isoformat() if item.approval_date else None,
             item.mandatory_application_date.isoformat() if item.mandatory_application_date else None,
             item.last_modified_at.isoformat() if item.last_modified_at else None,
             _json(item.metadata), item.discovered_at.isoformat(), item.updated_at.isoformat()),
        )
        row = connection.execute(
            "SELECT * FROM regulatory_documents WHERE source_id=? AND canonical_url=?",
            (item.source_id, item.canonical_url),
        ).fetchone()
    data = dict(row)
    data["metadata"] = json.loads(data.pop("metadata_json"))
    return RegulatoryDocument(**data)


def get_regulatory_document(document_id: str, db_path: Path | str | None = None) -> RegulatoryDocument | None:
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM regulatory_documents WHERE document_id=?", (document_id,)
        ).fetchone()
    if not row:
        return None
    data = dict(row)
    data["metadata"] = json.loads(data.pop("metadata_json"))
    return RegulatoryDocument(**data)


def list_regulatory_documents(
    source_id: str | None = None, db_path: Path | str | None = None
) -> list[dict[str, Any]]:
    sql, params = "SELECT * FROM regulatory_documents", ()
    if source_id:
        sql, params = sql + " WHERE source_id=?", (source_id,)
    with connect(db_path) as connection:
        rows = connection.execute(sql + " ORDER BY authority, title", params).fetchall()
    result = []
    for row in rows:
        data = dict(row)
        data["metadata"] = json.loads(data.pop("metadata_json"))
        result.append(data)
    return result


def insert_clause(clause: Clause, db_path: Path | str | None = None) -> Clause:
    with connect(db_path) as connection:
        connection.execute(
            """INSERT OR IGNORE INTO clauses
               (clause_id, version_id, article_ref, heading, text, page_number, start_offset, end_offset, text_sha256)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (clause.clause_id, clause.version_id, clause.article_ref, clause.heading, clause.text,
             clause.page_number, clause.start_offset, clause.end_offset, clause.text_sha256),
        )
    return clause


def list_clauses(version_id: str, db_path: Path | str | None = None) -> list[Clause]:
    with connect(db_path) as connection:
        rows = connection.execute("SELECT * FROM clauses WHERE version_id=? ORDER BY start_offset", (version_id,)).fetchall()
    return [Clause(**dict(row)) for row in rows]


def get_clause(clause_id: str, db_path: Path | str | None = None) -> Clause | None:
    with connect(db_path) as connection:
        row = connection.execute("SELECT * FROM clauses WHERE clause_id=?", (clause_id,)).fetchone()
    return Clause(**dict(row)) if row else None


def insert_change(change: RegulatoryChange, db_path: Path | str | None = None) -> RegulatoryChange:
    with connect(db_path) as connection:
        connection.execute(
            """INSERT OR IGNORE INTO regulatory_changes
               (change_id, source_id, old_version_id, new_version_id, before_clause_id, after_clause_id,
                article_ref, change_type, before_text, after_text, summary, substantive,
                numeric_before_json, numeric_after_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (change.change_id, change.source_id, change.old_version_id, change.new_version_id,
             change.before_clause_id, change.after_clause_id, change.article_ref, change.change_type.value,
             change.before_text, change.after_text, change.summary, int(change.substantive),
             _json(change.numeric_before), _json(change.numeric_after)),
        )
    return change


def _change_from_row(row: sqlite3.Row) -> RegulatoryChange:
    data = dict(row)
    data["numeric_before"] = json.loads(data.pop("numeric_before_json"))
    data["numeric_after"] = json.loads(data.pop("numeric_after_json"))
    data["substantive"] = bool(data["substantive"])
    return RegulatoryChange(**data)


def list_changes(old_version_id: str, new_version_id: str, db_path: Path | str | None = None) -> list[RegulatoryChange]:
    with connect(db_path) as connection:
        rows = connection.execute(
            "SELECT * FROM regulatory_changes WHERE old_version_id=? AND new_version_id=? ORDER BY article_ref",
            (old_version_id, new_version_id),
        ).fetchall()
    return [_change_from_row(row) for row in rows]


def get_change(change_id: str, db_path: Path | str | None = None) -> RegulatoryChange | None:
    with connect(db_path) as connection:
        row = connection.execute("SELECT * FROM regulatory_changes WHERE change_id=?", (change_id,)).fetchone()
    return _change_from_row(row) if row else None


def insert_company_snapshot(snapshot: CompanySnapshot, db_path: Path | str | None = None) -> CompanySnapshot:
    with connect(db_path) as connection:
        connection.execute("INSERT OR IGNORE INTO company_snapshots VALUES (?, ?, ?, ?, ?, ?)", (
            snapshot.company_snapshot_id, snapshot.company_id, snapshot.name, snapshot.captured_at.isoformat(),
            snapshot.jurisdiction, _json(snapshot),
        ))
    return snapshot


def get_company_snapshot(snapshot_id: str, db_path: Path | str | None = None) -> CompanySnapshot | None:
    with connect(db_path) as connection:
        row = connection.execute("SELECT payload_json FROM company_snapshots WHERE company_snapshot_id=?", (snapshot_id,)).fetchone()
    return CompanySnapshot.model_validate_json(row[0]) if row else None


def insert_evidence(item: Evidence, db_path: Path | str | None = None) -> Evidence:
    with connect(db_path) as connection:
        connection.execute(
            """INSERT OR REPLACE INTO evidence
               (evidence_id, company_snapshot_id, company_id, evidence_type, title, content, asset_id,
                observed_at, valid_from, valid_to, structured_data_json, source_quality)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (item.evidence_id, item.company_snapshot_id, item.company_id, item.evidence_type, item.title,
             item.content, item.asset_id, item.observed_at.isoformat() if item.observed_at else None,
             item.valid_from.isoformat() if item.valid_from else None,
             item.valid_to.isoformat() if item.valid_to else None,
             _json(item.structured_data), item.source_quality.value),
        )
    return item


def list_evidence(snapshot_id: str, db_path: Path | str | None = None) -> list[Evidence]:
    with connect(db_path) as connection:
        rows = connection.execute("SELECT * FROM evidence WHERE company_snapshot_id=? ORDER BY evidence_id", (snapshot_id,)).fetchall()
    result: list[Evidence] = []
    for row in rows:
        data = dict(row)
        data["structured_data"] = json.loads(data.pop("structured_data_json"))
        result.append(Evidence(**data))
    return result


def create_run_record(*, run_id: str, thread_id: str, company_snapshot_id: str, company_id: str,
                      source_id: str, old_version_id: str, new_version_id: str,
                      idempotency_key: str, request_hash: str,
                      db_path: Path | str | None = None) -> tuple[dict[str, Any], bool]:
    with connect(db_path) as connection:
        existing = connection.execute("SELECT * FROM runs WHERE idempotency_key=?", (idempotency_key,)).fetchone()
        if existing:
            if existing["request_hash"] != request_hash:
                raise ValueError("idempotency key is already bound to a different request")
            return dict(existing), False
        model_id = settings.llm_model if settings.llm_provider == "anthropic" else "deterministic-rules-1.0"
        connection.execute(
            """INSERT INTO runs
               (run_id, thread_id, company_snapshot_id, company_id, source_id, old_version_id,
                new_version_id, idempotency_key, request_hash, phase, pipeline_version, model_id,
                prompt_version, schema_version, started_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, thread_id, company_snapshot_id, company_id, source_id, old_version_id,
             new_version_id, idempotency_key, request_hash, RunPhase.queued.value,
             settings.pipeline_version, model_id, settings.prompt_version, settings.schema_version, _now()),
        )
        row = connection.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
    return dict(row), True


def get_run(run_id: str, db_path: Path | str | None = None) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        row = connection.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
    return dict(row) if row else None


def update_run_phase(run_id: str, phase: RunPhase, *, error_code: str | None = None,
                     error_message: str | None = None, db_path: Path | str | None = None) -> None:
    finished = _now() if phase in {RunPhase.completed, RunPhase.failed, RunPhase.no_change} else None
    with connect(db_path) as connection:
        connection.execute(
            "UPDATE runs SET phase=?, finished_at=COALESCE(?, finished_at), error_code=?, error_message=? WHERE run_id=?",
            (phase.value, finished, error_code, error_message, run_id),
        )


def save_run_state(state: RunState, db_path: Path | str | None = None) -> None:
    state.updated_at = datetime.now(timezone.utc)
    with connect(db_path) as connection:
        connection.execute(
            """INSERT INTO run_states(run_id, state_json, updated_at) VALUES (?, ?, ?)
               ON CONFLICT(run_id) DO UPDATE SET state_json=excluded.state_json, updated_at=excluded.updated_at""",
            (state.run_id, _json(state), state.updated_at.isoformat()),
        )
        connection.execute("UPDATE runs SET phase=? WHERE run_id=?", (state.phase.value, state.run_id))


def load_run_state(run_id: str, db_path: Path | str | None = None) -> RunState | None:
    with connect(db_path) as connection:
        row = connection.execute("SELECT state_json FROM run_states WHERE run_id=?", (run_id,)).fetchone()
    return RunState.model_validate_json(row[0]) if row else None


def insert_obligation(item: Obligation, db_path: Path | str | None = None) -> Obligation:
    p = item.provenance
    with connect(db_path) as connection:
        connection.execute(
            """INSERT OR IGNORE INTO obligations
               (obligation_id, obligation_key, run_id, company_id, source_id, version_id, model_id,
                prompt_version, schema_version, clause_id, change_id, article_ref, payload_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (item.obligation_id, item.obligation_key, p.run_id, p.company_id, p.source_id, p.version_id,
             p.model_id, p.prompt_version, p.schema_version, item.clause_id, item.change_id,
             item.article_ref, _json(item)),
        )
        row = connection.execute(
            "SELECT payload_json FROM obligations WHERE run_id=? AND change_id=? AND obligation_key=?",
            (p.run_id, item.change_id, item.obligation_key),
        ).fetchone()
    return Obligation.model_validate_json(row[0])


def list_obligations(run_id: str, db_path: Path | str | None = None) -> list[Obligation]:
    with connect(db_path) as connection:
        rows = connection.execute("SELECT payload_json FROM obligations WHERE run_id=? ORDER BY article_ref", (run_id,)).fetchall()
    return [Obligation.model_validate_json(row[0]) for row in rows]


def insert_applicability(item: ApplicabilityResult, db_path: Path | str | None = None) -> ApplicabilityResult:
    with connect(db_path) as connection:
        connection.execute(
            """INSERT OR IGNORE INTO applicability_results
               (applicability_id, run_id, obligation_id, company_snapshot_id, payload_json)
               VALUES (?, ?, ?, ?, ?)""",
            (item.applicability_id, item.provenance.run_id, item.obligation_id,
             item.company_snapshot_id, _json(item)),
        )
        row = connection.execute(
            "SELECT payload_json FROM applicability_results WHERE run_id=? AND obligation_id=?",
            (item.provenance.run_id, item.obligation_id),
        ).fetchone()
    return ApplicabilityResult.model_validate_json(row[0])


def get_applicability(run_id: str, obligation_id: str, db_path: Path | str | None = None) -> ApplicabilityResult | None:
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT payload_json FROM applicability_results WHERE run_id=? AND obligation_id=?",
            (run_id, obligation_id),
        ).fetchone()
    return ApplicabilityResult.model_validate_json(row[0]) if row else None


def insert_finding(item: Finding, db_path: Path | str | None = None) -> Finding:
    p = item.provenance
    with connect(db_path) as connection:
        connection.execute(
            """INSERT OR IGNORE INTO findings
               (finding_id, run_id, company_id, source_id, version_id, model_id, prompt_version,
                schema_version, change_id, obligation_id, assessment_status, priority, payload_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (item.finding_id, p.run_id, p.company_id, p.source_id, p.version_id, p.model_id,
             p.prompt_version, p.schema_version, item.change_id, item.obligation_id,
             item.assessment_status.value, item.priority, _json(item)),
        )
        row = connection.execute(
            "SELECT payload_json FROM findings WHERE run_id=? AND change_id=? AND obligation_id=?",
            (p.run_id, item.change_id, item.obligation_id),
        ).fetchone()
    return Finding.model_validate_json(row[0])


def list_findings(run_id: str, db_path: Path | str | None = None) -> list[Finding]:
    with connect(db_path) as connection:
        rows = connection.execute("SELECT payload_json FROM findings WHERE run_id=? ORDER BY finding_id", (run_id,)).fetchall()
    return [Finding.model_validate_json(row[0]) for row in rows]


def insert_task(item: TaskDraft, db_path: Path | str | None = None) -> TaskDraft:
    p = item.provenance
    with connect(db_path) as connection:
        connection.execute(
            """INSERT OR IGNORE INTO task_drafts
               (task_id, run_id, company_id, source_id, version_id, model_id, prompt_version,
                schema_version, finding_id, review_status, revision, payload_json, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (item.task_id, p.run_id, p.company_id, p.source_id, p.version_id, p.model_id,
             p.prompt_version, p.schema_version, item.finding_id, item.review_status,
             item.revision, _json(item), _now()),
        )
        row = connection.execute("SELECT payload_json FROM task_drafts WHERE finding_id=?", (item.finding_id,)).fetchone()
    return TaskDraft.model_validate_json(row[0])


def get_task(task_id: str, db_path: Path | str | None = None) -> TaskDraft | None:
    with connect(db_path) as connection:
        row = connection.execute("SELECT payload_json FROM task_drafts WHERE task_id=?", (task_id,)).fetchone()
    return TaskDraft.model_validate_json(row[0]) if row else None


def list_tasks(run_id: str, db_path: Path | str | None = None) -> list[TaskDraft]:
    with connect(db_path) as connection:
        rows = connection.execute("SELECT payload_json FROM task_drafts WHERE run_id=? ORDER BY task_id", (run_id,)).fetchall()
    return [TaskDraft.model_validate_json(row[0]) for row in rows]


def update_task_and_add_review(task: TaskDraft, review_payload: dict[str, Any], db_path: Path | str | None = None) -> None:
    with connect(db_path) as connection:
        row = connection.execute("SELECT revision FROM task_drafts WHERE task_id=?", (task.task_id,)).fetchone()
        if not row or row[0] != review_payload["reviewed_revision"]:
            raise sqlite3.IntegrityError("stale_revision")
        connection.execute(
            "UPDATE task_drafts SET review_status=?, revision=?, payload_json=?, updated_at=? WHERE task_id=?",
            (task.review_status, task.revision, _json(task), _now(), task.task_id),
        )
        connection.execute("INSERT INTO reviews VALUES (?, ?, ?, ?, ?, ?, ?)", (
            review_payload["review_id"], task.task_id, review_payload["reviewer_id"],
            review_payload["decision"], review_payload["comment"],
            review_payload["reviewed_revision"], review_payload["created_at"],
        ))


def list_reviews(task_id: str, db_path: Path | str | None = None) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        rows = connection.execute("SELECT * FROM reviews WHERE task_id=? ORDER BY created_at", (task_id,)).fetchall()
    return [dict(row) for row in rows]


def add_audit_event(event: AuditEvent, db_path: Path | str | None = None) -> None:
    with connect(db_path) as connection:
        connection.execute(
            """INSERT OR IGNORE INTO audit_events
               (event_id, run_id, actor_id, actor_role, action, entity_type, entity_id,
                reason_summary, evidence_ids_json, tool_name, before_hash, after_hash, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (event.event_id, event.run_id, event.actor_id, event.actor_role, event.action,
             event.entity_type, event.entity_id, event.reason_summary, _json(event.evidence_ids),
             event.tool_name, event.before_hash, event.after_hash, event.created_at.isoformat()),
        )


def list_audit_events(run_id: str, db_path: Path | str | None = None) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        rows = connection.execute("SELECT * FROM audit_events WHERE run_id=? ORDER BY created_at, event_id", (run_id,)).fetchall()
    result = []
    for row in rows:
        data = dict(row)
        data["evidence_ids"] = json.loads(data.pop("evidence_ids_json"))
        result.append(data)
    return result


def fetch_run_bundle(run_id: str, db_path: Path | str | None = None) -> dict[str, Any]:
    run = get_run(run_id, db_path)
    if not run:
        raise KeyError(run_id)
    state = load_run_state(run_id, db_path)
    return {
        "run": run,
        "state": state.model_dump(mode="json") if state else None,
        "changes": [x.model_dump(mode="json") for x in list_changes(run["old_version_id"], run["new_version_id"], db_path)],
        "obligations": [x.model_dump(mode="json") for x in list_obligations(run_id, db_path)],
        "findings": [x.model_dump(mode="json") for x in list_findings(run_id, db_path)],
        "tasks": [x.model_dump(mode="json") for x in list_tasks(run_id, db_path)],
        "audit_events": list_audit_events(run_id, db_path),
    }


def create_scan_record(
    *, scan_id: str, company_snapshot_id: str, company_id: str, idempotency_key: str,
    request_hash: str, db_path: Path | str | None = None,
) -> tuple[dict[str, Any], bool]:
    with connect(db_path) as connection:
        existing = connection.execute(
            "SELECT * FROM regulatory_scan_runs WHERE idempotency_key=?", (idempotency_key,)
        ).fetchone()
        if existing:
            if existing["request_hash"] != request_hash:
                raise ValueError("idempotency key is already bound to a different regulatory scan")
            return dict(existing), False
        connection.execute(
            """INSERT INTO regulatory_scan_runs
               (scan_id, company_snapshot_id, company_id, idempotency_key, request_hash, status, started_at)
               VALUES (?, ?, ?, ?, ?, 'queued', ?)""",
            (scan_id, company_snapshot_id, company_id, idempotency_key, request_hash, _now()),
        )
        row = connection.execute(
            "SELECT * FROM regulatory_scan_runs WHERE scan_id=?", (scan_id,)
        ).fetchone()
    return dict(row), True


def update_scan_record(
    scan_id: str, *, status: str, counters: dict[str, int] | None = None,
    summary: dict[str, Any] | None = None, db_path: Path | str | None = None,
) -> None:
    counters = counters or {}
    allowed = {
        "sources_checked", "documents_discovered", "versions_created", "unchanged_documents",
        "changes_created", "relevant_documents", "filtered_documents", "error_count",
    }
    assignments = ["status=?"]
    params: list[Any] = [status]
    for key, value in counters.items():
        if key not in allowed:
            raise ValueError(f"unsupported scan counter: {key}")
        assignments.append(f"{key}=?")
        params.append(value)
    if summary is not None:
        assignments.append("summary_json=?")
        params.append(_json(summary))
    if status in {"completed", "completed_with_errors", "failed"}:
        assignments.append("finished_at=?")
        params.append(_now())
    params.append(scan_id)
    with connect(db_path) as connection:
        connection.execute(
            f"UPDATE regulatory_scan_runs SET {', '.join(assignments)} WHERE scan_id=?", params
        )


def get_scan(scan_id: str, db_path: Path | str | None = None) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM regulatory_scan_runs WHERE scan_id=?", (scan_id,)
        ).fetchone()
    if not row:
        return None
    data = dict(row)
    data["summary"] = json.loads(data.pop("summary_json") or "{}")
    return data


def add_source_fetch_event(event: dict[str, Any], db_path: Path | str | None = None) -> None:
    with connect(db_path) as connection:
        connection.execute(
            """INSERT OR REPLACE INTO source_fetch_events
               (fetch_event_id, scan_id, source_id, document_id, status, http_status,
                canonical_url, content_sha256, error_code, error_message, started_at,
                finished_at, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (event["fetch_event_id"], event["scan_id"], event["source_id"], event.get("document_id"),
             event["status"], event.get("http_status"), event["canonical_url"],
             event.get("content_sha256"), event.get("error_code"), event.get("error_message"),
             event["started_at"], event["finished_at"], _json(event.get("metadata", {}))),
        )


def upsert_scan_document_result(result: dict[str, Any], db_path: Path | str | None = None) -> None:
    with connect(db_path) as connection:
        connection.execute(
            """INSERT INTO scan_document_results
               (scan_id, document_id, version_id, previous_version_id, outcome,
                applicability_status, applicability_rationale, change_count, priority,
                department_ids_json, analysis_run_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(scan_id, document_id) DO UPDATE SET
                 version_id=excluded.version_id, previous_version_id=excluded.previous_version_id,
                 outcome=excluded.outcome, applicability_status=excluded.applicability_status,
                 applicability_rationale=excluded.applicability_rationale,
                 change_count=excluded.change_count, priority=excluded.priority,
                 department_ids_json=excluded.department_ids_json,
                 analysis_run_id=excluded.analysis_run_id""",
            (result["scan_id"], result["document_id"], result.get("version_id"),
             result.get("previous_version_id"), result["outcome"], result["applicability_status"],
             result["applicability_rationale"], result.get("change_count", 0),
             result.get("priority", "pending_review"), _json(result.get("department_ids", [])),
             result.get("analysis_run_id"), result.get("created_at", _now())),
        )


def get_scan_results(scan_id: str, db_path: Path | str | None = None) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """SELECT r.*, d.title, d.authority, d.category, d.canonical_url, d.download_url
               FROM scan_document_results r JOIN regulatory_documents d USING(document_id)
               WHERE r.scan_id=? ORDER BY d.authority, d.title""",
            (scan_id,),
        ).fetchall()
    result = []
    for row in rows:
        data = dict(row)
        data["department_ids"] = json.loads(data.pop("department_ids_json"))
        changes: list[RegulatoryChange] = []
        if data.get("previous_version_id") and data.get("version_id") != data.get("previous_version_id"):
            changes = list_changes(data["previous_version_id"], data["version_id"], db_path)
        data["change_previews"] = [
            {
                "article_ref": item.article_ref,
                "change_type": item.change_type.value,
                "old_text": item.before_text,
                "new_text": item.after_text,
                "summary": item.summary,
            }
            for item in changes[:20]
        ]
        data["affected_files"] = []
        data["affected_files_status"] = (
            "no_traceable_internal_file_evidence" if data.get("analysis_run_id") else "not_analyzed_without_change"
        )
        data["financial_exposure"] = {
            "status": "not_enough_data",
            "label": "Estimated Financial Exposure",
            "amount": None,
            "currency": None,
            "basis": "No cited penalty or approved company cost inputs are linked to this result.",
            "confidence": "not_assessed",
        }
        data["pipeline_status"] = (
            (get_run(data["analysis_run_id"], db_path) or {}).get("phase")
            if data.get("analysis_run_id") else None
        )
        result.append(data)
    return result


def list_source_fetch_events(scan_id: str, db_path: Path | str | None = None) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        rows = connection.execute(
            "SELECT * FROM source_fetch_events WHERE scan_id=? ORDER BY started_at", (scan_id,)
        ).fetchall()
    result = []
    for row in rows:
        data = dict(row)
        data["metadata"] = json.loads(data.pop("metadata_json"))
        result.append(data)
    return result


def dashboard_summary(db_path: Path | str | None = None) -> dict[str, Any]:
    with connect(db_path) as connection:
        latest = connection.execute(
            "SELECT * FROM regulatory_scan_runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        counts = connection.execute(
            """SELECT
                 COUNT(*) AS total,
                 SUM(CASE WHEN applicability_status IN ('applicable','potentially_applicable') THEN 1 ELSE 0 END) AS relevant,
                 SUM(CASE WHEN applicability_status='not_applicable' THEN 1 ELSE 0 END) AS filtered,
                 SUM(CASE WHEN priority='high' THEN 1 ELSE 0 END) AS high_priority
               FROM scan_document_results"""
        ).fetchone()
    return {"latest_scan": dict(latest) if latest else None, "documents": dict(counts)}


def create_grc_task(
    task: GRCTaskCreate, *, adapter_name: str, db_path: Path | str | None = None
) -> dict[str, Any]:
    grc_task_id = stable_id("grc", task.local_task_id or "", task.title, task.description)
    now = _now()
    with connect(db_path) as connection:
        connection.execute(
            """INSERT OR IGNORE INTO grc_tasks
               (grc_task_id, local_task_id, title, description, status, owner, priority,
                due_date, evidence_refs_json, adapter_name, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?)""",
            (grc_task_id, task.local_task_id, task.title, task.description, task.owner,
             task.priority, task.due_date.isoformat() if task.due_date else None,
             _json(task.evidence_refs), adapter_name, now, now),
        )
    return get_grc_task(grc_task_id, db_path)


def get_grc_task(grc_task_id: str, db_path: Path | str | None = None) -> dict[str, Any]:
    with connect(db_path) as connection:
        row = connection.execute("SELECT * FROM grc_tasks WHERE grc_task_id=?", (grc_task_id,)).fetchone()
    if not row:
        raise KeyError(grc_task_id)
    data = dict(row)
    data["evidence_refs"] = json.loads(data.pop("evidence_refs_json"))
    return data


def update_grc_task(
    grc_task_id: str, changes: dict[str, Any], db_path: Path | str | None = None
) -> dict[str, Any]:
    allowed = {"status", "owner", "priority", "due_date", "evidence_refs"}
    if not changes or any(key not in allowed for key in changes):
        raise ValueError("unsupported GRC task update")
    assignments, params = [], []
    for key, value in changes.items():
        column = "evidence_refs_json" if key == "evidence_refs" else key
        assignments.append(f"{column}=?")
        params.append(_json(value) if key == "evidence_refs" else value)
    assignments.append("updated_at=?")
    params.extend([_now(), grc_task_id])
    with connect(db_path) as connection:
        if not connection.execute("SELECT 1 FROM grc_tasks WHERE grc_task_id=?", (grc_task_id,)).fetchone():
            raise KeyError(grc_task_id)
        connection.execute(f"UPDATE grc_tasks SET {', '.join(assignments)} WHERE grc_task_id=?", params)
    return get_grc_task(grc_task_id, db_path)


def insert_export_sector_regulation(
    item: dict[str, Any], db_path: Path | str | None = None
) -> dict[str, Any]:
    with connect(db_path) as connection:
        connection.execute(
            """INSERT OR REPLACE INTO export_sector_regulations
               (export_regulation_id, source_id, authority, jurisdiction,
                controlled_technology_category, restriction_type, destination_country,
                effective_date, licensing_requirement, official_source_url, document_id,
                metadata_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (item["export_regulation_id"], item["source_id"], item["authority"], item["jurisdiction"],
             item["controlled_technology_category"], item["restriction_type"],
             item.get("destination_country"), item.get("effective_date"),
             item["licensing_requirement"], item["official_source_url"], item.get("document_id"),
             _json(item.get("metadata", {})), item.get("created_at", _now())),
        )
        row = connection.execute(
            "SELECT * FROM export_sector_regulations WHERE export_regulation_id=?",
            (item["export_regulation_id"],),
        ).fetchone()
    data = dict(row)
    data["metadata"] = json.loads(data.pop("metadata_json"))
    return data


def healthcheck(db_path: Path | str | None = None) -> bool:
    try:
        with connect(db_path) as connection:
            return connection.execute("SELECT 1").fetchone()[0] == 1
    except sqlite3.Error:
        return False


def insert_company_document(item: CompanyDocument, db_path=None) -> CompanyDocument:
    with connect(db_path) as connection:
        connection.execute(
            """INSERT OR IGNORE INTO company_documents
               (company_document_id, company_snapshot_id, company_id, title, filename, mime_type,
                document_kind, department, project_id, sha256, storage_uri, metadata_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (item.company_document_id, item.company_snapshot_id, item.company_id, item.title,
             item.filename, item.mime_type, item.document_kind, item.department, item.project_id,
             item.sha256, item.storage_uri, _json(item.metadata), item.created_at.isoformat()),
        )
        row = connection.execute("SELECT * FROM company_documents WHERE company_document_id=?",
                                 (item.company_document_id,)).fetchone()
    data = dict(row); data["metadata"] = json.loads(data.pop("metadata_json"))
    return CompanyDocument.model_validate(data)


def insert_company_document_chunk(item: CompanyDocumentChunk, db_path=None) -> CompanyDocumentChunk:
    with connect(db_path) as connection:
        connection.execute(
            """INSERT OR IGNORE INTO company_document_chunks
               (chunk_id, company_document_id, sequence_no, locator_type, locator_json,
                section_ref, text, text_sha256) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (item.chunk_id, item.company_document_id, item.sequence_no, item.locator.locator_type,
             _json(item.locator), item.section_ref, item.text, item.text_sha256),
        )
        row = connection.execute("SELECT * FROM company_document_chunks WHERE chunk_id=?",
                                 (item.chunk_id,)).fetchone()
    data = dict(row); data["locator"] = json.loads(data.pop("locator_json")); data.pop("locator_type")
    return CompanyDocumentChunk.model_validate(data)


def get_company_document(document_id: str, db_path=None) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        row = connection.execute("SELECT * FROM company_documents WHERE company_document_id=?",
                                 (document_id,)).fetchone()
    if not row: return None
    data = dict(row); data["metadata"] = json.loads(data.pop("metadata_json")); return data


def list_company_documents(company_snapshot_id: str | None = None, db_path=None) -> list[dict[str, Any]]:
    sql, params = "SELECT * FROM company_documents", ()
    if company_snapshot_id: sql += " WHERE company_snapshot_id=?"; params = (company_snapshot_id,)
    sql += " ORDER BY created_at DESC"
    with connect(db_path) as connection: rows = connection.execute(sql, params).fetchall()
    result = []
    for row in rows:
        data = dict(row); data["metadata"] = json.loads(data.pop("metadata_json")); result.append(data)
    return result


def list_company_document_chunks(document_id: str, db_path=None) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        rows = connection.execute("SELECT * FROM company_document_chunks WHERE company_document_id=? ORDER BY sequence_no",
                                  (document_id,)).fetchall()
    result = []
    for row in rows:
        data = dict(row); data["locator"] = json.loads(data.pop("locator_json")); result.append(data)
    return result


def insert_dependency(item: dict[str, Any], db_path=None) -> dict[str, Any]:
    dependency_id = stable_id("dep", item["company_document_id"], item["chunk_id"],
                              item["version_id"], item["clause_id"], item["obligation_key"])
    with connect(db_path) as connection:
        connection.execute(
            """INSERT OR IGNORE INTO document_dependencies
               (dependency_id, company_id, company_document_id, chunk_id, source_id, version_id,
                clause_id, obligation_id, obligation_key, article_ref, department, project_id,
                relationship_type, active, established_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
            (dependency_id, item["company_id"], item["company_document_id"], item["chunk_id"],
             item["source_id"], item["version_id"], item["clause_id"], item.get("obligation_id"),
             item["obligation_key"], item["article_ref"], item["department"], item.get("project_id"),
             item.get("relationship_type", "depends_on"), _now()),
        )
        row = connection.execute("SELECT * FROM document_dependencies WHERE dependency_id=?", (dependency_id,)).fetchone()
    return dict(row)


def list_dependencies(*, company_document_id: str | None = None, article_ref: str | None = None, db_path=None) -> list[dict[str, Any]]:
    sql = """SELECT d.*, cd.title AS document_title, cd.filename, c.locator_json, c.section_ref,
                    c.text AS document_quote, s.authority
             FROM document_dependencies d JOIN company_documents cd USING(company_document_id)
             JOIN company_document_chunks c USING(chunk_id) JOIN sources s USING(source_id) WHERE 1=1"""
    params: list[Any] = []
    if company_document_id: sql += " AND d.company_document_id=?"; params.append(company_document_id)
    if article_ref: sql += " AND d.article_ref=?"; params.append(article_ref)
    with connect(db_path) as connection: rows = connection.execute(sql, params).fetchall()
    result=[]
    for row in rows:
        data=dict(row); data["locator"] = json.loads(data.pop("locator_json")); result.append(data)
    return result


def upsert_financial_input(item: FinancialInput, db_path=None) -> dict[str, Any]:
    input_id = stable_id("fin", item.company_snapshot_id)
    with connect(db_path) as connection:
        connection.execute(
            """INSERT OR REPLACE INTO company_financial_inputs
               (financial_input_id, company_snapshot_id, currency, remediation_cost,
                project_delay_daily_cost, expected_delay_days, downtime_hourly_cost,
                expected_downtime_hours, contract_exposure, is_synthetic, label, payload_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (input_id, item.company_snapshot_id, item.currency, item.remediation_cost,
             item.project_delay_daily_cost, item.expected_delay_days, item.downtime_hourly_cost,
             item.expected_downtime_hours, item.contract_exposure, int(item.is_synthetic), item.label,
             _json(item), _now()),
        )
        row=connection.execute("SELECT * FROM company_financial_inputs WHERE financial_input_id=?", (input_id,)).fetchone()
    data=dict(row); data["payload"] = json.loads(data.pop("payload_json")); return data


def get_financial_input(snapshot_id: str, db_path=None) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        row=connection.execute("SELECT * FROM company_financial_inputs WHERE company_snapshot_id=?", (snapshot_id,)).fetchone()
    if not row: return None
    data=dict(row); data["payload"] = json.loads(data.pop("payload_json")); return data


def get_compliance_review(review_id: str, db_path=None) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        row=connection.execute("SELECT * FROM compliance_reviews WHERE compliance_review_id=?", (review_id,)).fetchone()
        findings=connection.execute("SELECT * FROM compliance_review_findings WHERE compliance_review_id=? ORDER BY severity DESC, article_ref", (review_id,)).fetchall()
        exposure=connection.execute("SELECT * FROM financial_exposures WHERE compliance_review_id=?", (review_id,)).fetchone()
    if not row: return None
    data=dict(row); data["summary"] = json.loads(data.pop("summary_json")); data["findings"]=[]
    for finding in findings:
        item=dict(finding); item["locator"] = json.loads(item.pop("locator_json")) if item.get("locator_json") else None; data["findings"].append(item)
    if exposure:
        e=dict(exposure); e["breakdown"]=json.loads(e.pop("breakdown_json")); e["formula"]=json.loads(e.pop("formula_json")); data["financial_exposure"]=e
    else: data["financial_exposure"]={"status":"not_enough_data"}
    data["dependencies"] = list_dependencies(company_document_id=data["company_document_id"], db_path=db_path)
    return data
