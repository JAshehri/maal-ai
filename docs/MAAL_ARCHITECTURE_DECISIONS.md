# سجل قرارات المعمارية الهندسية والأساس العلمي (ADRs & Scientific Foundations)
**المشروع:** مآل – Maal (AI-powered Regulatory Intelligence & Compliance Platform)
**الحالة:** معتمد
**التاريخ:** سبتمبر 2026

---

## مقدمة ومنهجية التوثيق (Methodology)

تتبع هذه الوثيقة معيار **Architecture Decision Records (ADR)** لتوثيق القرارات الجوهرية المتخذة في معمارية منصة «مآل».
ولتحقيق أقصى درجات الشفافية والنزاهة الهندسية، تم تصنيف كل بيان علمي أو تقني وفق المقياس التالي:
- **[Implemented Fact]:** حقيقة مطبقة ومختبرة برمجياً داخل الكود.
- **[Engineering Decision]:** قرار هندسي اتخذه الفريق بناءً على موازنات التصميم وأفضل الممارسات.
- **[Research-backed Recommendation]:** توصية مدعومة ببحوث علمية محكمة في معالجة اللغات الطبيعية أو استرجاع المعلومات أو المعلوماتية القانونية.
- **[Assumption]:** افتراض تصميمي مدروس خاضع للتحقق العملي.
- **[Future Improvement]:** تحسين مستقبلي مجدول في خارطة الطريق.

---

## فهرس القرارات المعمارية (Table of ADRs)

- **ADR-001:** حفظ الإصدارات التنظيمية غير القابلة للتعديل (Immutable Regulatory Versions)
- **ADR-002:** الحفاظ المزدوج على النص العربي الخام والمعياري (Dual Storage: Raw & Normalized Arabic Text)
- **ADR-003:** الفصل الصارم بين قاعدة المعرفة التنظيمية وقاعدة معرفة المنشأة (KB Separation)
- **ADR-004:** الاعتماد على المقارنات الحتمية للتواريخ والحدود الرقمية وحظر الاختلاق (Deterministic Rules over LLM Hallucination)
- **ADR-005:** محرك الاسترجاع الهجين متعدد اللغات وتصفية البيانات الوصفية المسبقة (Hybrid Multilingual Retrieval)
- **ADR-006:** المراجعة الزمنية المحددة للامتثال وتتبع تاريخ النفاذ (`as_of_date` Temporal Review)
- **ADR-007:** المراجعة البشرية الإلزامية قبل اعتماد المهام ونتائج الامتثال (Mandatory Human-in-the-Loop)
- **ADR-008:** تجريد جودة استخراج الوثائق والتصنيف الصريح للمستندات الممسوحة (OCR Quality Abstraction)

---

### ADR-001: حفظ الإصدارات التنظيمية غير القابلة للتعديل (Immutable Regulatory Versions)

#### الحالة
مقبول ومطبق (Accepted & Implemented)

#### السياق
اللوائح والأنظمة تتغير باستمرار. في كثير من الأحيان تصدر جهة رقابية تعديلاً على مادة معينة، وإذا قام النظام باستبدال النسخة القديمة، يفقد قدرته على تدقيق قرارات المنشأة التي اتُخذت في ظل النسخة السابقة.

#### القرار
اعتبار كل نسخة لائحة كياناً غير قابل للتعديل أو الاستبدال (`Immutable Version`). كل نسخة تحمل بصمة تشفيرية فريدة `SHA-256` للنص الكامل وللملف الأصلي، وتُربط بالنسخة السابقة عبر حقل `supersedes_version_id`.

#### الأساس العلمي والتقني
- **Software Engineering Best Practice:** مبدأ الثبات (Immutability) في أنظمة الأحداث والتدقيق المؤسسي (Event Sourcing & Auditability - Fowler, 2017).
- **Legal Informatics Research:** الأنظمة القانونية تخضع لمبدأ "عدم رجعية القوانين" (Non-retroactivity of laws)، مما يفرض حفظ النص القانوني كما كان نافذاً في كل لحظة زمنية (Bench-Capon et al., *Computers and Law*, 2012).
- **تصنيف الأساس:** **[Engineering Decision]** و **[Research-backed Recommendation]**.

#### البدائل المرفوضة
- **تحديث السجل الحالي (Overwrite In-Place):** رُفض لأنه يدمر السجل التاريخي ويجعل التدقيق القانوني مستحيلاً.
- **حفظ الفروقات فقط (Git-like Diffs without full text):** رُفض لتعقيد استرجاع نصوص المواد الكاملة بسرعة في استعلامات البحث.

---

### ADR-002: الحفاظ المزدوج على النص العربي الخام والمعياري (Dual Storage: Raw & Normalized Text)

#### الحالة
مقبول ومطبق (Accepted & Implemented)

#### السياق
تتطلب اللغة العربية توحيداً لأشكال الحروف (مثل الهمزات، الياء والألف المقصورة، التاء المربوطة) وحذف التشكيل والتطويل لتحقيق دقة بحث واسترجاع عالية. ولكن إجراء هذا التوحيد على النص الأصلي المخزن يفقد الوثيقة حجيتها كدليل قانوني واقتباس دقيق (Verbatim Legal Citation).

#### القرار
تخزين نسختين لكل مقطع ومستند:
1. `raw_text`: النص الأصلي تماماً كما ورد في الملف (للعرض، الاقتباس القانوني، والتدقيق).
2. `normalized_text`: النص المعياري الموحد (للبحث، المطابقة، ومقارنة التغييرات).

#### الأساس العلمي والتقني
- **NLP Research on Arabic Information Retrieval:** دراسات معالجة اللغة العربية تؤكد أن التطبيع الكامل (Hamza & Ya normalization) يرفع نسبة الاستدعاء (Recall) بنسبة تفوق 25%، ولكنه يسبب غموضاً في النص الأصلي إذا استُبدل (Darwish & Magdy, *Arabic Information Retrieval*, 2014; Habash, *Introduction to Arabic Natural Language Processing*, 2010).
- **تصنيف الأساس:** **[Research-backed Recommendation]** و **[Implemented Fact]**.

#### البدائل المرفوضة
- **التطبيع الدائم للنص المخزن:** رُفض لأنه يشوه الاقتباس القانوني ويمنع التحقق البصري الدقيق.
- **البحث في النص الخام فقط:** رُفض لأنه يفشل في العثور على المواد عند اختلاف الهمزة أو التاء المربوطة.

---

### ADR-003: الفصل الصارم بين قاعدة المعرفة التنظيمية وقاعدة معرفة المنشأة (KB Separation)

#### الحالة
مقبول (Accepted)

#### السياق
تتعامل المنصة مع نوعين من البيانات: نصوص تنظيمية عامة صادرة عن جهات حكومية، ووثائق داخلية سرية تخص المنشأة (عقود، تقارير تدقيق، سياسات).

#### القرار
فصل معماري كامل بين:
1. **Regulatory Knowledge Base:** تحتوي المصادر الرسمية، اللوائح، الإصدارات، والمواد، وتكون مشتركة ومعلنة ومفهرسة دون أي بيانات سرية.
2. **Company Knowledge Base:** تحتوي وثائق المنشأة المرفوعة، ملف المنشأة، الحقائق المستخرجة، وملاحظات الامتثال، وتكون معزولة منطقياً ومحمية بالصلاحيات ولا يمكن أن تتداخل مع اللوائح العامة.

#### الأساس العلمي والتقني
- **Security & Privacy Standards:** متطلبات نظام حماية البيانات الشخصية السعودي (PDPL) ومعايير ISO/IEC 27001 الخاصة بعزل البيانات وسريتها.
- **تصنيف الأساس:** **[Engineering Decision]** و **[Implemented Fact]**.

#### البدائل المرفوضة
- **دمج كافة الوثائق في فهرس بحث موحد دون عزل:** رُفض لوجود خطر أمني جسيم بتسرب بيانات المنشأة في نتائج البحث المشترك.

---

### ADR-004: الاعتماد على المقارنات الحتمية للتواريخ والحدود الرقمية وحظر الاختلاق (Deterministic Rules over LLM)

#### الحالة
مقبول ومطبق (Accepted & Implemented)

#### السياق
تتضمن اللوائح قيماً رقمية حاسمة (مثل: نسب الانبعاثات، مهل الإخطار بالأيام، المبالغ المالية). الاعتماد على النماذج اللغوية الكبيرة (LLMs) في استنتاج أو مقارنة هذه الأرقام يعرض النظام لمخاطر الهلوسة والخطأ الحسابي.

#### القرار
1. حظر كامل لتوليد أو تخمين الأرقام، المهل، التواريخ، أو الغرامات المالية من قِبل الـ LLM.
2. استخدام خوارزميات برمجية حتمية (Deterministic Parsers & Comparators) لاستخراج الأرقام (اللاتينية والهندية)، مقارنة الحدود ($\le, <, \ge, >$)، وحساب المهل الزمنية.
3. عند عدم وجود دليل مالي أو نص صريح، يُسجل فوراً: `Not enough data` أو `Insufficient Evidence` بدلاً من اختلاق أرقام تقديرية.

#### الأساس العلمي والتقني
- **AI Safety & Trustworthy AI Research:** أثبتت الدراسات أن الـ LLMs تعاني من ضعف جوهري في العمليات الحسابية الدقيقة وتوليد أرقام غير موثوقة ما لم تُسند بأدوات حتمية (Cobbe et al., *GSM8K*, 2021; Mielke et al., *Faithful Reasoning*, 2022).
- **تصنيف الأساس:** **[Engineering Decision]** و **[Implemented Fact]**.

#### البدائل المرفوضة
- **سؤال الـ LLM مباشرة "هل الرقم في الوثيقة متوافق مع اللائحة؟":** رُفض لانعدام الضمان الحسابي وإمكانية الهلوسة.

---

### ADR-005: محرك الاسترجاع الهجين متعدد اللغات وتصفية البيانات الوصفية المسبقة (Hybrid Multilingual Retrieval)

#### الحالة
مقبول للتنفيذ المرحلي (Accepted for Phased Implementation)

#### السياق
في الشركات الكبرى، قد تكون اللائحة مكتوبة بالعربية بينما وثيقة المنشأة والسياسة التقنية مكتوبة بالإنجليزية، أو العكس. البحث بالكلمات المفتاحية وحدها يفشل في الربط عبر اللغات.

#### القرار
اعتماد استراتيجية استرجاع متعددة المراحل:
1. **Metadata Pre-filtering:** تصفية مسبقة صارمة تستبعد الوثائق غير المنطبقة جغرافياً أو قطاعياً أو زمنياً.
2. **Lexical Retrieval (BM25):** بحث نصي دقيق للمطابقات الصريحة على النص المعياري.
3. **Multilingual Dense Embeddings:** استرجاع دلالي عابر للغات للمطابقة بين المفاهيم العربية والإنجليزية.
4. **Deterministic Gatekeeper:** تمرير النتائج لفاحص حتمي يمنع إصدار أي مخالفة دون وجود تطابق صريح ومسند.

#### الأساس العلمي والتقني
- **Information Retrieval State of the Art:** أثبتت أبحاث TREC و MS-MARCO أن الاسترجاع الهجين (Sparse BM25 + Dense Vectors) يتفوق باستمرار على كل أسلوب منفرد بنسبة 15-20% في دقة النتائج (Karpukhin et al., *DPR*, 2020; Formal et al., *SPLADE*, 2021).
- **تصنيف الأساس:** **[Research-backed Recommendation]** و **[Future Improvement]**.

---

### ADR-006: المراجعة الزمنية المحددة للامتثال وتتبع تاريخ النفاذ (`as_of_date` Temporal Review)

#### الحالة
مقبول ومطبق (Accepted & Implemented)

#### السياق
قد يُطلب من المنشأة إثبات امتثالها في تاريخ تدقيق سابق (مثلاً في 15 مارس 2025). إذا تم فحص مستنداتها باستخدام لوائح عام 2026، ستكون النتيجة مضللة وظالمة للمنشأة. كما أن اللائحة قد تكون منشورة اليوم لكن تاريخ نفاذها الإلزامي بعد 6 أشهر، فلا يجوز تصنيف المنشأة كمخالفة في فترة السماح.

#### القرار
دعم معلمة زمنية اختيارية `as_of_date` في كافة استدعاءات مراجعة الامتثال:
$$\text{Review Eligibility}(R, D) = (\text{Publication Date}(R) \le D) \land (\text{Effective Date}(R) \le D) \land (D < \text{Repealed Date}(R))$$
مع تمييز فترات السماح وتوفيق الأوضاع كحالة `Transition Period` بدلاً من المخالفة الفورية.

#### الأساس العلمي والتقني
- **Temporal Database & Legal Reasoning:** نظريات المنطق الزمني في المعلوماتية القانونية (Temporal Defeasible Logic - Governatori et al., *Artificial Intelligence and Law*, 2010).
- **تصنيف الأساس:** **[Engineering Decision]** و **[Implemented Fact]**.

---

### ADR-007: المراجعة البشرية الإلزامية قبل اعتماد المهام ونتائج الامتثال (Mandatory Human-in-the-Loop)

#### الحالة
مقبول ومطبق (Accepted & Implemented)

#### السياق
أي قرار امتثال خاطئ أو تكليف بمهمة غير لازمة يكلف المنشأة موارد بشرية ومالية ومسؤوليات قانونية.

#### القرار
إنشاء نقطة توقف إلزامية (Mandatory Checkpoint) في آلة الحالات؛ كافة مسودات المهام والنتائج تبقى بحالة `pending_human_review` حتى يقوم مراجع معتمد بمراجعتها وقبولها أو تعديلها أو رفضها مع تسجيل سبب القرار ورقم المراجعة `revision`.

#### الأساس العلمي والتقني
- **Responsible AI Principles & Legal Liability:** إرشادات الذكاء الاصطناعي المسؤول الصادرة عن هيئة الذكاء الاصطناعي السعودية (SDAIA) والمفوضية الأوروبية، والتي تشترط الرقابة البشرية الفعالة (Human Oversight) في الأنظمة ذات الأثر الحرج.
- **تصنيف الأساس:** **[Engineering Decision]** و **[Implemented Fact]**.

---

### ADR-008: تجريد جودة استخراج الوثائق والتصنيف الصريح للمستندات الممسوحة (OCR Quality Abstraction)

#### الحالة
مقبول ومطبق (Accepted & Implemented)

#### السياق
الملفات المصورة والممسوحة ضوئياً (Scanned PDFs) قد تبدو ملفات صالحة للنظام لكنها لا تحتوي نصوصاً قابلة للاستخراج برمجياً بواسطة قارئات PDF القياسية، مما يؤدي إلى "نجاح وهمي" في القراءة دون العثور على أي التزام.

#### القرار
إلزام طبقة استخراج المستندات بتقييم كثافة النص المكتشف لكل صفحة وتصنيف الحالة إلى:
- `extraction_success`
- `partial_extraction`
- `low_quality`
- `OCR_required`
مع منع النظام من التظاهر بقراءة مستند إذا كانت جودة الاستخراج منخفضة، وإعلام المستخدم صراحة بضرورة المعالجة الضوئية.

#### الأساس العلمي والتقني
- **Document Engineering & Quality Assurance Standards:** مبادئ جودة البيانات الوصفية الرقمية (Data Quality Frameworks - Wang & Strong, 1996).
- **تصنيف الأساس:** **[Engineering Decision]** و **[Implemented Fact]**.

---

## المراجع العلمية والمصادر (References)

1. **Bench-Capon, T., et al.** (2012). *A history of AI and Law: 50 years of modeling legal reasoning*. Artificial Intelligence and Law, 20(3), 215-319. [DOI: 10.1007/s10506-012-9131-x]
2. **Darwish, K., & Magdy, W.** (2014). *Arabic Information Retrieval*. Foundations and Trends in Information Retrieval, 7(4), 239-342. [DOI: 10.1561/1500000031]
3. **Governatori, G., et al.** (2010). *Normative temporal reasoning: From logic to legal compliance*. International Journal of Cooperative Information Systems, 19(04), 297-326.
4. **Habash, N.** (2010). *Introduction to Arabic Natural Language Processing*. Synthesis Lectures on Human Language Technologies. Morgan & Claypool Publishers.
5. **Karpukhin, V., et al.** (2020). *Dense Passage Retrieval for Open-Domain Question Answering*. Proceedings of EMNLP 2020, 6769-6781.
6. **Fowler, M.** (2017). *Patterns of Distributed Systems: Event Sourcing & Immutable Infrastructure*. martinfowler.com.
7. **SDAIA AI Ethics Principles.** (2023). Saudi Data and Artificial Intelligence Authority, Riyadh, KSA.

---
**نهاية سجل القرارات المعمارية**
