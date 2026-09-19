from __future__ import annotations

import re
from datetime import date, datetime, timezone
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ... import db
from ...schemas import RegulatoryDocument
from .base import RegulatorySourceConnector


class NCAConnector(RegulatorySourceConnector):
    connector_type = "nca_html"
    allowed_hosts = frozenset({"nca.gov.sa", "www.nca.gov.sa", "cdn.nca.gov.sa"})
    index_url = "https://nca.gov.sa/ar/regulatory-documents/?documentType=controls-list"
    target_slugs = frozenset({"ecc", "cscc", "ccc", "otcc", "dcc"})

    @staticmethod
    def _parse_date(value: str) -> date | None:
        match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", value)
        if not match:
            return None
        day, month, year = map(int, match.groups())
        try:
            return date(year, month, day)
        except ValueError:
            return None

    @classmethod
    def _parse_modified(cls, text: str) -> datetime | None:
        match = re.search(r"(?:تاريخ آخر تعديل|اخر تعديل)\s*:?\s*(\d{1,2}/\d{1,2}/\d{4})", text)
        parsed = cls._parse_date(match.group(1)) if match else None
        return datetime.combine(parsed, datetime.min.time(), tzinfo=timezone.utc) if parsed else None

    @staticmethod
    def _slug(url: str) -> str:
        parts = [part for part in urlparse(url).path.split("/") if part]
        return parts[-1].lower() if parts else ""

    @staticmethod
    def _primary_pdf(soup: BeautifulSoup, title: str) -> str | None:
        candidates: list[tuple[int, str]] = []
        for anchor in soup.find_all("a", href=True):
            href = urljoin("https://nca.gov.sa", anchor["href"])
            if ".pdf" not in href.lower():
                continue
            label = " ".join(anchor.get_text(" ", strip=True).split()).casefold()
            score = 0
            if any(word in label for word in ("دليل", "guide", "أداة", "tool", "ملحق", "annex")):
                score -= 10
            if any(word in label for word in title.casefold().split() if len(word) > 4):
                score += 3
            if "controls" in href.lower() or any(code in href.lower() for code in ("ecc", "cscc", "ccc", "otcc", "dcc")):
                score += 2
            candidates.append((score, href))
        return max(candidates, default=(0, None), key=lambda item: item[0])[1]

    def _parse_detail(self, source_id: str, canonical_url: str, fallback_title: str) -> RegulatoryDocument:
        response = self._request(canonical_url)
        soup = BeautifulSoup(response.text, "html.parser")
        heading = soup.find("h1")
        title = " ".join((heading.get_text(" ", strip=True) if heading else fallback_title).split())
        text = " ".join(soup.get_text(" ", strip=True).split())
        dates = [self._parse_date(value) for value in re.findall(r"\d{1,2}/\d{1,2}/\d{4}", text)]
        publication_date = next((value for value in dates if value), None)
        download_url = self._primary_pdf(soup, title)
        slug = self._slug(canonical_url)
        return RegulatoryDocument(
            document_id=db.stable_id("regdoc", source_id, canonical_url),
            source_id=source_id,
            authority="NCA",
            jurisdiction="SA",
            regulatory_domain="Cybersecurity / Critical Systems / Cloud / Data / Operational Technology",
            title=title,
            document_type="cybersecurity_controls",
            category={
                "ecc": "Essential Cybersecurity Controls",
                "cscc": "Critical Systems Cybersecurity Controls",
                "ccc": "Cloud Cybersecurity Controls",
                "otcc": "Operational Technology Cybersecurity Controls",
                "dcc": "Data Cybersecurity Controls",
            }.get(slug, "Cybersecurity Controls"),
            canonical_url=canonical_url,
            download_url=download_url,
            publication_date=publication_date,
            last_modified_at=self._parse_modified(text),
            metadata={"slug": slug, "index_url": self.index_url, "connector": self.connector_type},
        )

    def discover(self, source_id: str) -> list[RegulatoryDocument]:
        response = self._request(self.index_url)
        soup = BeautifulSoup(response.text, "html.parser")
        found: dict[str, str] = {}
        pattern = re.compile(r"/ar/regulatory-documents/controls-list/([^/]+)/?$")
        for anchor in soup.find_all("a", href=True):
            canonical = urljoin(self.index_url, anchor["href"])
            match = pattern.search(urlparse(canonical).path)
            if not match:
                continue
            slug = match.group(1).lower()
            if slug not in self.target_slugs:
                continue
            found[canonical] = " ".join(anchor.get_text(" ", strip=True).split()) or slug.upper()
        for slug in self.target_slugs:
            canonical = f"https://nca.gov.sa/ar/regulatory-documents/controls-list/{slug}/"
            found.setdefault(canonical, slug.upper())
        return [self._parse_detail(source_id, url, title) for url, title in sorted(found.items())]
