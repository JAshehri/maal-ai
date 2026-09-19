from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .. import db
from ..schemas import ExportSectorRegulationCreate, FetchedDocument, RegulatoryDocument
from .discovery import _store_new_version
from .registry import seed_regulatory_sources


def register_manual_export_regulation(
    payload: ExportSectorRegulationCreate,
    *,
    file_content: bytes | None = None,
    filename: str | None = None,
    content_type: str | None = None,
    db_path: Path | str | None = None,
) -> dict:
    source_id = seed_regulatory_sources(db_path)["Manual Export/Sector Source"]
    document = RegulatoryDocument(
        document_id=db.stable_id("regdoc", source_id, payload.official_source_url, payload.title),
        source_id=source_id,
        authority=payload.authority,
        jurisdiction=payload.jurisdiction,
        regulatory_domain="Export Control / Sector Regulations",
        title=payload.title,
        document_type="export_sector_regulation",
        category=payload.controlled_technology_category,
        canonical_url=payload.official_source_url,
        download_url=None,
        mandatory_application_date=payload.effective_date,
        metadata={
            "controlled_technology_category": payload.controlled_technology_category,
            "restriction_type": payload.restriction_type,
            "destination_country": payload.destination_country,
            "licensing_requirement": payload.licensing_requirement,
            "manual_registration": True,
        },
    )
    stored_document = db.upsert_regulatory_document(document, db_path)
    version = None
    warnings: list[str] = []
    raw = file_content or (payload.content.encode("utf-8") if payload.content else None)
    if raw is not None:
        fetched = FetchedDocument(
            document=stored_document,
            content=raw,
            content_type=content_type or "text/plain",
            final_url=payload.official_source_url,
            filename=filename or "manual-regulation.txt",
            http_status=200,
        )
        previous = db.latest_document_version(stored_document.document_id, db_path)
        version, warnings = _store_new_version(fetched, previous=previous, db_path=db_path)
    export_record = db.insert_export_sector_regulation({
        "export_regulation_id": db.stable_id("exportreg", stored_document.document_id),
        "source_id": source_id,
        "authority": payload.authority,
        "jurisdiction": payload.jurisdiction,
        "controlled_technology_category": payload.controlled_technology_category,
        "restriction_type": payload.restriction_type,
        "destination_country": payload.destination_country,
        "effective_date": payload.effective_date.isoformat() if payload.effective_date else None,
        "licensing_requirement": payload.licensing_requirement,
        "official_source_url": payload.official_source_url,
        "document_id": stored_document.document_id,
        "metadata": {"uploaded": raw is not None},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }, db_path)
    return {
        "regulation": export_record,
        "document": stored_document.model_dump(mode="json"),
        "version": version.model_dump(mode="json") if version else None,
        "warnings": warnings,
    }
