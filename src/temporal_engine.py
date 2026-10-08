"""محرك الذكاء الزمني وتاريخ اللوائح (Temporal Regulatory Intelligence Engine) لمشروع مآل.

يدعم:
1. قراءة وتحليل التواريخ الميلادية والهجرية المكتوبة بالعربية والإنجليزية وبالأرقام الهندية.
2. تتبع دورة الحياة القانونية للتشريعات عبر الزمن (draft, published, effective, superseded, repealed, expired).
3. تقييم الانطباق الزمني بتاريخ محدد (as_of_date) ومراعاة فترات السماح وتوفيق الأوضاع (Transition/Grace Periods).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .arabic_processing import convert_hindi_digits_to_ascii, normalize_arabic_letters


# أشهر السنة الميلادية بالعربية (المشرق والمغرب والخليج)
GREGORIAN_MONTHS: dict[str, int] = {
    "يناير": 1, "كانون الثاني": 1, "جانفي": 1,
    "فبراير": 2, "شباط": 2, "فيفري": 2,
    "مارس": 3, "آذار": 3, "اذار": 3,
    "أبريل": 4, "ابريل": 4, "نيسان": 4, "افريل": 4,
    "مايو": 5, "أيار": 5, "ايار": 5,
    "يونيو": 6, "حزيران": 6, "جوان": 6,
    "يوليو": 7, "تموز": 7, "جويلية": 7,
    "أغسطس": 8, "اغسطس": 8, "آب": 8, "اب": 8, "اوت": 8,
    "سبتمبر": 9, "أيلول": 9, "ايلول": 9,
    "أكتوبر": 10, "اكتوبر": 10, "تشرين الأول": 10, "تشرين الاول": 10,
    "نوفمبر": 11, "تشرين الثاني": 11,
    "ديسمبر": 12, "كانون الأول": 12, "كانون الاول": 12,
}

# أشهر السنة الهجرية
HIJRI_MONTHS: dict[str, int] = {
    "محرم": 1, "المحرم": 1,
    "صفر": 2,
    "ربيع الأول": 3, "ربيع الاول": 3, "ربيع 1": 3,
    "ربيع الثاني": 4, "ربيع الآخر": 4, "ربيع الاخر": 4, "ربيع 2": 4,
    "جمادى الأولى": 5, "جمادى الاول": 5, "جمادى 1": 5,
    "جمادى الآخرة": 6, "جمادى الثانية": 6, "جمادى الاخر": 6, "جمادى 2": 6,
    "رجب": 7,
    "شعبان": 8,
    "رمضان": 9,
    "شوال": 10,
    "ذو القعدة": 11, "ذي القعدة": 11,
    "ذو الحجة": 12, "ذي الحجة": 12,
}


@dataclass(frozen=True)
class ParsedDateResult:
    original_text: str
    calendar_type: str  # 'gregorian' | 'hijri' | 'unknown'
    parsed_date: date | None
    conversion_confidence: float  # 0.0 to 1.0
    notes: str = ""


def hijri_to_gregorian(year: int, month: int, day: int) -> date:
    """تحويل التاريخ الهجري إلى تاريخ ميلادي مكافئ باستخدام الخوارزمية الفلكية المعيارية المعتمدة.

    Methodology: Tabular Islamic Calendar (Kuwaiti Algorithm approximation).
    Julian Day Number computation and astronomical conversion.
    """
    # حساب اليوم اليولياني (Julian Day Number) للتاريخ الهجري
    jd = math.floor((11 * year + 3) / 30) + 354 * year + 30 * month - math.floor((month - 1) / 2) + day + 1948440 - 385

    # تحويل اليوم اليولياني إلى تاريخ ميلادي
    l = jd + 68569
    n = math.floor((4 * l) / 146097)
    l = l - math.floor((146097 * n + 3) / 4)
    i = math.floor((4000 * (l + 1)) / 1461001)
    l = l - math.floor((1461 * i) / 4) + 31
    j = math.floor((80 * l) / 2447)
    d = l - math.floor((2447 * j) / 80)
    l = math.floor(j / 11)
    m = j + 2 - 12 * l
    y = 100 * (n - 49) + i + l
    return date(int(y), int(m), int(d))


def parse_date_string(raw_text: str | None) -> ParsedDateResult:
    """محلل شامل للتواريخ العربية والميلادية والهجرية بشتى التنسيقات."""
    if not raw_text or not raw_text.strip():
        return ParsedDateResult("", "unknown", None, 0.0, "Empty date input")

    original = raw_text.strip()
    # تحويل الأرقام الهندية وإزالة التشكيل
    ascii_text = convert_hindi_digits_to_ascii(original)
    norm_text = normalize_arabic_letters(ascii_text)

    # 1. التنسيق القياسي ISO: YYYY-MM-DD
    iso_match = re.search(r"\b(19\d\d|20\d\d)-(0?[1-9]|1[0-2])-(0?[1-9]|[12]\d|3[01])\b", ascii_text)
    if iso_match:
        y, m, d = int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3))
        try:
            return ParsedDateResult(original, "gregorian", date(y, m, d), 1.0, "ISO format")
        except ValueError:
            pass

    # 2. فحص التاريخ الهجري الصريح (بالأشهر الهجرية)
    for month_name, month_num in HIJRI_MONTHS.items():
        pattern = rf"\b(0?[1-9]|[12]\d|30)\s+(?:من\s+)?{re.escape(month_name)}\s+(?:عام\s+|سنة\s+)?(1[34]\d\d)\b"
        match = re.search(pattern, norm_text)
        if match:
            day, year = int(match.group(1)), int(match.group(2))
            try:
                greg_date = hijri_to_gregorian(year, month_num, day)
                return ParsedDateResult(original, "hijri", greg_date, 0.95, f"Hijri text: {year}-{month_num:02d}-{day:02d}")
            except Exception as e:
                return ParsedDateResult(original, "hijri", None, 0.5, f"Hijri conversion error: {e}")

    # 3. فحص التاريخ الميلادي بالاسم العربي للشهر (مثل: 15 سبتمبر 2026)
    for month_name, month_num in GREGORIAN_MONTHS.items():
        pattern = rf"\b(0?[1-9]|[12]\d|3[01])\s+(?:من\s+)?{re.escape(month_name)}\s+(?:عام\s+|سنة\s+)?(19\d\d|20\d\d)\b"
        match = re.search(pattern, norm_text)
        if match:
            day, year = int(match.group(1)), int(match.group(2))
            try:
                return ParsedDateResult(original, "gregorian", date(year, month_num, day), 1.0, "Arabic textual Gregorian")
            except ValueError:
                pass

    # 4. التنسيق الرقمي الهجري مع علامة هـ (مثال: 1446/05/15هـ أو 15/05/1446هـ)
    hijri_num_match = re.search(r"\b(1[34]\d\d)/(0?[1-9]|1[0-2])/(0?[1-9]|[12]\d|30)\s*(?:هـ|ه|H)?\b", ascii_text)
    if hijri_num_match:
        y, m, d = int(hijri_num_match.group(1)), int(hijri_num_match.group(2)), int(hijri_num_match.group(3))
        try:
            greg = hijri_to_gregorian(y, m, d)
            return ParsedDateResult(original, "hijri", greg, 0.95, "Numeric Hijri Y/M/D")
        except Exception:
            pass

    hijri_num_rev = re.search(r"\b(0?[1-9]|[12]\d|30)/(0?[1-9]|1[0-2])/(1[34]\d\d)\s*(?:هـ|ه|H)\b", ascii_text)
    if hijri_num_rev:
        d, m, y = int(hijri_num_rev.group(1)), int(hijri_num_rev.group(2)), int(hijri_num_rev.group(3))
        try:
            greg = hijri_to_gregorian(y, m, d)
            return ParsedDateResult(original, "hijri", greg, 0.95, "Numeric Hijri D/M/Y")
        except Exception:
            pass

    # 5. التنسيق الرقمي الميلادي الشائع: DD/MM/YYYY
    dmy_match = re.search(r"\b(0?[1-9]|[12]\d|3[01])/(0?[1-9]|1[0-2])/(19\d\d|20\d\d)\b", ascii_text)
    if dmy_match:
        d, m, y = int(dmy_match.group(1)), int(dmy_match.group(2)), int(dmy_match.group(3))
        try:
            return ParsedDateResult(original, "gregorian", date(y, m, d), 0.95, "Numeric Gregorian D/M/Y")
        except ValueError:
            pass

    return ParsedDateResult(original, "unknown", None, 0.0, "Unrecognized date pattern")


@dataclass(frozen=True)
class TemporalEvaluation:
    is_applicable: bool
    lifecycle_status: str  # currently_effective, upcoming_requirement, transition_period, past_due, repealed, expired, not_yet_published
    human_status_ar: str
    effective_date: date | None
    days_until_effective: int | None
    is_grace_period: bool
    rationale: str


def evaluate_temporal_status(
    *,
    publication_date: date | None,
    effective_date: date | None,
    repealed_date: date | None = None,
    legal_status: str = "effective",
    grace_period_days: int = 0,
    as_of_date: date | None = None,
) -> TemporalEvaluation:
    """تقييم الوضع الزمني للائحة أو التزام تنظيمي في تاريخ محدد (as_of_date).

    مبدأ جوهري:
    لا يُصنف عدم الامتثال كمخالفة إذا كان التشريع في فترة سماح أو لم يدخل حيز النفاذ في التاريخ المعني.
    """
    eval_date = as_of_date or datetime.now(timezone.utc).date()

    # 1. إذا كان ملغى قبل تاريخ التقييم
    if repealed_date and eval_date >= repealed_date:
        return TemporalEvaluation(
            is_applicable=False,
            lifecycle_status="repealed",
            human_status_ar="ملغى",
            effective_date=effective_date,
            days_until_effective=None,
            is_grace_period=False,
            rationale=f"التشريع ملغى منذ {repealed_date.isoformat()}، وتاريخ الفحص هو {eval_date.isoformat()}.",
        )

    if legal_status == "repealed":
        return TemporalEvaluation(
            is_applicable=False,
            lifecycle_status="repealed",
            human_status_ar="ملغى",
            effective_date=effective_date,
            days_until_effective=None,
            is_grace_period=False,
            rationale="التشريع مصنف كملغى رسمياً.",
        )

    # 2. إذا كان تاريخ الفحص يسبق تاريخ النشر
    if publication_date and eval_date < publication_date:
        return TemporalEvaluation(
            is_applicable=False,
            lifecycle_status="not_yet_published",
            human_status_ar="غير منشور بعد",
            effective_date=effective_date,
            days_until_effective=None,
            is_grace_period=False,
            rationale=f"التشريع نُشر في {publication_date.isoformat()}، بينما تاريخ الفحص المطلوب هو {eval_date.isoformat()}.",
        )

    # 3. إذا كان التشريع منشوراً ولكن تاريخ النفاذ في المستقبل بالنسبة لتاريخ الفحص
    if effective_date and eval_date < effective_date:
        delta_days = (effective_date - eval_date).days
        is_grace = grace_period_days > 0 or (publication_date and effective_date > publication_date)
        status_code = "transition_period" if is_grace else "upcoming_requirement"
        status_label = "فترة توفيق أوضاع (مهلة سماح)" if is_grace else "متطلب تنظيمي قادم"
        return TemporalEvaluation(
            is_applicable=False,  # ليس ملزماً بشكل قاطع حتى الآن
            lifecycle_status=status_code,
            human_status_ar=status_label,
            effective_date=effective_date,
            days_until_effective=delta_days,
            is_grace_period=is_grace,
            rationale=f"التشريع يصبح نافذاً في {effective_date.isoformat()} (متبقي {delta_days} يوماً). المنشأة في فترة انتقالية ولا تعتبر مخالفة حالياً.",
        )

    # 4. إذا تجاوز تاريخ النفاذ، فهو نافذ وملزم في تاريخ الفحص
    return TemporalEvaluation(
        is_applicable=True,
        lifecycle_status="currently_effective",
        human_status_ar="نافذ وسارٍ",
        effective_date=effective_date,
        days_until_effective=0,
        is_grace_period=False,
        rationale=f"التشريع نافذ وملزم قانونياً في تاريخ التقييم {eval_date.isoformat()}.",
    )
