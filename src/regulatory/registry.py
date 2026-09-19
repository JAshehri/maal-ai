from __future__ import annotations

from pathlib import Path

from .. import db
from ..schemas import Source, SourceCreate, SourceQuality
from .connectors import NCAConnector, SASOConnector
from .connectors.base import RegulatorySourceConnector


NCA_URL = "https://nca.gov.sa/ar/regulatory-documents/?documentType=controls-list"
SASO_URL = "https://www.saso.gov.sa/ar/Laws-And-Regulations/technical_regulations/Pages/default.aspx"


def seed_regulatory_sources(db_path: Path | str | None = None) -> dict[str, str]:
    definitions = [
        SourceCreate(
            authority="NCA", jurisdiction="SA", title="NCA Regulatory Documents",
            canonical_url=NCA_URL, regulatory_domain="Cybersecurity / Critical Systems / Cloud / Data / Operational Technology",
            connector_type="nca_html", document_types=["cybersecurity_controls"],
            source_quality=SourceQuality.official_approved,
            fetch_config={"official_hosts": ["nca.gov.sa", "cdn.nca.gov.sa"]},
        ),
        SourceCreate(
            authority="SASO", jurisdiction="SA", title="SASO Technical Regulations",
            canonical_url=SASO_URL, regulatory_domain="Product Standards / Technical Regulations / Conformity",
            connector_type="saso_html", document_types=["technical_regulation"],
            source_quality=SourceQuality.official_approved,
            fetch_config={"official_hosts": ["www.saso.gov.sa"]},
        ),
        SourceCreate(
            authority="Manual Export/Sector Source", jurisdiction="MULTI", title="Manual Export and Sector Regulations",
            canonical_url="manual://export-sector-regulations", regulatory_domain="Export Control / Sector Regulations",
            connector_type="manual_export_sector", document_types=["export_control", "sector_regulation"],
            source_quality=SourceQuality.approved_copy,
            fetch_config={"automatic_fetch": False},
        ),
    ]
    result = {}
    for definition in definitions:
        source = Source(source_id=db.stable_id("source", definition.canonical_url), **definition.model_dump())
        result[source.authority] = db.insert_source(source, db_path).source_id
    return result


def connector_for_source(
    source: dict, *, transport=None
) -> RegulatorySourceConnector:
    connector_type = source.get("connector_type")
    if connector_type == "nca_html":
        return NCAConnector(transport=transport)
    if connector_type == "saso_html":
        return SASOConnector(transport=transport)
    raise ValueError(f"source connector is not automatically scannable: {connector_type}")
