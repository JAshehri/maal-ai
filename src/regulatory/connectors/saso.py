from __future__ import annotations

import re
from datetime import date
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ... import db
from ...schemas import RegulatoryDocument
from .base import RegulatorySourceConnector


class SASOConnector(RegulatorySourceConnector):
    connector_type = "saso_html"
    allowed_hosts = frozenset({"saso.gov.sa", "www.saso.gov.sa"})
    index_url = "https://www.saso.gov.sa/ar/Laws-And-Regulations/technical_regulations/Pages/default.aspx"

    @staticmethod
    def _clean(value: str) -> str:
        return " ".join(value.replace("\u200b", "").replace("\ufeff", "").split())

    @classmethod
    def _date_after(cls, text: str, label: str) -> date | None:
        match = re.search(rf"{re.escape(label)}\s*:?\s*(\d{{1,2}}/\d{{1,2}}/\d{{4}})", cls._clean(text))
        if not match:
            return None
        day, month, year = map(int, match.group(1).split("/"))
        try:
            return date(year, month, day)
        except ValueError:
            return None

    @staticmethod
    def _category(title: str, href: str) -> str:
        value = f"{title} {href}".casefold()
        categories = [
            ("Electrical", ("كهرب", "إلكترون", "electr", "electromagnetic", "communications", "تقنية المعلومات")),
            ("Mechanical", ("ميكاني", "آلة", "آلات", "machin", "مركب", "vehicle", "معدات", "equipment", "صهاريج")),
            ("Construction", ("بناء", "تشييد", "building", "construction", "أسمنت", "خرسانة")),
            ("Chemical", ("كيمي", "chemical", "منظفات", "دهان")),
            ("Textile", ("نسيج", "غزل", "textile")),
            ("Services", ("خدمات", "service", "مطابقة", "conformity")),
        ]
        for category, tokens in categories:
            if any(token in value for token in tokens):
                return category
        return "Other"

    def _expand_page_size(self, response_text: str) -> str:
        soup = BeautifulSoup(response_text, "html.parser")
        select = soup.find("select", id=lambda value: value and value.endswith("DDL_PageSize"))
        if not select or not select.get("name"):
            return response_text
        payload = {
            item.get("name"): item.get("value", "")
            for item in soup.find_all("input")
            if item.get("name")
        }
        payload["__EVENTTARGET"] = select["name"]
        payload["__EVENTARGUMENT"] = ""
        payload[select["name"]] = "100"
        expanded = self._post_form(self.index_url, payload)
        expanded.encoding = "utf-8"
        return expanded.text

    def discover(self, source_id: str) -> list[RegulatoryDocument]:
        response = self._request(self.index_url)
        response.encoding = "utf-8"
        text = self._expand_page_size(response.text)
        soup = BeautifulSoup(text, "html.parser")
        documents: list[RegulatoryDocument] = []
        seen: set[str] = set()
        for anchor in soup.select("a.rulesAndRegulationsListItem[href]"):
            download_url = urljoin(self.index_url, anchor["href"])
            if download_url in seen:
                continue
            seen.add(download_url)
            heading = anchor.find("h2")
            title = self._clean(heading.get_text(" ", strip=True) if heading else anchor.get_text(" ", strip=True))
            details = self._clean(anchor.get_text(" ", strip=True))
            category = self._category(title, download_url)
            documents.append(RegulatoryDocument(
                document_id=db.stable_id("regdoc", source_id, download_url),
                source_id=source_id,
                authority="SASO",
                jurisdiction="SA",
                regulatory_domain="Product Standards / Technical Regulations / Conformity",
                title=title,
                document_type="technical_regulation",
                category=category,
                canonical_url=download_url,
                download_url=download_url,
                publication_date=self._date_after(details, "تاريخ النشر"),
                approval_date=self._date_after(details, "تاريخ الاعتماد"),
                mandatory_application_date=self._date_after(details, "التطبيق الإلزامي"),
                metadata={"index_url": self.index_url, "connector": self.connector_type, "category_inferred": True},
            ))
        return documents
