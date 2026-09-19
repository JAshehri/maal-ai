from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..schemas import CompanySnapshot, RegulatoryDocument


@dataclass(frozen=True)
class DiscoveryApplicability:
    status: str
    rationale: str
    department_ids: list[str]
    priority: str


def _company_text(snapshot: CompanySnapshot) -> str:
    tokens: list[str] = [snapshot.name, snapshot.jurisdiction, *snapshot.activities]

    def collect(value: Any, key: str = "") -> None:
        if value is None or value is False:
            return
        if value is True:
            tokens.append(key)
        elif isinstance(value, dict):
            for child_key, child in value.items():
                collect(child, str(child_key))
        elif isinstance(value, list):
            for child in value:
                collect(child, key)
        else:
            tokens.append(str(value))

    collect(snapshot.assets)
    collect(snapshot.policies)
    collect(snapshot.permits)
    collect(snapshot.attributes)
    return " ".join(tokens).casefold()


def classify_discovered_document(
    document: RegulatoryDocument, snapshot: CompanySnapshot
) -> DiscoveryApplicability:
    company = _company_text(snapshot)
    title = f"{document.title} {document.category or ''}".casefold()
    if document.authority == "NCA":
        departments = ["Cybersecurity", "IT", "Legal"]
        conditions = {
            "Essential Cybersecurity Controls": ("cybersecurity", "information system", "data", "تقني", "بيانات"),
            "Critical Systems Cybersecurity Controls": ("critical", "حساس", "بنية تحتية حرجة"),
            "Cloud Cybersecurity Controls": ("cloud", "سحاب"),
            "Operational Technology Cybersecurity Controls": ("operational technology", "ot", "ics", "manufactur", "تصنيع"),
            "Data Cybersecurity Controls": ("data", "بيانات", "privacy", "خصوص"),
        }
        required = conditions.get(document.category or "")
        if required and not any(token in company for token in required):
            return DiscoveryApplicability(
                "needs_review",
                f"وثيقة NCA رسمية، لكن ملف المنشأة لا يثبت شرط {document.category} بما يكفي.",
                departments,
                "pending_review",
            )
        return DiscoveryApplicability(
            "applicable" if required else "potentially_applicable",
            "المنشأة سعودية ونشاطها التقني/الصناعي يتقاطع مع نطاق وثيقة NCA، مع بقاء الحكم التفصيلي للمواد.",
            departments + (["Engineering"] if document.category == "Operational Technology Cybersecurity Controls" else []),
            "high" if document.category in {"Critical Systems Cybersecurity Controls", "Operational Technology Cybersecurity Controls"} else "medium",
        )
    if document.authority == "SASO":
        company_relevant = any(token in company for token in (
            "advanced electronics", "embedded", "manufactur", "procurement", "quality",
            "إلكترون", "أنظمة مدمجة", "تصنيع", "مشتريات", "جودة",
        ))
        relevant_category = document.category in {"Electrical", "Mechanical", "Services"}
        departments = {
            "Electrical": ["Engineering", "Quality", "Procurement"],
            "Mechanical": ["Engineering", "Quality", "Procurement"],
            "Services": ["Quality", "Legal", "Procurement"],
        }.get(document.category or "", ["Legal", "Quality"])
        if company_relevant and relevant_category:
            # Category alone is not evidence of product scope.  Keep this list
            # intentionally narrow for the synthetic advanced-electronics profile;
            # generic vehicles, tanks and machinery must not enter impact analysis.
            direct_keywords = (
                "إلكترون", "electronic", "كهربائ", "electrical", "اتصالات",
                "information technology", "تقنية المعلومات", "كهرومغناط",
                "electromagnetic", "بطاريات", "batter", "مراكم", "خلايا",
                "semiconductor", "أشباه الموصلات", "مكونات إلكترونية",
            )
            product_scope_exclusions = (
                "مركب", "vehicle", "سكوتر", "scooter", "مصاعد", "elevator",
                "مواد البناء", "أنابيب", "pipe", "تدخين", "smoking",
                "لعب", "amusement", "عربات", "stroller",
            )
            direct = (
                any(token in title for token in direct_keywords)
                and not any(token in title for token in product_scope_exclusions)
            )
            if not direct:
                return DiscoveryApplicability(
                    "needs_review",
                    "الفئة قد تتقاطع مع نشاط المنشأة، لكن ملفها لا يثبت تصنيع أو استيراد المنتج المحدد في هذه اللائحة.",
                    departments,
                    "pending_review",
                )
            return DiscoveryApplicability(
                "applicable",
                "عنوان اللائحة مرتبط مباشرة بالإلكترونيات أو الأجهزة أو المكونات المذكورة في ملف المنشأة التجريبي.",
                departments,
                "high" if document.category == "Electrical" else "medium",
            )
        return DiscoveryApplicability(
            "not_applicable",
            "لا توجد في ملف المنشأة الحالي أنشطة أو منتجات تثبت ارتباط هذه الفئة الفنية؛ حُفظ سبب الاستبعاد.",
            departments,
            "low",
        )
    return DiscoveryApplicability(
        "needs_review", "المصدر اليدوي يحتاج حقائق نطاق إضافية قبل الحكم.", ["Legal"], "pending_review"
    )
