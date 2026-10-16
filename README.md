# مآل Maal

مآل نموذج أولي لوكيل يراقب التغير بين نسختين تنظيميتين، يستخرج الالتزامات المتأثرة فقط، يربطها بأدلة منشأة، ويحلل الانطباق والفجوة قبل صياغة مهمة تتوقف إلزاميًا عند مراجعة بشرية. النظام أداة دعم قرار، وليس مستشارًا قانونيًا أو ضمانًا للامتثال.

النسخة الحالية تستخدم آلة حالات دائمة واضحة بدل LangGraph. هذا قرار مقصود لتقليل اعتماديات الديمو مع الحفاظ على `thread_id` وcheckpoints والاستئناف ونقطة التوقف البشرية. يمكن استبدال المنسق لاحقًا دون تغيير عقود البيانات.

## وضع التشغيل الحقيقي ووضع العرض

- حقيقي ومختبر حتميًا: تخزين النسخ والبصمات، استخراج المواد النصية، مقارنة النسخ، المقارنات الرقمية، حالات الانطباق والفجوة، منع التكرار، حفظ الحالة، المراجعة والإصدارات، وسجل التدقيق. ويشمل ذلك ingestion لملفات PDF/DOCX/XLSX/PPTX/TXT/CSV مع locators دقيقة، ومراجعة امتثال عند الطلب، وعلاقات أثر محفوظة في قاعدة البيانات.
- حي ومختبر: موصلا NCA وSASO يقرآن الفهارس الرسمية، يحفظان الملفات الأصلية والبصمات والنسخ غير القابلة للاستبدال، ويعاملان إعادة المسح دون تغير كـ no-op.
- الوضع الافتراضي حقيقي: `DEMO_MODE=false`. لا تُزرع لوائح أو ملفات منشأة أو نتائج أو قيم مالية اصطناعية عند بدء التطبيق. تبدأ قاعدة البيانات النظيفة بصفحة Onboarding ثم Dashboard فارغة حتى يشغّل المستخدم المسح الحي.
- بيانات العرض باقية تحت `data/demo/` للاختبارات والعرض الاحتياطي فقط، ولا تُستخدم إلا عند ضبط `DEMO_MODE=true` صراحةً. ملف `sami_company_snapshot.json` اصطناعي ولا يمثل بيانات SAMI الفعلية.
- لا يعرض الوضع الحقيقي تعرضًا ماليًا إلا من مدخلات شركة معتمدة أو citation رسمي. عند غيابها يعرض `Not enough data`.
- اختياري وغير متحقق في هذه البيئة: استدعاء Anthropic الحي. الإعداد الافتراضي `deterministic`، وواجهة `LLMClient` موجودة لاستخدام المزود عند توفير المفتاح والاعتماديات.
- لا يوجد بحث متجهي. يسترجع النظام مقاطع مواد وأدلة فعلية بالمعرفات والكلمات والحقول المنظمة؛ لذلك لا يدعي وجود قاعدة vector أو تدريب نموذج جديد.

## الهيكل

```text
.
├── app.py                       # FastAPI والواجهة
├── migrations/001_initial.sql   # مخطط منصة التحليل
├── migrations/002_platform_expansion.sql # سجل المصادر والمسح وExport/GRC
├── migrations/003_core_differentiators.sql # مستندات المنشأة والاعتماد والمراجعة والتعرض
├── migrations/004_real_company_onboarding.sql # ملف الشركة المنسخ والنطاق وأدلة الاستخراج
├── migrations/006_local_user_authentication.sql # حسابات المدير والموظف والجلسات
├── migrations/007_requirement_assessments_and_feedback.sql # مطابقة المتطلبات وتصحيح الموظف
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
│   ├── onboarding.py            # استخراج ملف الشركة والنطاق الإلزامي والمراجعة والاعتماد
│   ├── requirement_matching.py  # موضع الدليل وحالة التطبيق والمقارنات الرقمية
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
python -m pytest tests -q
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

التشغيل العادي لا يحتاج تعديلًا لأن `.env.example` يضبط `DEMO_MODE=false`. لتشغيل العرض الاحتياطي فقط:

```powershell
$env:DEMO_MODE="true"
uvicorn app:app --reload --port 8000
```

عند أول فتح تظهر شاشة إعداد لإنشاء مدير النظام. بعد ذلك يكون الدخول باسم مستخدم وكلمة مرور، وتُحفظ كلمات المرور باستخدام PBKDF2 ولا تُخزن كنص صريح. المدير يستطيع إدارة المستخدمين واعتماد ملف الشركة وحذف الملفات واتخاذ قرار المراجعة البشرية؛ موظف الامتثال يستطيع الاطلاع ورفع الأدلة وتشغيل المسح والمراجعات. جلسة الويب صالحة 12 ساعة ويمكن إلغاؤها بتسجيل الخروج. تظل رؤوس `X-Role` و`X-User-Id` متاحة للاختبارات والتكامل المحلي القديم فقط، وليست آلية دخول الواجهة.

## نقاط API

- `GET /auth/status` يحدد هل تم إنشاء المدير الأول.
- `POST /auth/setup` ينشئ أول مدير مرة واحدة فقط، و`POST /auth/login` ينشئ جلسة دخول.
- `GET /auth/me` يعيد المستخدم الحالي، و`POST /auth/logout` يلغي الجلسة.
- `GET /auth/users` و`POST /auth/users` لإدارة الحسابات بصلاحية المدير فقط.
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
- `GET /onboarding/status` يعيد حالة إعداد الشركة أو Empty State الحقيقي.
- `POST /onboarding/documents` يقبل ملفات متعددة ويستخرج facts مع المصدر والموضع والثقة والطريقة.
- `POST /onboarding/{company_id}/approve` يعتمد النسخة والنطاق مع حماية المجالات الإلزامية.
- `GET /ui/live-overview` يعيد View Model من بيانات الشركة والمسح الحي فقط، دون Demo fallback.
- `GET /regulatory-scans/{id}/changes` و`GET /dashboard/summary` للعرض والتقارير.
- `POST /export-sector/manual` و`POST /export-sector/manual/upload` للإدخال اليدوي الموثق فقط.
- `POST /grc/tasks` و`POST /grc/tasks/{id}/status` لمحول GRC المحلي التجريبي.
- `POST /company-documents/upload` لاستخراج ملف منشأة وحفظه وبصمته ومواضعه.
- `GET /company-documents` و`GET /company-documents/{id}` للوثائق والمقاطع والاعتمادات.
- `POST /compliance-reviews` لمراجعة وثيقة محفوظة، و`POST /compliance-reviews/upload` للرفع والمراجعة في طلب واحد.
- `GET /compliance-reviews/{id}` للنتيجة والـscore والاستشهاد والتعرض.
- `GET /compliance-reviews/{id}/report` يجمع نتيجة المراجعة مع impact graph والتوضيحات.
- `GET /impact-graph` لسلسلة `Regulation → Article → Obligation → Internal Document → Section → Department → Project` المخزنة فعليًا.
- `POST /analysis-feedback` لتأكيد أو رفض وتصحيح قرار الانطباق أو حالة تطبيق المتطلب مع حفظ هوية الموظف وبصمة الدليل.
- `GET /ui/overview` خاص بوضع `DEMO_MODE=true` ويرجع 404 في الوضع العادي.

## الواجهة المؤسسية

الواجهة عبارة عن SPA عربية/إنجليزية بصفحات واضحة تشمل Dashboard، Regulatory Analysis، File Compliance Review، Impact Traceability، Human Review، وإدارة المستخدمين للمدير. تظهر Financial Exposure فقط عند وجود مدخلات فعلية ومعتمدة. تغيير اللغة يغيّر اتجاه الصفحة وكامل تسميات الواجهة، بينما يبقى النص التنظيمي الأصلي بلغته ولا يُترجم أو يُستبدل. يعرض التحليل اسم ملف الشركة والموضع الدقيق وحالة تطبيق كل متطلب، ويستطيع موظف الامتثال تأكيد أو رفض وتصحيح تصنيف الوكيل مع تعليق. تعرض نتيجة مراجعة الملف اسم الملف والموضع الدقيق حسب الصيغة (السطر أو الصفحة أو القسم/الفقرة أو الشريحة أو الورقة/الخلية)، والنص غير المتوافق، والاستشهاد الحالي، والتصحيح المقترح. النصوص الطويلة تظهر كملخص ويمكن فتح النص الكامل عند الطلب، وسجل التدقيق مخفي افتراضيًا داخل Technical Details.

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

## سيناريو التشغيل الحقيقي

1. افتح قاعدة بيانات نظيفة؛ تظهر صفحة Onboarding بدل Dashboard.
2. ارفع عدة ملفات PDF/DOCX/XLSX/PPTX/TXT/CSV تصف الشركة.
3. راجع facts المستخرجة وأدلتها والـRegulatory Scope؛ المجالات الإلزامية لا يمكن للمحلل حذفها.
4. اعتمد ملف الشركة؛ تظهر Dashboard فارغة من اللوائح والقيم المصطنعة.
5. اضغط **تحديث البيانات التنظيمية**؛ ينشئ الزر `POST /regulatory-scans` ويشغّل NCA وSASO فقط.
6. راجع New / Updated / Unchanged / Filtered / Needs Review / Errors ووقت آخر تحديث.
7. أعد التحديث دون تغير؛ يجب أن تظهر النتائج `Unchanged` ورسالة عدم وجود تحديثات جديدة دون إنشاء تغيير وهمي.

## الضوابط والقرارات الهندسية

مرجع إغلاق قسم المنتج: [docs/MAAL_PRODUCT_DEFINITION_AND_ROADMAP_AR.md](docs/MAAL_PRODUCT_DEFINITION_AND_ROADMAP_AR.md).
مرجع دور AI والأمن والخصوصية: [docs/MAAL_AI_SECURITY_OPERATING_MODEL_AR.md](docs/MAAL_AI_SECURITY_OPERATING_MODEL_AR.md).
التقرير التفصيلي للمنظومة والمطابقة والمراجعة البشرية: [docs/MAAL_SYSTEM_DETAILED_REPORT_AR.md](docs/MAAL_SYSTEM_DETAILED_REPORT_AR.md).

- الوثائق التنظيمية تعامل كبيانات غير موثوقة، ولا تنفذ تعليماتها. يوجد اختبار حقن صريح.
- لا تتحول ثقة النموذج إلى احتمال صحة. تعرض النتيجة جودة المصدر وحداثة الدليل وصحة الاستشهاد وكفاية الانطباق منفصلة.
- المقارنات الرقمية والوحدات تنفذ بالقواعد. اختلاف الوحدة أو أساس القياس يوقف الحكم.
- غياب المستند من المستودع ينتج `insufficient_evidence`، لا مخالفة.
- النص الاختياري `may allow` لا يولد مخالفة لعدم الحصول على الامتياز.
- المهمة تنشأ فقط عندما تكون الحالة `gap`؛ ولا تنشأ لـ`unknown` أو نقص أو تعارض الأدلة.
- كل نتيجة تحمل التشغيل والمنشأة والمصدر والنسخة والنموذج وإصداري prompt وschema.
- CORS مقيد افتراضيًا بعناوين الواجهة المحلية الموجودة في `.env.example`.
- `GET /system/capabilities` يعرض مرحلة المنتج والميزات الحقيقية وسياسة AI وحالة المصادقة دون مفاتيح أو معرفات داخلية.
- وضع `local` يتطلب هوية مستخدم صريحة. للـPilot استخدم `MAAL_AUTH_MODE=token` ومفاتيح مربوطة بهوية ودور؛ هذا لا يغني عن SSO في الإنتاج.

## القيود الحالية وخارطة التوسع

- العامل داخل عملية FastAPI مناسب للديمو فقط. للإنتاج: عامل طابور منفصل ومراقبة وإعادة محاولات موزعة.
- SQLite مناسب لمستخدم واحد في العرض. عند تعدد العمال: PostgreSQL مع migrations معاملاتية وعزل منشآت.
- نشر Render المجاني الحالي يستخدم SQLite وتخزين الملفات داخل `/tmp`؛ قد يفقد بياناته عند إعادة التشغيل أو إعادة النشر، وقد يتأخر أول طلب بسبب الاستيقاظ البارد. هذا مناسب لعرض مؤقت فقط وليس توافرًا إنتاجيًا.
- تنزيل الوثائق المتوافقة متوازٍ بصورة محدودة. يمكن ضبطه عبر `MAAL_CONNECTOR_CONCURRENCY`؛ القيمة الافتراضية 4 لتقليل الزمن دون الضغط على المواقع الرسمية.
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
