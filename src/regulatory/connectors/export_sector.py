from __future__ import annotations

from abc import ABC

from ...schemas import RegulatoryDocument
from .base import RegulatorySourceConnector


class ExportSectorRegulationConnector(RegulatorySourceConnector, ABC):
    """Extension point for future official export/import and sector sources.

    Implementations must expose authority, jurisdiction, controlled technology,
    restriction direction, destination, effective date, licensing requirement,
    and an official canonical URL through RegulatoryDocument.metadata.
    """

    connector_type = "export_sector"


class ManualExportSectorConnector(ExportSectorRegulationConnector):
    connector_type = "manual_export_sector"
    allowed_hosts = frozenset()

    def __init__(self, documents: list[RegulatoryDocument] | None = None) -> None:
        super().__init__()
        self._documents = documents or []

    def discover(self, source_id: str) -> list[RegulatoryDocument]:
        return [item for item in self._documents if item.source_id == source_id]

    def fetch_document(self, document: RegulatoryDocument):  # pragma: no cover - explicit safety boundary
        raise NotImplementedError(
            "manual export-sector documents are ingested through the authenticated upload endpoint; "
            "the connector does not fetch arbitrary URLs"
        )
