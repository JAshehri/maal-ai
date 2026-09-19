from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .. import db
from ..change_detection import compare_versions
from ..ingestion import detect_prompt_injection, extract_clauses, sha256_text
from ..pipeline import create_run, execute_run
from ..schemas import DocumentVersion, RegulatoryScanCreate, RunCreate
from ..settings import settings
from .applicability import classify_discovered_document
from .connectors.base import ConnectorError, RegulatorySourceConnector
from .extraction import extract_official_text, sha256_bytes
from .registry import connector_for_source


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request_hash(request: RegulatoryScanCreate) -> str:
    return hashlib.sha256(
        json.dumps(request.model_dump(mode="json"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def create_regulatory_scan(
    request: RegulatoryScanCreate, db_path: Path | str | None = None
) -> tuple[dict[str, Any], bool]:
    db.init_db(db_path)
    snapshot = db.get_company_snapshot(request.company_snapshot_id, db_path)
    if not snapshot:
        raise KeyError("company snapshot not found")
    scan_id = db.stable_id("scan", request.idempotency_key)
    return db.create_scan_record(
        scan_id=scan_id,
        company_snapshot_id=request.company_snapshot_id,
        company_id=snapshot.company_id,
        idempotency_key=request.idempotency_key,
        request_hash=_request_hash(request),
        db_path=db_path,
    )


def _safe_storage_path(
    authority: str, document_id: str, raw_hash: str, filename: str,
    *, storage_root: Path | None = None,
) -> Path:
    suffix = Path(filename).suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
        suffix = ".bin"
    authority_dir = re.sub(r"[^A-Za-z0-9_-]+", "-", authority).strip("-") or "source"
    root = (storage_root or settings.regulatory_storage_dir).resolve()
    destination = (root / authority_dir / document_id / f"{raw_hash}{suffix}").resolve()
    if root not in destination.parents:
        raise ValueError("unsafe regulatory storage path")
    return destination


def _store_new_version(
    fetched,
    *,
    previous: dict[str, Any] | None,
    db_path: Path | str | None,
) -> tuple[DocumentVersion, list[str]]:
    raw_hash = sha256_bytes(fetched.content)
    extracted_text, extraction_warnings = extract_official_text(
        fetched.content, fetched.content_type, fetched.filename
    )
    if not extracted_text:
        raise ValueError("official document contains no extractable text")
    storage_root = None
    actual_db_path = Path(db_path or settings.database_path).resolve()
    default_storage = (settings.root_dir / "data" / "regulatory" / "raw").resolve()
    if actual_db_path != (settings.root_dir / "maal.db").resolve() and settings.regulatory_storage_dir == default_storage:
        storage_root = actual_db_path.parent / "regulatory_raw"
    storage_path = _safe_storage_path(
        fetched.document.authority, fetched.document.document_id, raw_hash, fetched.filename,
        storage_root=storage_root,
    )
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    if not storage_path.exists():
        storage_path.write_bytes(fetched.content)
    try:
        storage_uri = str(storage_path.relative_to(settings.root_dir)).replace("\\", "/")
    except ValueError:
        storage_uri = str(storage_path)
    version = DocumentVersion(
        version_id=db.stable_id("ver", fetched.document.document_id, raw_hash),
        source_id=fetched.document.source_id,
        document_id=fetched.document.document_id,
        sha256=raw_hash,
        text_sha256=sha256_text(extracted_text),
        content=extracted_text,
        published_at=fetched.document.publication_date,
        effective_at=fetched.document.mandatory_application_date,
        supersedes_version_id=previous["version_id"] if previous else None,
        storage_uri=storage_uri,
        mime_type=fetched.content_type,
        original_filename=fetched.filename,
        source_last_modified_at=fetched.document.last_modified_at,
    )
    stored = db.insert_document_version(version, db_path)
    for clause in extract_clauses(stored.version_id, stored.content):
        db.insert_clause(clause, db_path)
    return stored, [*extraction_warnings, *detect_prompt_injection(extracted_text)]


def _select_sources(request: RegulatoryScanCreate, db_path: Path | str | None) -> list[dict[str, Any]]:
    sources = [
        item for item in db.list_sources(db_path)
        if item["enabled"] and item["approval_status"] == "approved"
        and item["connector_type"] in {"nca_html", "saso_html"}
    ]
    if request.source_ids:
        allowed = set(request.source_ids)
        sources = [item for item in sources if item["source_id"] in allowed]
    if request.jurisdictions:
        jurisdictions = set(request.jurisdictions)
        sources = [item for item in sources if item["jurisdiction"] in jurisdictions]
    if request.domains:
        tokens = [item.casefold() for item in request.domains]
        sources = [
            item for item in sources
            if any(token in item["regulatory_domain"].casefold() for token in tokens)
        ]
    return sources


def execute_regulatory_scan(
    scan_id: str,
    *,
    request: RegulatoryScanCreate,
    db_path: Path | str | None = None,
    connector_overrides: dict[str, RegulatorySourceConnector] | None = None,
) -> dict[str, Any]:
    scan = db.get_scan(scan_id, db_path)
    snapshot = db.get_company_snapshot(request.company_snapshot_id, db_path)
    if not scan or not snapshot:
        raise KeyError(scan_id)
    if scan["status"] in {"completed", "completed_with_errors"}:
        return scan
    counters = {
        "sources_checked": 0, "documents_discovered": 0, "versions_created": 0,
        "unchanged_documents": 0, "changes_created": 0, "relevant_documents": 0,
        "filtered_documents": 0, "error_count": 0,
    }
    errors: list[dict[str, str]] = []
    db.update_scan_record(scan_id, status="running", counters=counters, db_path=db_path)
    sources = _select_sources(request, db_path)
    for source in sources:
        connector = (connector_overrides or {}).get(source["source_id"]) or connector_for_source(source)
        source_ok = True
        try:
            documents = connector.discover(source["source_id"])
            counters["sources_checked"] += 1
            counters["documents_discovered"] += len(documents)
        except Exception as exc:
            source_ok = False
            counters["error_count"] += 1
            errors.append({"source_id": source["source_id"], "error": type(exc).__name__})
            db.add_source_fetch_event({
                "fetch_event_id": db.stable_id("fetch", scan_id, source["source_id"], "discovery"),
                "scan_id": scan_id, "source_id": source["source_id"], "status": "failed",
                "canonical_url": source["canonical_url"], "error_code": type(exc).__name__,
                "error_message": str(exc)[:500], "started_at": _now(), "finished_at": _now(),
            }, db_path)
            db.update_source_scan_time(source["source_id"], checked_at=_now(), successful=False, db_path=db_path)
            continue
        for discovered in documents:
            applicability = classify_discovered_document(discovered, snapshot)
            document = db.upsert_regulatory_document(discovered, db_path)
            if applicability.status in {"not_applicable", "needs_review"}:
                counters["filtered_documents"] += 1
                db.upsert_scan_document_result({
                    "scan_id": scan_id, "document_id": document.document_id,
                    "outcome": "filtered" if applicability.status == "not_applicable" else "needs_review",
                    "applicability_status": applicability.status,
                    "applicability_rationale": applicability.rationale,
                    "priority": applicability.priority, "department_ids": applicability.department_ids,
                }, db_path)
                continue
            counters["relevant_documents"] += 1
            fetch_started = _now()
            try:
                fetched = connector.fetch_document(document)
                raw_hash = sha256_bytes(fetched.content)
                previous = db.latest_document_version(document.document_id, db_path)
                if previous and previous["sha256"] == raw_hash:
                    counters["unchanged_documents"] += 1
                    outcome, version, changes, analysis_run_id = "unchanged", previous, [], None
                else:
                    version_model, warnings = _store_new_version(fetched, previous=previous, db_path=db_path)
                    version = version_model.model_dump(mode="json")
                    counters["versions_created"] += 1
                    changes = compare_versions(previous["version_id"], version_model.version_id, db_path) if previous else []
                    counters["changes_created"] += len(changes)
                    outcome = "changed" if previous else "new"
                    analysis_run_id = None
                    # A document can be archived while still only potentially applicable.
                    # Impact analysis is gated on affirmative applicability so ambiguous
                    # scope never produces findings or compliance tasks.
                    if previous and changes and applicability.status == "applicable":
                        run_request = RunCreate(
                            company_snapshot_id=request.company_snapshot_id,
                            old_version_id=previous["version_id"], new_version_id=version_model.version_id,
                            idempotency_key=f"scan-{scan_id}-{document.document_id}-{raw_hash[:16]}",
                        )
                        run, created = create_run(run_request, db_path)
                        if created:
                            execute_run(run["run_id"], db_path=db_path)
                        analysis_run_id = run["run_id"]
                db.upsert_scan_document_result({
                    "scan_id": scan_id, "document_id": document.document_id,
                    "version_id": version["version_id"],
                    "previous_version_id": previous["version_id"] if previous else None,
                    "outcome": outcome, "applicability_status": applicability.status,
                    "applicability_rationale": applicability.rationale,
                    "change_count": len(changes), "priority": applicability.priority,
                    "department_ids": applicability.department_ids, "analysis_run_id": analysis_run_id,
                }, db_path)
                db.add_source_fetch_event({
                    "fetch_event_id": db.stable_id("fetch", scan_id, document.document_id, raw_hash),
                    "scan_id": scan_id, "source_id": source["source_id"], "document_id": document.document_id,
                    "status": outcome, "http_status": fetched.http_status,
                    "canonical_url": document.canonical_url, "content_sha256": raw_hash,
                    "started_at": fetch_started, "finished_at": _now(),
                    "metadata": {"download_url": document.download_url, "final_url": fetched.final_url},
                }, db_path)
            except Exception as exc:
                source_ok = False
                counters["error_count"] += 1
                errors.append({"document_id": document.document_id, "error": type(exc).__name__})
                db.add_source_fetch_event({
                    "fetch_event_id": db.stable_id("fetch", scan_id, document.document_id, type(exc).__name__),
                    "scan_id": scan_id, "source_id": source["source_id"], "document_id": document.document_id,
                    "status": "failed", "canonical_url": document.canonical_url,
                    "error_code": type(exc).__name__, "error_message": str(exc)[:500],
                    "started_at": fetch_started, "finished_at": _now(),
                }, db_path)
        db.update_source_scan_time(source["source_id"], checked_at=_now(), successful=source_ok, db_path=db_path)
    final_status = "completed_with_errors" if counters["error_count"] else "completed"
    db.update_scan_record(
        scan_id, status=final_status, counters=counters,
        summary={"errors": errors, "source_ids": [item["source_id"] for item in sources]}, db_path=db_path,
    )
    return db.get_scan(scan_id, db_path) or {}
