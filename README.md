# مآل Maal

مآل نموذج أولي لوكيل يراقب التغير بين نسختين تنظيميتين، يستخرج الالتزامات المتأثرة فقط، يربطها بأدلة منشأة، ويحلل الانطباق والفجوة قبل صياغة مهمة تتوقف إلزاميًا عند مراجعة بشرية. النظام أداة دعم قرار، وليس مستشارًا قانونيًا أو ضمانًا للامتثال.

النسخة الحالية تستخدم آلة حالات دائمة واضحة بدل LangGraph. هذا قرار مقصود لتقليل اعتماديات الديمو مع الحفاظ على `thread_id` وcheckpoints والاستئناف ونقطة التوقف البشرية. يمكن استبدال المنسق لاحقًا دون تغيير عقود البيانات.

## ما هو حقيقي وما هو محاكاة

- حقيقي ومختبر حتميًا: تخزين النسخ والبصمات، استخراج المواد النصية، مقارنة النسخ، المقارنات الرقمية، حالات الانطباق والفجوة، منع التكرار، حفظ الحالة، المراجعة والإصدارات، وسجل التدقيق. ويشمل ذلك ingestion لملفات PDF/DOCX/XLSX/PPTX/TXT/CSV مع locators دقيقة، ومراجعة امتثال عند الطلب، وعلاقات أثر محفوظة في قاعدة البيانات.
- حي ومختبر: موصلا NCA وSASO يقرآن الفهارس الرسمية، يحفظان الملفات الأصلية والبصمات والنسخ غير القابلة للاستبدال، ويعاملان إعادة المسح دون تغير كـ no-op.
- محاكاة معلنة: سيناريو التغيير المقارن وملفا المنشأة والقياسات تحت `data/demo/`. ملف `sami_company_snapshot.json` سياق عرض اصطناعي ولا يمثل بيانات SAMI الفعلية.
- محاكاة معلنة: مدخلات التعرض المالي (المعالجة، التأخير، التوقف، والعقد) اصطناعية للديمو. لا يعرض النظام عقوبة مباشرة إلا عند وجود citation رسمي؛ وإلا يعرض `Not enough data`.
- اختياري وغير متحقق في هذه البيئة: استدعاء Anthropic الحي. الإعداد الافتراضي `deterministic`، وواجهة `LLMClient` موجودة لاستخدام المزود عند توفير المفتاح والاعتماديات.
- لا يوجد بحث متجهي. يسترجع النظام مقاطع مواد وأدلة فعلية بالمعرفات والكلمات والحقول المنظمة؛ لذلك لا يدعي وجود قاعدة vector أو تدريب نموذج جديد.

## الهيكل

```text
.
├── app.py                       # FastAPI والواجهة
├── migrations/001_initial.sql   # مخطط منصة التحليل
├── migrations/002_platform_expansion.sql # سجل المصادر والمسح وExport/GRC
├── migrations/003_core_differentiators.sql # مستندات المنشأة والاعتماد والمراجعة والتعرض
├── src/
│   ├── schemas.py               # عقود Source إلى RunState
│   ├── settings.py              # إعدادات ومسارات وتحميل .env
│   ├── db.py                    # migrations والمستودعات وعدم التكرار
│   ├── ingestion.py             # نسخ SHA-256 واستخراج المواد
│   ├── change_detection.py      # فرق الإضافة والحذف والقيم والموعد والنطاق
│   ├── retrieval.py             # استرجاع المواد والأدلة
│   ├── risk_rules.py            # مقارنة الأرقام والوحدات برمجيًا
│   ├── llm_client.py            # حد Anthropic القابل للاستبدال والتحقق
│   ├── pipeline.py              # آلة الحالات وcheckpoints والاستئناف
│   ├── company_documents.py     # استخراج متعدد الصيغ مع page/section/slide/sheet/cell/line
│   ├── compliance_review.py     # مراجعة عند الطلب وwatch window وdependency graph والتعرض
│   ├── review_service.py        # قبول وتعديل ورفض مع revision
│   ├── regulatory/              # NCA وSASO وManual Export/قطاع
│   ├── grc.py                   # GRCIntegrationService وLocal adapter
│   └── generate_report.py       # تقرير مبني من النتائج المحفوظة
├── static/                      # واجهة عربية RTL
├── data/demo/                   # مدخلات محاكاة بلا labels
├── eval/gold.jsonl              # النتائج المتوقعة منفصلة
└── tests/                       # وحدات ورحلة كاملة وصلاحيات
```

## متطلبات التشغيل

- Python 3.11 أو أحدث.
- SQLite المضمن مع Python.
- مفتاح Anthropic مطلوب فقط إذا غُيّر `MAAL_LLM_PROVIDER` إلى `anthropic`.

على Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

لا تضع مفتاحًا في الكود أو السجلات. اكتب `ANTHROPIC_API_KEY` محليًا في `.env` عند الحاجة فقط.

## تهيئة قاعدة البيانات

تعمل التهيئة تلقائيًا عند بدء التطبيق، ويمكن تنفيذها يدويًا من جذر المشروع:

```powershell
python -c "from src.db import init_db; init_db()"
```

إذا وُجد مخطط البداية القديم، تُنقل جداوله غير المتوافقة إلى جداول باسم `legacy_*` بدل حذفها.

## تشغيل الاختبارات

المجموعة الحتمية لا تحتاج مفتاح API:

```powershell
python -m unittest discover -s tests -v
```

تشمل: تغيرًا رقميًا، نسختين متطابقتين، تغيرًا تحريريًا، عدم الانطباق، نقص الدليل، تعارض الأدلة، النفي والاستثناء، اختلاف الوحدة، الاستئناف، منع تكرار المهمة، منع المراجع غير المخول، رفض revision قديم، حقن تعليمات داخل الوثيقة، الصيغ الست وlocators، ورحلة رفع مشروع يستخدم requirement قديم حتى score والـcitation والتعرض المالي.

## تشغيل الخلفية والواجهة

من جذر المشروع:

```powershell
uvicorn app:app --reload --port 8000
```

- الواجهة العربية: `http://127.0.0.1:8000/`
- توثيق API: `http://127.0.0.1:8000/docs`
- الجاهزية: `http://127.0.0.1:8000/ready`

الأدوار تمر في رؤوس الديمو: `X-Role: admin|analyst|reviewer` و`X-User-Id`. عند وضع `MAAL_API_TOKEN` يجب إرسال `X-API-Token` أيضًا. هذا RBAC أساسي للديمو، وليس بديلًا عن SSO في الإنتاج.

## نقاط API

- `POST /runs` يعيد `202` ويستخدم `idempotency_key`.
- `GET /runs/{id}` يعرض المرحلة وcheckpoint.
- `GET /runs/{id}/findings` يعرض النتائج والمهام والتدقيق.
- `POST /tasks/{id}/review` يفرض دور المراجع و`expected_revision`.
- `GET /runs/{id}/report` يولد تقريرًا من البيانات المحفوظة.
- `POST /sources` للمسؤول.
- `POST /documents/versions` يحفظ نسخة وبصمة وموادها.
- `GET /changes/{id}` يعرض قبل وبعد.
- `GET /health` للبقاء و`GET /ready` للجاهزية.
- `GET /regulatory-sources` و`GET /regulatory-documents` لسجل المصادر والوثائق.
- `POST /regulatory-scans` يعيد `202`، و`GET /regulatory-scans/{id}` يعرض التقدم والنتائج.
- `GET /regulatory-scans/{id}/changes` و`GET /dashboard/summary` للعرض والتقارير.
- `POST /export-sector/manual` و`POST /export-sector/manual/upload` للإدخال اليدوي الموثق فقط.
- `POST /grc/tasks` و`POST /grc/tasks/{id}/status` لمحول GRC المحلي التجريبي.
- `POST /company-documents/upload` لاستخراج ملف منشأة وحفظه وبصمته ومواضعه.
- `GET /company-documents` و`GET /company-documents/{id}` للوثائق والمقاطع والاعتمادات.
- `POST /compliance-reviews` لمراجعة وثيقة محفوظة، و`POST /compliance-reviews/upload` للرفع والمراجعة في طلب واحد.
- `GET /compliance-reviews/{id}` للنتيجة والـscore والاستشهاد والتعرض.
- `GET /compliance-reviews/{id}/report` يجمع نتيجة المراجعة مع impact graph والتوضيحات.
- `GET /impact-graph` لسلسلة `Regulation → Article → Obligation → Internal Document → Section → Department → Project` المخزنة فعليًا.
- `GET /ui/overview` يعيد View Model منقحًا للواجهة المؤسسية دون تغيير منطق التحليل أو عرض المعرفات الداخلية.

## الواجهة المؤسسية

الواجهة عبارة عن SPA عربية/إنجليزية بست صفحات واضحة: Dashboard، Regulatory Analysis، File Compliance Review، Impact Traceability، Financial Exposure، وHuman Review. تغيير اللغة يغيّر اتجاه الصفحة وكامل تسميات الواجهة، بينما يبقى النص التنظيمي الأصلي بلغته ولا يُترجم أو يُستبدل. النصوص الطويلة تظهر كملخص ويمكن فتح النص الكامل عند الطلب، وسجل التدقيق مخفي افتراضيًا داخل Technical Details.

مثال تشغيل عبر API:

```powershell
$headers = @{"X-Role"="analyst"; "X-User-Id"="demo-analyst"}
$context = Invoke-RestMethod http://127.0.0.1:8000/demo/context -Headers $headers
$body = @{
  company_snapshot_id = $context.company_snapshot_id
  old_version_id = $context.old_version_id
  new_version_id = $context.new_version_id
  idempotency_key = "jury-demo-0001"
} | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8000/runs -Method Post -Headers $headers -ContentType "application/json" -Body $body
```

## سيناريو الديمو المقترح

1. افتح الواجهة؛ تعرض سلسلة الاعتماد المحفوظة من المصدر حتى مشروع `Advanced Manufacturing Expansion` والسياسة الداخلية والسطر 3.
2. شغّل التحليل المحاكى واعرض تغير NOx من 100 إلى 80 والمادة 5.1 ونافذة المراقبة 30 يومًا.
3. في قسم On-Demand Review ارفع `data/demo/new_project_proposal.txt`.
4. اعرض تحذير `Recently superseded requirement detected` وscore = 0% والموضع الدقيق (السطر 5).
5. اعرض نص المشروع 100، والاستشهاد الحالي 80، والتعديل المقترح، والقسم والمشروع في dependency graph.
6. اعرض التعرض: remediation 120,000 + delay 150,000 + downtime 40,000 + contract 75,000 = 385,000 SAR. وضّح أن المدخلات اصطناعية وأن direct penalty هي `Not enough data`.
7. اختياريًا اعرض رحلة المهمة البشرية ومسار التدقيق. NCA/SASO مكتملان للـMVP ولا يلزم تشغيل scan حي أثناء عرض الـcore.

## الضوابط والقرارات الهندسية

- الوثائق التنظيمية تعامل كبيانات غير موثوقة، ولا تنفذ تعليماتها. يوجد اختبار حقن صريح.
- لا تتحول ثقة النموذج إلى احتمال صحة. تعرض النتيجة جودة المصدر وحداثة الدليل وصحة الاستشهاد وكفاية الانطباق منفصلة.
- المقارنات الرقمية والوحدات تنفذ بالقواعد. اختلاف الوحدة أو أساس القياس يوقف الحكم.
- غياب المستند من المستودع ينتج `insufficient_evidence`، لا مخالفة.
- النص الاختياري `may allow` لا يولد مخالفة لعدم الحصول على الامتياز.
- المهمة تنشأ فقط عندما تكون الحالة `gap`؛ ولا تنشأ لـ`unknown` أو نقص أو تعارض الأدلة.
- كل نتيجة تحمل التشغيل والمنشأة والمصدر والنسخة والنموذج وإصداري prompt وschema.
- CORS مقيد افتراضيًا بعناوين الواجهة المحلية الموجودة في `.env.example`.

## القيود الحالية وخارطة التوسع

- العامل داخل عملية FastAPI مناسب للديمو فقط. للإنتاج: عامل طابور منفصل ومراقبة وإعادة محاولات موزعة.
- SQLite مناسب لمستخدم واحد في العرض. عند تعدد العمال: PostgreSQL مع migrations معاملاتية وعزل منشآت.
- استخراج النص يدعم النصوص الحالية، وليس OCR/PDF العربي المتقدم.
- ملفات PDF المصورة تحتاج OCR غير موجود في MVP. DOCX/XLSX/PPTX تُقرأ من بنية OOXML؛ الرسومات والمعادلات والكائنات المضمنة لا تُحلل دلاليًا.
- استرجاع الـOn-Demand في الـMVP حتمي بالمادة والقيم المرتبطة بالتغييرات النشطة؛ التوسع يحتاج فهرس بحث كامل ومعجم مرادفات دون استبدال التحقق القاعدي.
- نافذة 30 يومًا تبدأ عند تسجيل التغيير في مآل، وتحتاج scheduler دوريًا لإغلاقها آليًا في التشغيل طويل الأمد.
- تواريخ SASO تُحفظ عندما تنشرها صفحة الفهرس؛ بعض الصفوف لا تعرض تاريخًا ولذلك تبقى القيمة فارغة بدل استنتاجها.
- تصنيف فئات SASO مبني على العنوان/الرابط ثم بوابة نطاق المنشأة؛ يحتاج الإنتاج كتالوج منتجات وأصول موثوقًا بدل ملف العرض الاصطناعي.
- موصل Export/Sector الحالي يدوي عن قصد إلى أن يُعتمد مصدر رسمي محدد؛ وGRC محول محلي فقط.
- SSO، تشفير مخزن مُدار، وسياسات الاحتفاظ المؤسسية خارج نطاق الديمو.
- جودة النموذج الحي غير مقاسة؛ لا تستخدم بيانات الاختبار الحتمية كدليل على دقة Anthropic.
- قبل الاستخدام التجاري يلزم تحقق قانوني/خصوصية/أمن ومراجعة تراخيص المصادر وتدفق البيانات.

## الملفات القديمة

احتُفظ بـ`data/regulation_source.txt` و`data/company_profile.txt` كمرجع legacy منقح. المسار النشط لا يستخدمهما، لأنهما كانا يخلطان النص والمدخلات مع تسميات الإجابة وافتراضات غير موثقة.
