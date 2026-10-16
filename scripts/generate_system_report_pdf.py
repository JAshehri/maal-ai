from __future__ import annotations

from pathlib import Path

import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "pdf" / "Maal_Full_System_Report_AR.pdf"
FONT_REGULAR = Path("C:/Windows/Fonts/arial.ttf")
FONT_BOLD = Path("C:/Windows/Fonts/arialbd.ttf")

NAVY = HexColor("#153826")
NAVY_DARK = HexColor("#0E241A")
GOLD = HexColor("#AD8A4E")
SAGE = HexColor("#7C9484")
IVORY = HexColor("#F7F5EF")
PALE_GREEN = HexColor("#EDF3EF")
PALE_AMBER = HexColor("#F7F0E2")
RED = HexColor("#A83B40")
SLATE = HexColor("#4B4A42")
MUTED = HexColor("#6D746E")
LINE = HexColor("#DFE3DC")


def rtl(text: str) -> str:
    return get_display(arabic_reshaper.reshape(str(text)))


class Report:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        pdfmetrics.registerFont(TTFont("Maal", str(FONT_REGULAR)))
        pdfmetrics.registerFont(TTFont("Maal-Bold", str(FONT_BOLD)))
        self.c = canvas.Canvas(str(path), pagesize=A4)
        self.c.setTitle("Maal Full System Report - Arabic")
        self.w, self.h = A4
        self.margin = 46
        self.y = self.h - 62
        self.page = 0

    def _header_footer(self):
        if self.page <= 1:
            return
        self.c.setStrokeColor(LINE)
        self.c.line(self.margin, 34, self.w - self.margin, 34)
        self.c.setFont("Maal", 8)
        self.c.setFillColor(MUTED)
        self.c.drawString(self.margin, 20, "Maal - Decision support, not legal advice")
        self.c.drawRightString(self.w - self.margin, 20, rtl(f"صفحة {self.page}"))

    def new_page(self, section: str | None = None):
        if self.page:
            self._header_footer()
            self.c.showPage()
        self.page += 1
        self.y = self.h - 58
        if section:
            self.c.setFillColor(NAVY)
            self.c.roundRect(self.margin, self.h - 91, self.w - 2 * self.margin, 34, 7, fill=1, stroke=0)
            self.c.setFillColor(white)
            self.c.setFont("Maal-Bold", 16)
            self.c.drawRightString(self.w - self.margin - 14, self.h - 80, rtl(section))
            self.y = self.h - 112

    def ensure(self, needed: float, section: str | None = None):
        if self.y - needed < 48:
            self.new_page(section)

    def wrap(self, text: str, size: float, width: float, bold: bool = False) -> list[str]:
        font = "Maal-Bold" if bold else "Maal"
        words = str(text).split()
        if not words:
            return [""]
        lines, current = [], ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if pdfmetrics.stringWidth(rtl(candidate), font, size) <= width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines

    def paragraph(self, text: str, size: float = 10.5, color=SLATE, bold: bool = False,
                  gap: float = 9, indent: float = 0):
        width = self.w - 2 * self.margin - indent
        lines = self.wrap(text, size, width, bold)
        line_h = size * 1.62
        self.ensure(line_h * len(lines) + gap)
        self.c.setFont("Maal-Bold" if bold else "Maal", size)
        self.c.setFillColor(color)
        for line in lines:
            self.c.drawRightString(self.w - self.margin - indent, self.y, rtl(line))
            self.y -= line_h
        self.y -= gap

    def heading(self, text: str, size: float = 17):
        self.ensure(42)
        self.c.setFillColor(GOLD)
        self.c.roundRect(self.w - self.margin - 8, self.y - 18, 8, 24, 4, fill=1, stroke=0)
        self.c.setFillColor(NAVY)
        self.c.setFont("Maal-Bold", size)
        self.c.drawRightString(self.w - self.margin - 18, self.y, rtl(text))
        self.y -= 34

    def bullets(self, items: list[str], color=SLATE):
        for item in items:
            lines = self.wrap(item, 10, self.w - 2 * self.margin - 25)
            self.ensure(18 * len(lines) + 5)
            self.c.setFillColor(GOLD)
            self.c.circle(self.w - self.margin - 5, self.y + 2, 2.4, fill=1, stroke=0)
            self.c.setFillColor(color)
            self.c.setFont("Maal", 10)
            for line in lines:
                self.c.drawRightString(self.w - self.margin - 16, self.y, rtl(line))
                self.y -= 16
            self.y -= 3
        self.y -= 5

    def callout(self, title: str, body: str, tone: str = "green"):
        fill = PALE_GREEN if tone == "green" else PALE_AMBER
        accent = NAVY if tone == "green" else GOLD
        lines = self.wrap(body, 9.5, self.w - 2 * self.margin - 30)
        height = 42 + 15 * len(lines)
        self.ensure(height + 12)
        self.c.setFillColor(fill)
        self.c.roundRect(self.margin, self.y - height + 8, self.w - 2 * self.margin, height, 8, fill=1, stroke=0)
        self.c.setFillColor(accent)
        self.c.rect(self.w - self.margin - 5, self.y - height + 8, 5, height, fill=1, stroke=0)
        self.c.setFont("Maal-Bold", 11)
        self.c.drawRightString(self.w - self.margin - 17, self.y - 10, rtl(title))
        self.c.setFont("Maal", 9.5)
        self.c.setFillColor(SLATE)
        line_y = self.y - 29
        for line in lines:
            self.c.drawRightString(self.w - self.margin - 17, line_y, rtl(line))
            line_y -= 15
        self.y -= height + 8

    def metrics(self, values: list[tuple[str, str]], columns: int = 3):
        gap = 10
        card_w = (self.w - 2 * self.margin - gap * (columns - 1)) / columns
        rows = (len(values) + columns - 1) // columns
        self.ensure(rows * 74 + 18)
        for idx, (label, value) in enumerate(values):
            row, col = divmod(idx, columns)
            x = self.w - self.margin - card_w - col * (card_w + gap)
            y = self.y - row * 74
            self.c.setFillColor(white)
            self.c.setStrokeColor(LINE)
            self.c.roundRect(x, y - 60, card_w, 60, 8, fill=1, stroke=1)
            self.c.setFillColor(MUTED)
            self.c.setFont("Maal", 8.5)
            self.c.drawRightString(x + card_w - 10, y - 18, rtl(label))
            self.c.setFillColor(NAVY)
            self.c.setFont("Maal-Bold", 17)
            self.c.drawRightString(x + card_w - 10, y - 44, rtl(value))
        self.y -= rows * 74 + 12

    def flow(self, labels: list[str]):
        gap = 7
        box_w = (self.w - 2 * self.margin - gap * (len(labels) - 1)) / len(labels)
        self.ensure(72)
        for idx, label in enumerate(labels):
            x = self.w - self.margin - box_w - idx * (box_w + gap)
            self.c.setFillColor(NAVY if idx == 0 else PALE_GREEN)
            self.c.setStrokeColor(SAGE)
            self.c.roundRect(x, self.y - 50, box_w, 50, 7, fill=1, stroke=idx != 0)
            self.c.setFillColor(white if idx == 0 else NAVY)
            self.c.setFont("Maal-Bold", 8.3)
            lines = self.wrap(label, 8.3, box_w - 12, True)
            line_y = self.y - 21
            for line in lines[:2]:
                self.c.drawCentredString(x + box_w / 2, line_y, rtl(line))
                line_y -= 13
        self.y -= 66

    def table(self, headers: list[str], rows: list[list[str]], widths: list[float]):
        row_h = 31
        total_w = sum(widths)
        self.ensure(row_h * (len(rows) + 1) + 12)
        x0 = self.w - self.margin - total_w
        y0 = self.y
        data = [headers] + rows
        for ridx, row in enumerate(data):
            x = x0
            fill = NAVY if ridx == 0 else (IVORY if ridx % 2 else white)
            self.c.setFillColor(fill)
            self.c.rect(x0, y0 - row_h * (ridx + 1), total_w, row_h, fill=1, stroke=0)
            for cidx, value in enumerate(row):
                width = widths[cidx]
                self.c.setStrokeColor(LINE)
                self.c.rect(x, y0 - row_h * (ridx + 1), width, row_h, fill=0, stroke=1)
                self.c.setFont("Maal-Bold" if ridx == 0 else "Maal", 8.2)
                self.c.setFillColor(white if ridx == 0 else SLATE)
                self.c.drawRightString(x + width - 7, y0 - row_h * ridx - 20, rtl(str(value)))
                x += width
        self.y -= row_h * len(data) + 15

    def cover(self):
        self.page = 1
        self.c.setFillColor(IVORY)
        self.c.rect(0, 0, self.w, self.h, fill=1, stroke=0)
        self.c.setFillColor(NAVY)
        self.c.rect(0, self.h - 250, self.w, 250, fill=1, stroke=0)
        self.c.setFillColor(GOLD)
        self.c.circle(self.w - 92, self.h - 72, 7, fill=1, stroke=0)
        self.c.setStrokeColor(GOLD)
        self.c.setLineWidth(3)
        self.c.arc(self.w - 180, self.h - 153, self.w - 70, self.h - 105, 10, 155)
        self.c.setFillColor(white)
        self.c.setFont("Maal-Bold", 40)
        self.c.drawRightString(self.w - 56, self.h - 118, rtl("مآل"))
        self.c.setFont("Maal", 13)
        self.c.drawRightString(self.w - 56, self.h - 151, "MAAL COMPLIANCE INTELLIGENCE")
        self.c.setFillColor(NAVY)
        self.c.setFont("Maal-Bold", 25)
        self.c.drawRightString(self.w - 56, self.h - 330, rtl("التقرير الكامل للنظام"))
        self.c.setFont("Maal", 13)
        self.c.setFillColor(SLATE)
        self.c.drawRightString(self.w - 56, self.h - 370, rtl("المعمارية، المنتج، الذكاء الاصطناعي، الأمن، الاختبارات وخارطة الإنتاج"))
        self.c.setFillColor(PALE_GREEN)
        self.c.roundRect(56, self.h - 480, self.w - 112, 72, 9, fill=1, stroke=0)
        self.c.setFillColor(NAVY)
        self.c.setFont("Maal-Bold", 12)
        self.c.drawRightString(self.w - 76, self.h - 438, rtl("نسخة MVP حقيقية قائمة على بيانات المنشأة والمصادر الرسمية"))
        self.c.setFont("Maal", 9.5)
        self.c.drawRightString(self.w - 76, self.h - 462, rtl("مصادر حية: NCA وSASO | مراجعة بشرية إلزامية | أدلة قابلة للتتبع"))
        self.c.setFillColor(MUTED)
        self.c.setFont("Maal", 10)
        self.c.drawRightString(self.w - 56, 92, rtl("تاريخ التقرير: أكتوبر 2026"))
        self.c.drawRightString(self.w - 56, 70, rtl("حالة النظام: نموذج أولي تشغيلي قابل للعرض والاختبار"))

    def finish(self):
        self._header_footer()
        self.c.save()


def build():
    r = Report(OUTPUT)
    r.cover()

    r.new_page("الملخص التنفيذي")
    r.paragraph("مآل منصة امتثال تنظيمي تحول الوثائق الرسمية وملفات الشركة إلى قرارات قابلة للمراجعة والتتبع. تبدأ الرحلة بفهم المنشأة من ملفاتها، ثم مراقبة المصادر الرسمية، واكتشاف النسخ والتغييرات، وتحديد التوافق مع نطاق الشركة، ومطابقة كل متطلب بموضعه داخل الملف الداخلي، ثم إيقاف أي إجراء تنفيذي حتى اعتماد الموظف المختص.", 11)
    r.metrics([
        ("المصادر الحية", "2"), ("صيغ ملفات الشركة", "6"), ("اختبارات ناجحة", "57"),
        ("ملفات المنشأة المرحّلة", "25"), ("علاقات أدلة حالية", "20"), ("أخطاء الترحيل", "0"),
    ])
    r.callout("مبدأ الثقة", "لا يحول مآل التشابه النصي إلى ادعاء امتثال. إذا كان المقطع ذا صلة لكن لا يثبت التنفيذ، تظهر النتيجة أدلة غير كافية ويطلب قرار الموظف.")
    r.heading("المشكلة التي يعالجها")
    r.bullets([
        "توزع الأنظمة واللوائح عبر جهات ومواقع وملفات متعددة وصعوبة معرفة ما تغير فعلًا.",
        "فصل فرق الامتثال عن السياسات والمشروعات والأصول التي تتأثر بالمتطلب.",
        "الاعتماد على مراجعات يدوية طويلة دون أثر تدقيق يربط الحكم بالمصدر والملف والموضع.",
        "خطر تحويل نتائج الذكاء الاصطناعي إلى قرارات قطعية دون دليل أو مراجعة بشرية.",
    ])
    r.heading("القيمة المقترحة")
    r.paragraph("مآل يختصر زمن الوصول من تحديث رسمي إلى أثر داخلي قابل للتنفيذ، مع إبقاء القرار النهائي للإنسان وحفظ مصدر كل استنتاج. القيمة ليست جمع اللوائح فقط، بل إثبات أين تلتقي المادة التنظيمية مع وثائق المنشأة وما الدليل الناقص أو المتعارض.")

    r.new_page("نطاق المنتج الحالي")
    r.heading("القدرات المنفذة")
    r.bullets([
        "Onboarding حقيقي متعدد الملفات لا يبدأ ببيانات Demo افتراضيًا.",
        "استخراج PDF وDOCX وXLSX وPPTX وTXT وCSV مع page وsection وslide وsheet وcell وline.",
        "موصلات رسمية حية للهيئة الوطنية للأمن السيبراني NCA وهيئة المواصفات SASO.",
        "نسخ immutable وبصمة SHA-256 ومقارنة no-op عند عدم تغير المحتوى.",
        "تصفية توافق الوثيقة مع المنشأة قبل تحليل الأثر، مع حالات needs review بدل الاستبعاد الخاطئ.",
        "مطابقة المتطلبات الحالية بملفات الشركة مع الاقتباس والموضع وحالة التطبيق.",
        "مراجعة ملف مشروع أو سياسة عند الطلب مع score واستشهاد وتصحيح مقترح.",
        "صلاحيات مدير وموظف امتثال، ومراجعة بشرية وذاكرة تصحيح مرتبطة ببصمة الدليل.",
        "تتبع أثر محفوظ في قاعدة البيانات، وليس رسمًا بصريًا مولدًا فقط.",
    ])
    r.heading("ما لا يدعيه النظام")
    r.bullets([
        "ليس مستشارًا قانونيًا ولا يمنح شهادة امتثال.",
        "لا يدرب نموذجًا جديدًا تلقائيًا من قرارات الموظفين.",
        "لا يعرض عقوبة أو تعرضًا ماليًا دون citation رسمي أو مدخلات شركة معتمدة.",
        "لا يدعي وجود موصل حي لجهة غير NCA أو SASO.",
    ], color=RED)

    r.new_page("المعمارية العامة")
    r.flow(["المصادر الرسمية", "الاكتشاف والنسخ", "كشف التغيير", "التوافق", "مطابقة الأدلة", "المراجعة البشرية"])
    r.heading("طبقات النظام")
    r.table(
        ["الطبقة", "المسؤولية", "التقنية الحالية"],
        [
            ["الواجهة", "Onboarding وDashboard والتحليل والمراجعة", "HTML وCSS وJavaScript"],
            ["API", "العقود والصلاحيات والمهام غير المتزامنة", "FastAPI"],
            ["الوكيل", "آلة حالات واستئناف وحدود محاولة", "State machine دائمة"],
            ["البيانات", "نسخ وأدلة وعلاقات وتدقيق", "SQLite + migrations"],
            ["الاسترجاع", "مواد ومقاطع فعلية بالمعرفات والنص", "بحث نصي وقواعد"],
            ["AI", "استخراج منظم خلف عميل قابل للاستبدال", "LLMClient + validation"],
        ],
        [118, 238, 145],
    )
    r.callout("قرار هندسي", "استخدم الـMVP آلة حالات واضحة بدل LangGraph لتقليل عدم الاستقرار، مع thread_id وcheckpoints واستئناف ونقطة توقف بشرية. يمكن استبدال المنسق لاحقًا دون تغيير عقود البيانات.", "amber")

    r.new_page("رحلة إعداد المنشأة")
    r.flow(["اسم الشركة", "رفع عدة ملفات", "استخراج facts", "Baseline إلزامي", "مراجعة النطاق", "اعتماد النسخة"])
    r.heading("الحقائق المستخرجة")
    r.bullets([
        "الأنشطة والمنتجات والخدمات والإدارات والعمليات والتقنيات والمواد والمرافق.",
        "وجود الموظفين ومعالجة البيانات الشخصية ونظم المعلومات والتصنيع والموردين والعملاء.",
        "نشاط الاستيراد والتصدير والدول والتراخيص والشهادات والجهات المشار إليها صراحة.",
        "لكل fact قيمة وملف مصدر وموضع دقيق وثقة وطريقة استخراج.",
    ])
    r.heading("تحديد النطاق التنظيمي")
    r.paragraph("النطاق التنظيمي يساوي النطاق المستنتج من الملفات + خط الأساس الإلزامي + ما يؤكده المستخدم. وجود موظفين يضيف العمل والتوظيف، ومعالجة البيانات تضيف الخصوصية، واستخدام نظم المعلومات يضيف الأمن السيبراني، والتصنيع يضيف مواصفات المنتجات والمطابقة.")
    r.callout("حماية البيانات", "لا تتحول inference إلى fact بلا دليل. المعلومة غير المعروفة تظهر Unknown أو Needs confirmation، والمجال الإلزامي لا يحذف بواسطة الموظف العادي.")

    r.new_page("المراقبة التنظيمية الحية")
    r.heading("NCA")
    r.bullets([
        "قراءة فهرس الوثائق الرسمي وتنزيل الملفات الرسمية وتخزين canonical URL.",
        "دعم عائلات ECC وCSCC وCCC وOTCC وDCC ضمن الاختبارات الحية السابقة.",
        "لا تعامل كل وثائق الجهة على أنها منطبقة؛ القرار يمر بمحرك نطاق المنشأة.",
    ])
    r.heading("SASO")
    r.bullets([
        "قراءة قائمة اللوائح الفنية الرسمية والفئات والتواريخ وروابط التنزيل المتاحة.",
        "إعطاء أولوية للمنتجات والإلكترونيات والمكونات والتصنيع المثبتة في ملف الشركة.",
        "القيمة المفقودة تبقى فارغة بدل استنتاج تاريخ أو فئة غير منشورة.",
    ])
    r.heading("سلوك المسح")
    r.flow(["Fetch", "Hash", "New/Updated", "Unchanged", "تصفية النطاق", "تحليل ذي صلة"])
    r.paragraph("يصدر POST /regulatory-scans تشغيلًا غير متزامن. تعرض الواجهة التقدم والوثائق فور وصولها بدل انتظار اكتمال القائمة كلها. إعادة المسح بنفس البصمة لا تنشئ نسخة أو تغييرًا وهميًا.")

    r.new_page("مطابقة المتطلبات وحالة التطبيق")
    r.heading("من التوافق العام إلى الدليل الدقيق")
    r.flow(["اللائحة", "المادة", "المتطلب", "ملف الشركة", "الموضع", "حالة التطبيق"])
    r.paragraph("يفرق النظام بين علاقة الوثيقة بنشاط المنشأة وبين تنفيذ كل متطلب. بعد قبول الوثيقة في النطاق، يستخرج المواد الإلزامية ويبحث في المقاطع الداخلية ثم يحفظ العلاقة في requirement_assessments.")
    r.heading("مثال رقمي حتمي")
    r.table(
        ["البند", "القيمة"],
        [
            ["المتطلب الرسمي", "متدرب واحد لكل 50 موظفًا"],
            ["سياسة الشركة", "متدرب واحد لكل 100 موظف"],
            ["الحكم", "غير متوافق"],
            ["التصحيح", "تحديث السياسة إلى 1 لكل 50 على الأقل"],
        ],
        [180, 321],
    )
    r.callout("منع الادعاء", "إذا كان الملف يذكر الموضوع لكنه لا يثبت التنفيذ، تكون الحالة Insufficient Evidence. وإذا وجدت قيم أو أدلة متعارضة يتوقف الحكم للمراجعة.", "amber")

    r.new_page("المراجعة البشرية والتعلم المقيد")
    r.heading("ما يستطيع الموظف مراجعته")
    r.bullets([
        "تأكيد أو رفض تصنيف الوثيقة: applicable أو not applicable أو needs review.",
        "تأكيد أو تصحيح حالة تطبيق المتطلب داخل ملف وموضع محدد.",
        "تأكيد أو تصحيح finding ناتج من مراجعة ملف عند الطلب.",
        "كتابة سبب القرار، مع حفظ المستخدم والدور والوقت والتصنيف المصحح.",
    ])
    r.heading("كيف يتعلم النظام بأمان")
    r.paragraph("يحفظ التصحيح مع subject key وبصمة evidence fingerprint. يعاد استخدامه عندما تكون المادة ومقطع الشركة بالبصمة نفسها. إذا تغير التشريع أو الملف تتغير البصمة ويطلب حكم جديد. هذا يمنع تعميم تصحيح قديم على دليل مختلف.")
    r.callout("لا يوجد تدريب خفي", "الـMVP يستخدم ذاكرة قرارات منظمة وقابلة للتدقيق. أي تدريب أو تعميم لاحق يحتاج dataset معتمدًا وتقييمًا وموافقة حوكمة مستقلة.")

    r.new_page("مراجعة الملفات عند الطلب")
    r.heading("الرحلة")
    r.flow(["رفع الملف", "استخراج السياق", "استرجاع المتطلبات", "فحص كل بند", "Score", "تصحيح مقترح"])
    r.heading("المخرجات")
    r.bullets([
        "Compliant وPartially Compliant وNon-Compliant وNeeds Review وInsufficient Evidence.",
        "درجة امتثال موزونة على المتطلبات التي أمكن تقييمها فقط.",
        "اسم الملف والصفحة أو القسم أو الشريحة أو الورقة والخلية أو السطر.",
        "اقتباس تنظيمي حالي واقتباس من الملف وتفسير وتصحيح مقترح.",
        "شارة Recently superseded requirement detected عند استخدام متطلب أُلغي خلال نافذة 30 يومًا.",
    ])
    r.heading("Document Dependency Graph")
    r.paragraph("تُحفظ العلاقات Regulation إلى Article إلى Obligation إلى Internal Document إلى Section إلى Department إلى Project في قاعدة البيانات. يمكن الاستعلام عن كل الملفات والمشروعات التي تعتمد على requirement قديم.")

    r.new_page("الأمن والصلاحيات والخصوصية")
    r.table(
        ["الدور", "الصلاحيات الأساسية"],
        [
            ["مدير النظام", "إدارة المستخدمين، اعتماد الملف، الحذف، تجاوز إلزامي، اعتماد المهام"],
            ["موظف الامتثال", "رفع الأدلة، تشغيل المسح، مراجعة الملفات، تصحيح تحليل الوكيل"],
        ],
        [145, 356],
    )
    r.bullets([
        "اشتقاق كلمات المرور بـPBKDF2 وعدم تخزينها كنص واضح.",
        "جلسات قابلة للإلغاء، وتقييد CORS، والتحقق من ملكية نتيجة feedback للمنشأة.",
        "عدم تسجيل مفاتيح API أو سلسلة التفكير الداخلية.",
        "اعتبار الوثائق مدخلات غير موثوقة ومقاومة prompt injection داخل النص.",
        "فصل النص التنظيمي عن أدلة المنشأة والحفاظ على النص القانوني بلغته الأصلية.",
    ])
    r.callout("حدود الأمن", "الدخول المحلي مناسب للـMVP. الإنتاج يحتاج SSO وMFA وtenant isolation وتشفيرًا مُدارًا وسياسات احتفاظ وفصل واجبات.", "amber")

    r.new_page("قاعدة البيانات وعقود البيانات")
    r.heading("الكيانات الأساسية")
    r.bullets([
        "Source وDocumentVersion وClause وRegulatoryChange وObligation.",
        "CompanySnapshot وCompanyProfileVersion وExtractedCompanyFact وEvidence.",
        "ApplicabilityResult وRequirementAssessment وFinding وTaskDraft وReview.",
        "AuditEvent وRunState وAnalysisFeedback وDocumentDependency.",
    ])
    r.heading("Migrations المهمة")
    r.table(
        ["Migration", "الغرض"],
        [
            ["001-003", "الأساس، المصادر، المسح، الملفات، المراجعة والتعرض"],
            ["004", "Onboarding الحقيقي ونسخ ملف الشركة والنطاق"],
            ["006", "المستخدمون المحليون والجلسات والأدوار"],
            ["007", "مطابقة المتطلبات وfeedback الموظفين"],
        ],
        [135, 366],
    )
    r.paragraph("كل نسخة وثيقة وملف شركة مرتبطة ببصمة ومصدر وزمن. لا تستبدل النسخ السابقة، ويستخدم النظام مفاتيح فريدة ومعرفات تشغيل لمنع تكرار النتائج والمهام.")

    r.new_page("واجهات API")
    r.table(
        ["المجموعة", "أهم المسارات"],
        [
            ["الصحة والدخول", "/health, /ready, /auth/setup, /auth/login, /auth/users"],
            ["الشركة", "/onboarding/documents, /onboarding/{id}/approve, /company-documents"],
            ["المصادر", "/regulatory-sources, /regulatory-documents, /regulatory-scans"],
            ["التحليل", "/runs, /changes/{id}, /ui/live-overview"],
            ["مراجعة الملفات", "/compliance-reviews/upload, /compliance-reviews/{id}"],
            ["الإنسان", "/tasks/{id}/review, /analysis-feedback"],
            ["الأثر والتقرير", "/impact-graph, /reports/system"],
        ],
        [135, 366],
    )
    r.heading("قواعد العقود")
    r.bullets([
        "202 للتشغيل غير المتزامن مع idempotency key.",
        "expected_revision لمنع اعتماد نسخة قديمة من المهمة.",
        "Pydantic للتحقق الصارم، وحدود مهلة وإعادة محاولة للمزود الخارجي.",
        "النتائج تحمل المصدر والنسخة والمنشأة وإصدارات النموذج والـprompt والـschema حيث ينطبق.",
    ])

    r.new_page("الواجهة وتجربة المستخدم")
    r.bullets([
        "واجهة عربية RTL وإنجليزية LTR مع بقاء النص القانوني بلغته الأصلية.",
        "Dashboard للتحديثات والأولوية والإدارات والمجالات غير المتصلة.",
        "Regulatory Analysis لعرض الوثيقة الحالية والمقارنة الاختيارية وسبب التوافق والأدلة الداخلية.",
        "Company Files صفحة مستقلة للإضافة والحذف وإعادة الرفع دون بقايا بيانات الملف المحذوف.",
        "File Compliance Review للرفع والسجل الدقيق والـscore والتصحيح.",
        "Impact Traceability لمسار الأثر، وHuman Review للقرار والتعليق.",
        "سجل التدقيق الكامل داخل تفاصيل تقنية قابلة للتوسيع بدل إغراق الشاشة.",
    ])
    r.heading("التعرض المالي")
    r.paragraph("تختفي الصفحة عندما لا توجد مدخلات مالية فعلية ومعتمدة. لا تعرض عقوبة مباشرة بلا مصدر رسمي، ولا تكلفة معالجة أو توقف أو عقد بلا مدخل شركة. البيانات الاصطناعية تبقى فقط في DEMO_MODE=true للاختبار والعرض الاحتياطي.")

    r.new_page("التحقق والاختبارات")
    r.metrics([
        ("إجمالي الاختبارات", "57 Passed"), ("فشل الاختبارات", "0"), ("تحذيرات مؤثرة", "0"),
        ("ملفات حالية", "25"), ("علاقات منقحة", "20"), ("زمن الربط المحلي", "1.76s"),
    ])
    r.heading("التغطية")
    r.bullets([
        "تغيير رقمي، لا تغيير، تغيير تحريري، عدم انطباق ونقص أو تعارض الأدلة.",
        "النفي والاستثناءات واختلاف الوحدات والاستئناف ومنع تكرار المهمة.",
        "رفض مستخدم غير مخول ورفض revision قديم ومقاومة prompt injection.",
        "استخراج الصيغ الست والمواضع، حذف الملف وإعادة رفعه، وعزل Demo عن الوضع الحقيقي.",
        "مقارنة نسب الموظفين والمتدربين بالأرقام الغربية والعربية، وحفظ تصحيح الموظف وإعادة استخدامه لنفس البصمة.",
    ])
    r.callout("نتيجة البيانات الحالية", "العلاقات العشرون الحالية Insufficient Evidence. توجد صلة نصية وموضع، لكن لا يوجد دليل تنفيذي كافٍ لإعلان الامتثال. هذه نتيجة مقصودة تحفظ النزاهة.", "amber")

    r.new_page("النشر الحالي وقابلية التوسع")
    r.heading("Render Free")
    r.bullets([
        "FastAPI وUvicorn وفق render.yaml مع health check على /health.",
        "DEMO_MODE=false وموفر AI deterministic افتراضيًا.",
        "SQLite والملفات تحت /tmp في الخطة المجانية، وقد تفقد البيانات عند إعادة التشغيل أو النشر.",
        "قد يتأخر أول طلب بسبب cold start. هذا مناسب للعرض المؤقت وليس توافرًا إنتاجيًا.",
    ])
    r.heading("خارطة التوسع")
    r.table(
        ["المرحلة", "المطلوب"],
        [
            ["Pilot", "PostgreSQL، object storage، scheduler، OCR، تقييم حقيقي، SSO أولي"],
            ["Production", "Multi-tenant isolation، queue workers، observability، DR، SLA، pentest"],
            ["Scale", "فهرس هجين، موصلات معتمدة إضافية، GRC فعلي، حوكمة feedback"],
        ],
        [120, 381],
    )

    r.new_page("المخاطر والضوابط")
    r.table(
        ["الخطر", "الضابط الحالي", "المتبقي"],
        [
            ["هلوسة قانونية", "مصدر واقتباس وحالات عدم يقين", "مراجعة قانونية"],
            ["False positive", "فلتر نوعي وحد أعلى للمرشحين", "Eval dataset"],
            ["تسرب بيانات", "محلي وCORS وعدم تسجيل أسرار", "تشفير وSSO"],
            ["فشل مصدر حي", "أحداث fetch وأخطاء ظاهرة", "مراقبة وتنبيه"],
            ["فقد التخزين", "نسخ immutable محليًا", "Object storage"],
            ["Feedback خاطئ", "هوية وبصمة وعدم تعميم", "اعتماد مزدوج"],
        ],
        [125, 190, 186],
    )
    r.heading("قرار Go / No-Go")
    r.paragraph("النظام جاهز كـMVP وعرض هاكاثون وPilot محدود ببيانات غير شديدة الحساسية. ليس جاهزًا بعد للاستخدام الإنتاجي القانوني متعدد المنشآت حتى استكمال التخزين الدائم والهوية المؤسسية والتقييم الأمني والقانوني.")

    r.new_page("مؤشرات النجاح والأثر التجاري")
    r.bullets([
        "زمن اكتشاف تحديث رسمي وزمن الوصول إلى أول نتيجة قابلة للمراجعة.",
        "نسبة النتائج التي تحمل citation وموضع دليل داخلي صالحًا.",
        "نسبة قرارات الوكيل التي أكدها الموظفون حسب المصدر ونوع القرار.",
        "نسبة Needs Review وInsufficient Evidence وأسبابها.",
        "انخفاض ساعات البحث اليدوي وعدد المهام المكررة أو الضائعة.",
        "عدد الإدارات والمشروعات والملفات المرتبطة فعليًا بالمتطلبات.",
    ])
    r.heading("عناصر التميز")
    r.paragraph("ميزة مآل ليست chatbot ولا لوحة تجمع روابط. التميز هو السلسلة القابلة للتدقيق من المصدر الرسمي إلى المادة والمتطلب وملف الشركة والموضع والإدارة والمشروع، مع ذاكرة تصحيح بشرية مقيدة ببصمة الدليل.")

    r.new_page("سيناريو العرض أمام لجنة التحكيم")
    r.bullets([
        "الدخول كموظف امتثال وإظهار فصل الصلاحيات عن المدير.",
        "فتح تحديث رسمي وعرض المصدر والنسخة والبصمة وحالة New أو Updated أو Unchanged.",
        "عرض سبب توافقه مع المنشأة ثم اسم الملف والموضع الدقيق الذي يطابق المادة.",
        "عرض مقارنة رقمية تثبت عدم التطبيق بدل سبب عام.",
        "رفض تصنيف خاطئ وكتابة السبب واختيار التصنيف الصحيح.",
        "إعادة فتح النتيجة لإظهار قرار الموظف وسجل التدقيق.",
        "رفع ملف مشروع جديد وإظهار score والاقتباس والموضع والتصحيح.",
        "توضيح أن التعرض المالي مخفي عند غياب بيانات فعلية، وهو قرار نزاهة.",
    ])
    r.callout("الرسالة الختامية", "مآل لا يستبدل مسؤول الامتثال. مآل يمنحه رؤية أسرع، ودليلًا أدق، وقرارًا يمكن مراجعته والدفاع عنه.")

    r.new_page("القيود والإجراءات التالية")
    r.heading("P0 قبل Pilot")
    r.bullets([
        "نقل البيانات إلى PostgreSQL وملفات إلى object storage دائم ومشفر.",
        "SSO وMFA وعزل المنشآت وتدقيق صلاحيات تفصيلي.",
        "OCR عربي للوثائق المصورة واختبارات جودة استخراج واقعية.",
        "اعتماد dataset تقييم حقيقي وقياس precision وrecall للمطابقة.",
    ])
    r.heading("P1")
    r.bullets([
        "عامل queue منفصل ومراقبة وتنبيه وإعادة محاولات موزعة.",
        "بحث هجين نصي ودلالي مع بقاء التحقق القاعدي للأرقام والتواريخ.",
        "تكامل GRC حقيقي بعد اعتماد النظام المستهدف وعقد البيانات.",
    ])
    r.heading("P2")
    r.bullets([
        "موصلات رسمية إضافية حسب النطاق المؤكد للعميل.",
        "تحليلات اتجاهات وقياس أداء الإدارات وworkflow اعتماد feedback متعدد المستويات.",
    ])
    r.paragraph("نهاية التقرير", 12, NAVY, True, 0)
    r.finish()
    print(OUTPUT)


if __name__ == "__main__":
    build()
