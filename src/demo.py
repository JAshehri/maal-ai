from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from . import db
from .ingestion import register_document_version
from .schemas import CompanySnapshot, DocumentVersionCreate, Evidence, Source, SourceCreate
from .settings import settings


def seed_demo(db_path: Path | str | None = None) -> dict[str, str]:
    db.init_db(db_path)
    demo_dir = settings.root_dir / "data" / "demo"
    source_payload = SourceCreate.model_validate_json((demo_dir / "source.json").read_text(encoding="utf-8"))
    source = db.insert_source(Source(
        source_id=db.stable_id("source", source_payload.canonical_url),
        **source_payload.model_dump(),
    ), db_path)
    old_version, _, _ = register_document_version(DocumentVersionCreate(
        source_id=source.source_id,
        content=(demo_dir / "regulation_v1.txt").read_text(encoding="utf-8"),
        published_at=date(2026, 1, 1),
        effective_at=date(2026, 1, 1),
        is_simulated=True,
        simulation_notice="نسخة أساس محاكاة لأغراض العرض وليست وثيقة رسمية.",
    ), db_path=db_path)
    new_version, _, _ = register_document_version(DocumentVersionCreate(
        source_id=source.source_id,
        content=(demo_dir / "regulation_v2_simulated.txt").read_text(encoding="utf-8"),
        published_at=date(2026, 9, 17),
        effective_at=date(2026, 10, 1),
        supersedes_version_id=old_version.version_id,
        is_simulated=True,
        simulation_notice="محاكاة تغيير وليست تحديثًا رسميًا.",
    ), db_path=db_path)
    snapshot = CompanySnapshot.model_validate_json((demo_dir / "company_snapshot.json").read_text(encoding="utf-8"))
    db.insert_company_snapshot(snapshot, db_path)
    discovery_snapshot = CompanySnapshot.model_validate_json(
        (demo_dir / "sami_company_snapshot.json").read_text(encoding="utf-8")
    )
    db.insert_company_snapshot(discovery_snapshot, db_path)
    evidence_payload = json.loads((demo_dir / "evidence.json").read_text(encoding="utf-8"))
    for item in evidence_payload:
        db.insert_evidence(Evidence.model_validate(item), db_path)
    return {
        "source_id": source.source_id,
        "old_version_id": old_version.version_id,
        "new_version_id": new_version.version_id,
        "company_snapshot_id": snapshot.company_snapshot_id,
        "discovery_company_snapshot_id": discovery_snapshot.company_snapshot_id,
    }
