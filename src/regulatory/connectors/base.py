from __future__ import annotations

import time
from abc import ABC, abstractmethod
from pathlib import PurePosixPath
from urllib.parse import urlparse

import httpx

from ...schemas import FetchedDocument, RegulatoryDocument
from ...settings import settings


class ConnectorError(RuntimeError):
    pass


class ConnectorSecurityError(ConnectorError):
    pass


class RegulatorySourceConnector(ABC):
    connector_type: str
    allowed_hosts: frozenset[str]

    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        self._transport = transport

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or (parsed.hostname or "").lower() not in self.allowed_hosts:
            raise ConnectorSecurityError(f"connector refused non-official URL: {url}")

    def _request(self, url: str) -> httpx.Response:
        self._validate_url(url)
        error: Exception | None = None
        for attempt in range(settings.connector_max_retries + 1):
            try:
                with httpx.Client(
                    timeout=settings.connector_timeout_seconds,
                    follow_redirects=True,
                    transport=self._transport,
                    headers={"User-Agent": settings.connector_user_agent, "Accept": "*/*"},
                ) as client:
                    response = client.get(url)
                self._validate_url(str(response.url))
                response.raise_for_status()
                content_length = int(response.headers.get("content-length", "0") or 0)
                if content_length > settings.max_regulatory_document_bytes:
                    raise ConnectorError("regulatory document exceeds configured size limit")
                if len(response.content) > settings.max_regulatory_document_bytes:
                    raise ConnectorError("regulatory document exceeds configured size limit")
                return response
            except (httpx.HTTPError, ConnectorError) as exc:
                error = exc
                if attempt >= settings.connector_max_retries:
                    break
                time.sleep(0.25 * (2 ** attempt))
        raise ConnectorError(f"fetch failed for {url}: {type(error).__name__}") from error

    def _post_form(self, url: str, data: dict[str, str]) -> httpx.Response:
        self._validate_url(url)
        try:
            with httpx.Client(
                timeout=settings.connector_timeout_seconds,
                follow_redirects=True,
                transport=self._transport,
                headers={"User-Agent": settings.connector_user_agent, "Accept": "text/html"},
            ) as client:
                response = client.post(url, data=data)
            self._validate_url(str(response.url))
            response.raise_for_status()
            if len(response.content) > settings.max_regulatory_document_bytes:
                raise ConnectorError("source index exceeds configured size limit")
            return response
        except httpx.HTTPError as exc:
            raise ConnectorError(f"form fetch failed for {url}: {type(exc).__name__}") from exc

    @staticmethod
    def _filename(url: str, content_type: str) -> str:
        name = PurePosixPath(urlparse(url).path).name or "document"
        if "." not in name:
            if "pdf" in content_type:
                name += ".pdf"
            elif "html" in content_type:
                name += ".html"
            else:
                name += ".bin"
        return name[:180]

    @abstractmethod
    def discover(self, source_id: str) -> list[RegulatoryDocument]:
        raise NotImplementedError

    def fetch_document(self, document: RegulatoryDocument) -> FetchedDocument:
        url = document.download_url or document.canonical_url
        response = self._request(url)
        content_type = response.headers.get("content-type", "application/octet-stream").split(";", 1)[0]
        return FetchedDocument(
            document=document,
            content=response.content,
            content_type=content_type,
            final_url=str(response.url),
            filename=self._filename(str(response.url), content_type),
            http_status=response.status_code,
            etag=response.headers.get("etag"),
            last_modified_header=response.headers.get("last-modified"),
        )
