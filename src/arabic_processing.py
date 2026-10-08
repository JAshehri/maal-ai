"""وحدة المعالجة المتقدمة للغة العربية والترقيم القانوني لمشروع مآل.

تطبق هذه الوحدة مبدأ الحفاظ الصارم على النص الخام (raw_text) كدليل قانوني غير قابل للتشويه،
مع توليد نص معياري موحد (normalized_text) لأغراض الفهرسة والبحث والمقارنة الحتمية.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any


# 1. جداول تحويل الأرقام الهندية/المشرقية إلى لاتينية
EASTERN_ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
WESTERN_DIGITS = "0123456789"

DIGIT_TRANS = str.maketrans(
    EASTERN_ARABIC_DIGITS + PERSIAN_DIGITS,
    WESTERN_DIGITS * 2,
)

# 2. حركات التشكيل والتطويل وعلامات الترقيم العربية
DIACRITICS_PATTERN = re.compile(
    r"[\u064B-\u0652\u0653-\u0655\u0670\u0640]"  # تنوين، حركات، شدة، ألف خنجرية، تطويل (كشيدة)
)

ARABIC_PUNCTUATION_TRANS = str.maketrans({
    "،": ",",
    "؛": ";",
    "؟": "?",
    "«": '"',
    "»": '"',
    "“": '"',
    "”": '"',
    "‘": "'",
    "’": "'",
    "–": "-",
    "—": "-",
})

# 3. الأرقام الترتيبية العربية للمواد القانونية
ARABIC_ORDINAL_MAP: dict[str, int] = {
    "الاولى": 1,
    "الاول": 1,
    "الثانية": 2,
    "الثاني": 2,
    "الثالثة": 3,
    "الثالث": 3,
    "الرابعة": 4,
    "الرابع": 4,
    "الخامسة": 5,
    "الخامس": 5,
    "السادسة": 6,
    "السادس": 6,
    "السابعة": 7,
    "السابع": 7,
    "الثامنة": 8,
    "الثامن": 8,
    "التاسعة": 9,
    "التاسع": 9,
    "العاشرة": 10,
    "العاشر": 10,
    "الحادية عشرة": 11,
    "الحادي عشر": 11,
    "الثانية عشرة": 12,
    "الثاني عشر": 12,
    "الثالثة عشرة": 13,
    "الثالث عشر": 13,
    "الرابعة عشرة": 14,
    "الرابع عشر": 14,
    "الخامسة عشرة": 15,
    "الخامس عشر": 15,
    "السادسة عشرة": 16,
    "السادس عشر": 16,
    "السابعة عشرة": 17,
    "السابع عشر": 17,
    "الثامنة عشرة": 18,
    "الثامن عشر": 18,
    "التاسعة عشرة": 19,
    "التاسع عشر": 19,
    "العشرون": 20,
    "العشرين": 20,
    "الحادية والعشرون": 21,
    "الثانية والعشرون": 22,
    "الثلاثون": 30,
    "الاربعون": 40,
    "الخمسون": 50,
}

# بنود الترقيم الترتيبي الفقهي والقانوني
ORDINAL_CLAUSE_MAP: dict[str, int] = {
    "اولا": 1,
    "ثانيا": 2,
    "ثالثا": 3,
    "رابعا": 4,
    "خامسا": 5,
    "سادسا": 6,
    "سابعا": 7,
    "ثامنا": 8,
    "تاسعا": 9,
    "عاشرا": 10,
}


@dataclass(frozen=True)
class ProcessedArabicText:
    raw_text: str
    normalized_text: str
    language: str
    tokens: list[str]


def convert_hindi_digits_to_ascii(text: str) -> str:
    """تحويل الأرقام الهندية/المشرقية والفارسية إلى أرقام ASCII قياسية."""
    return text.translate(DIGIT_TRANS)


def strip_tashkeel_and_tatweel(text: str) -> str:
    """إزالة علامات التشكيل والتطويل (الكشيدة) دون المساس بحروف الكلمات الأصلية."""
    return DIACRITICS_PATTERN.sub("", text)


def normalize_arabic_letters(text: str) -> str:
    """توحيد أشكال الحروف العربية (الهمزات، الياء/الألف المقصورة، التاء المربوطة).

    ملاحظة: هذا التطبيع يُجرى فقط على normalized_text لأغراض الفهرسة والبحث،
    ولا يُطبق أبداً على raw_text المحفوظ كحجة قانونية.
    """
    # 1. إزالة التشكيل والتطويل
    cleaned = strip_tashkeel_and_tatweel(text)
    # 2. تحويل الأرقام الهندية
    cleaned = convert_hindi_digits_to_ascii(cleaned)
    # 3. توحيد علامات الترقيم
    cleaned = cleaned.translate(ARABIC_PUNCTUATION_TRANS)
    # 4. توحيد الهمزات: أ، إ، آ، ء $\rightarrow$ ا
    cleaned = re.sub(r"[إأآٱ]", "ا", cleaned)
    # 5. توحيد الياء والألف المقصورة: ى $\rightarrow$ ي
    cleaned = re.sub(r"ى", "ي", cleaned)
    # 6. توحيد التاء المربوطة: ة $\rightarrow$ ه (للبحث غير الحساس للرسم)
    cleaned = re.sub(r"ة", "ه", cleaned)
    # 7. توحيد المسافات
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def detect_language(text: str) -> str:
    """اكتشاف لغة النص (عربية ar، إنجليزية en، أو مختلطة mixed)."""
    has_arabic = bool(re.search(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]", text))
    has_latin = bool(re.search(r"[A-Za-z]", text))
    if has_arabic and has_latin:
        return "mixed"
    if has_arabic:
        return "ar"
    if has_latin:
        return "en"
    return "unknown"


def process_text(text: str) -> ProcessedArabicText:
    """معالجة النص وتوليد الزوج القانوني (raw_text + normalized_text) مع تصنيف اللغة."""
    raw = text.strip()
    normalized = normalize_arabic_letters(raw)
    lang = detect_language(raw)
    # استخراج الكلمات المعيارية المفتاحية
    tokens = [t for t in re.findall(r"[\w.-]+", normalized.casefold()) if len(t) > 1]
    return ProcessedArabicText(
        raw_text=raw,
        normalized_text=normalized,
        language=lang,
        tokens=tokens,
    )


def extract_numbers_all_scripts(text: str | None) -> list[float]:
    """استخراج جميع الأرقام من النص سواء كانت بأرقام لاتينية (0-9) أو هندية (٠-٩)."""
    if not text:
        return []
    # تحويل الأرقام الهندية أولاً
    converted = convert_hindi_digits_to_ascii(text)
    # مطابقة الأرقام العشرية والصحيحة والسالبة
    matches = re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?", converted)
    numbers = []
    for m in matches:
        try:
            numbers.append(float(m))
        except ValueError:
            pass
    return numbers


# النمط الشامل لاكتشاف عناوين المواد والفقرات القانونية باللغتين العربية والإنجليزية
ARABIC_LEGAL_ARTICLE_PATTERN = re.compile(
    r"^(?P<prefix>"
    r"(?:المادة|مادة|البند|بند|الفقرة|فقرة|القسم|قسم|Article|Section|Clause)\s*"
    r"(?:\((?P<paren_num>[\d٠-٩.-]+)\)|(?P<direct_num>[\d٠-٩.-]+)|(?P<ordinal>[\w\s]+))"
    r"|"
    r"(?P<clause_ordinal>أولاً|ثانياً|ثالثاً|رابعاً|خامساً|سادساً|سابعاً|ثامناً|تاسعاً|عاشراً)"
    r"|"
    r"(?P<letter_bullet>[أ-يa-zA-Z]\))"
    r")"
    r"(?:\s*[-–—:]\s*|\s+|$)(?P<body>.*)$",
    re.IGNORECASE | re.MULTILINE,
)


def extract_canonical_article_number(article_ref: str) -> str:
    """استخراج المعرف المعياري للمادة القانونية لضمان المطابقة بين مختلف صيغ الترقيم.

    أمثلة:
    - 'المادة (٥)' -> '5'
    - 'المادة الخامسة' -> '5'
    - 'المادة 5.1' -> '5.1'
    - 'Article 5' -> '5'
    - 'أولاً' -> '1'
    """
    cleaned = convert_hindi_digits_to_ascii(article_ref.strip())
    # 1. إذا وجد رقم صريح (مثل 5 أو 5.1)
    num_match = re.search(r"\b(\d+(?:\.\d+)?)\b", cleaned)
    if num_match:
        return num_match.group(1)

    # 2. فحص الأقواس: المادة (5)
    paren_match = re.search(r"\(([\d.]+)\)", cleaned)
    if paren_match:
        return paren_match.group(1)

    # 3. فحص الأرقام الترتيبية: المادة الخامسة
    norm = normalize_arabic_letters(cleaned)
    for word, number in ARABIC_ORDINAL_MAP.items():
        if word in norm:
            return str(number)

    for word, number in ORDINAL_CLAUSE_MAP.items():
        if word in norm:
            return str(number)

    return article_ref.strip()


def are_articles_equivalent(ref1: str, ref2: str) -> bool:
    """مقارنة حتمية تفحص ما إذا كانت إشارتان لمادتين قانونيتين تشيران إلى المادة نفسها.

    يدعم المقارنة بين:
    - 'المادة الخامسة' و 'المادة 5'
    - 'المادة (٥)' و 'Article 5'
    - 'المادة 5.1' و 'Article 5.1'
    """
    if not ref1 or not ref2:
        return False
    # مطابقة متطابقة مباشرة
    if ref1.casefold() == ref2.casefold():
        return True
    c1 = extract_canonical_article_number(ref1)
    c2 = extract_canonical_article_number(ref2)
    if c1 and c2 and c1 == c2:
        return True
    # مطابقة بعد التطبيع العربي
    return normalize_arabic_letters(ref1).casefold() == normalize_arabic_letters(ref2).casefold()
