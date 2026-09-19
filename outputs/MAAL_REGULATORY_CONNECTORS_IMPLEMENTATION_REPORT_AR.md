# تقرير تنفيذ موصلات المصادر التنظيمية — مآل

التاريخ: 19 سبتمبر 2026

## النتيجة التنفيذية

اكتمل مسار NCA وSASO الحي من زر `Run Regulatory Scan` إلى لوحة النتائج، مع حفظ الملفات الأصلية والبصمات والنسخ، وفلترة الانطباق قبل تحليل الأثر، وإثبات no-op عند عدم تغير المحتوى.

آخر تحقق حي من الواجهة:

- الحالة: `completed`
- الوثائق المكتشفة: 71 (66 SASO و5 NCA)
- النسخ الجديدة: 0
- الوثائق غير المتغيرة: 11
- المستبعدة أو المتوقفة لطلب معلومات: 60
- الأخطاء: 0
- تم تحديث `last_success_at` للمصدرين في بطاقات الواجهة.

التحقق السابق الذي أنشأ خط الأساس في قاعدة الديمو اكتشف 71 وثيقة وأنشأ النسخ المؤهلة، ثم أعطت إعادة المسح 0 نسخة جديدة. اختبار NCA المنفصل الموجود في `work/nca_live.db` سبق أن حمّل العائلات الخمس الرسمية وأثبت 5 unchanged / 0 new / 0 errors. واختبار SASO المركز في `work/saso_live.db` اكتشف 66 سجلًا من الفهرس الرسمي وحمّل عينتين إلكترونيتين، ثم أثبت 2 unchanged / 0 new / 0 errors.

## ما تم فعليًا

- موصل NCA HTML رسمي لعائلات ECC وCSCC وCCC وOTCC وDCC.
- موصل SASO HTML/ASP.NET يوسّع حجم صفحة الفهرس، ويستخرج العنوان والفئة وتواريخ الاعتماد والنشر والتطبيق عندما تكون منشورة، ورابط الملف الرسمي.
- تنزيل آمن من النطاقات الرسمية فقط، حجم أقصى، مهلة، ومحاولتا إعادة كحد أعلى.
- تخزين immutable للملف الأصلي تحت `data/regulatory/raw` باستخدام SHA-256.
- ربط النسخة الجديدة بالسابقة وتشغيل change detection فقط عند تغير البصمة.
- `sami_company_snapshot.json` اصطناعي وموسوم بوضوح بأنه لا يمثل بيانات SAMI الحقيقية.
- بوابة Applicability قبل التنزيل والتحليل: `not_applicable` و`needs_review` لا تدخلان impact analysis، ولا تُنشئان findings أو tasks.
- تضييق SASO إلى الإلكترونيات/الأجهزة/المكونات المثبتة، مع إيقاف المركبات والمصاعد والسكوتر ومواد البناء ونطاقات المنتجات غير المثبتة عند `needs_review`.
- ربط التغيرات المنطبقة فقط بالـpipeline الحالي عبر `analysis_run_id`.
- لوحة عربية تعرض المصدر، اللائحة، old/new، الانطباق، القسم، الأولوية، الملفات المتأثرة، والتعرض المالي. لا تُختلق ملفات أو مبالغ؛ تظهر `Not enough data` عند غياب الدليل.
- `ExportSectorRegulationConnector` مع Manual Connector ونقطتي إدخال JSON/upload محميتين بدور admin.
- `GRCIntegrationService` مع `LocalGRCAdapter` يدعم الإنشاء، تحديث الحالة، إرفاق الدليل، تعيين المالك، الأولوية والموعد.
- تحديث README و`.env.example` وتشغيل كامل رحلة الواجهة وزر التحليل والمراجعة المحفوظة.

## ما لم يتم

- لا يوجد scraper عام لـExport Control؛ الإدخال يدوي إلى أن يعتمد مالك المنتج مصدرًا رسميًا محددًا.
- لا يوجد تكامل GRC خارجي؛ المحول محلي للديمو.
- لا توجد بيانات منتجات أو أصول SAMI فعلية؛ لذلك بعض النتائج تبقى `needs_review` عمدًا.
- لا توجد قيم مالية أو ملفات داخلية موثقة للمنشأة؛ لا يعرض النظام أرقامًا أو أسماء ملفات مفترضة.
- لم يُختبر Anthropic حيًا؛ الاختبارات تستخدم المسار الحتمي ولا تحتاج مفتاح API.

## نقاط API المضافة

- `GET /regulatory-sources`
- `GET /regulatory-documents`
- `POST /regulatory-scans` (`202`)
- `GET /regulatory-scans/{scan_id}`
- `GET /regulatory-scans/{scan_id}/changes`
- `GET /dashboard/summary`
- `POST /export-sector/manual`
- `POST /export-sector/manual/upload`
- `POST /grc/tasks`
- `POST /grc/tasks/{grc_task_id}/status`

## Migration

`migrations/002_platform_expansion.sql` مطبق في `maal.db` بعد `001_initial.sql`. أضاف سجل المصادر الموسع، الوثائق التنظيمية، تشغيلات المسح، أحداث الجلب، نتائج الوثائق، Export/Sector، وGRC، وفهارسها، إضافة إلى حقول النسخة الأصلية ومسار التخزين و`document_id`.

## الاختبارات

- `python -m pytest -q`: **27 passed**, وتحذيران deprecation من TestClient فقط.
- `node --check static/app.js`: نجح.
- رحلة الواجهة الحية: نجحت من الزر إلى Dashboard ثم إعادة المسح no-op، وبعدها تشغيل pipeline المحاكى وعرض results/task/audit.
- يغطي الاختبار الإضافي منع تنزيل SASO غير المرتبط، إيقاف NCA عند غياب حقيقة النطاق، منع اعتبار التصنيع العام دليل منتج محدد، ومنع كلمة Electrical وحدها من إثبات نطاق مركبة.

## الملفات الرئيسية المعدلة أو المضافة

- `app.py`, `README.md`, `.env.example`, `requirements.txt`
- `migrations/002_platform_expansion.sql`
- `src/db.py`, `src/schemas.py`, `src/settings.py`, `src/demo.py`
- `src/check_applicability.py`, `src/gap_analysis.py`, `src/generate_task.py`
- `src/regulatory/applicability.py`, `discovery.py`, `extraction.py`, `manual.py`, `registry.py`
- `src/regulatory/connectors/base.py`, `nca.py`, `saso.py`, `export_sector.py`
- `src/grc.py`
- `data/demo/sami_company_snapshot.json`
- `static/index.html`, `static/styles.css`, `static/app.js`
- `tests/test_api.py`, `tests/test_connectors.py`
- `work/run_live_nca.py`, `work/run_live_saso.py`

تعذر تقديم `git diff` لأن مجلد العمل المستلم لا يحتوي مستودع `.git` مستقلًا؛ لم تُنشأ مستودعات أو فروع ولم يُدفع أي شيء خارجيًا.

## طريقة التشغيل

```powershell
cd "C:\Users\JoudA\Documents\Codex\2026-09-17\lead-software-engineer-maal-maal-ai"
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -c "from src.db import init_db; init_db()"
uvicorn app:app --host 127.0.0.1 --port 8000
```

افتح `http://127.0.0.1:8000/` ثم اضغط `Run Regulatory Scan`. يلزم اتصال إنترنت يسمح بالوصول إلى النطاقين الرسميين. توثيق API في `http://127.0.0.1:8000/docs`.

## أفضل ترتيب للعرض أمام اللجنة

1. وضّح الفرق بين المصادر الحية وسيناريو التغيير المحاكى.
2. اعرض NCA وSASO و`last_success_at` ثم اضغط Run Regulatory Scan.
3. أبرز أن المركبات/المصاعد تظهر `needs_review` ولا تدخل التحليل، بينما ECC/OTCC/DCC ولوائح الإلكترونيات الموثقة تظهر applicable.
4. أعد المسح وأبرز 0 new وعداد unchanged.
5. مرّر على أعمدة evidence/files/financial exposure وأكد الامتناع عن اختلاق قيم.
6. اضغط تشغيل التحليل لعرض old/new والفجوة والتعارض ونقص الدليل.
7. افتح المهمة ومسار التدقيق، واشرح revision والمراجعة البشرية وعدم التكرار.
8. اختم بـManual Export/Sector وLocal GRC كنقطتي توسع منظمتين.

