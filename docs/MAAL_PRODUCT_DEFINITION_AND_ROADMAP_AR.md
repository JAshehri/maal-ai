# تعريف منتج مآل وخارطة الانتقال

تاريخ الحالة: 8 أكتوبر 2026
مرحلة المنتج: MVP قابل للعرض والاختبار، وليس خدمة إنتاجية متعددة العملاء.

## 1. وعد المنتج

مآل يحول التغير التنظيمي الرسمي إلى قرار قابل للتدقيق: ما الذي تغير، هل ينطبق على المنشأة، ما الملفات والإدارات المتأثرة، وما الإجراء المقترح قبل إيقاف التنفيذ لاعتماد إنساني.

النظام أداة دعم قرار. لا يقدم رأيًا قانونيًا نهائيًا، ولا يضمن الامتثال، ولا ينفذ تغييرًا تشغيليًا أو يرسل مهمة إلى نظام خارجي دون اعتماد.

## 2. المستخدمون الأساسيون

- **Compliance Analyst:** يرفع ملفات الشركة، يراجع نطاقها، يشغل المسح ويفحص النتائج.
- **Reviewer:** يعتمد المهمة أو يعدلها أو يرفضها مع تعليق وإصدار متوقع.
- **Admin:** يدير المصادر والنطاق الإلزامي والاستثناءات الإدارية.
- **Department Owner — Pilot:** يستقبل المهمة المعتمدة لاحقًا عبر GRC؛ غير منفذ كهوية مستقلة في الـMVP.

## 3. Current MVP

### داخل النطاق ويعمل حاليًا

- Onboarding متعدد الملفات: PDF وDOCX وXLSX وPPTX وTXT وCSV.
- Company Profile منسخ مع facts مرتبطة بالمصدر والموضع وطريقة الاستخراج.
- Mandatory Baseline مع مراجعة المستخدم ومنع إزالة الإلزامي لغير Admin.
- موصلان حيان فقط: NCA وSASO.
- نسخ تنظيمية immutable وبصمة SHA-256 وno-op عند عدم التغير.
- Applicability قبل Impact Analysis مع `Needs Review` عند نقص الدليل.
- مقارنة التغيرات، مراجعة ملف عند الطلب، score، citation وموضع finding.
- Dependency Graph، نافذة مراقبة 30 يومًا، مراجعة بشرية وسجل تدقيق.
- واجهة عربية RTL وإنجليزية LTR.
- Financial Exposure لا يظهر رقمًا دون input معتمد أو citation رسمي.

### خارج النطاق الحالي

- رأي قانوني أو اعتماد آلي.
- GRC خارجي حقيقي؛ الموجود Local Adapter فقط.
- OCR مُدار للملفات المصورة.
- SSO وmulti-tenancy وعزل قواعد بيانات العملاء.
- Connectors حية للعمل والخصوصية والتصدير.
- SLA وعامل مهام موزع ومراقبة إنتاجية.

## 4. Product Next Steps

### P0 — إغلاق الـPilot

1. اختيار منشأة Pilot ونطاق واحد محدد.
2. اعتماد مسؤول Compliance وReviewer ومالك بيانات.
3. تفعيل `MAAL_AUTH_MODE=token` بهويات منفصلة.
4. اعتماد سياسة الاحتفاظ والنسخ الاحتياطي والاستعادة.
5. اختبار 20–30 وثيقة حقيقية مع مراجعة بشرية للنتائج.
6. تسجيل false positive وfalse negative ووقت المراجعة لكل نتيجة.
7. منع أي استخدام إنتاجي إذا لم توجد citation أو Evidence locator صالح.

### P1 — Pilot مستقر

1. PostgreSQL وعامل خلفية منفصل.
2. SSO/RBAC مؤسسي وعزل منشآت.
3. OCR عربي مع مؤشر جودة وتوقف عند انخفاضها.
4. كتالوج منتجات وأصول موثوق لتحسين SASO Applicability.
5. Export حقيقي إلى GRC بعد الاعتماد البشري.
6. مراقبة connector drift وتنبيهات فشل المصدر.

### P2 — Production

1. Multi-tenancy وعزل تشفيري ومفاتيح مدارة.
2. High availability وqueue وdead-letter/replay.
3. سياسات retention/delete/legal hold قابلة للتنفيذ.
4. Observability وSLOs واختبارات حمل واختبارات اختراق.
5. إجراءات incident response وdisaster recovery.
6. تقييم نموذج حي ومراقبة drift قبل توسيع استخدام LLM.

## 5. MVP → Pilot → Production Gates

| البوابة | شرط الدخول | شرط الخروج |
|---|---|---|
| MVP | بيانات اختبار ومصادر رسمية | رحلة كاملة، no-op، citations، مراجعة بشرية، اختبارات حتمية ناجحة |
| Pilot | عميل ونطاق محدود ومالك بيانات | ≥95% citations صالحة، صفر تنفيذ بلا اعتماد، وقياس precision/recall ووقت المراجعة |
| Production | نتائج Pilot معتمدة وضوابط أمن | SSO، عزل، PostgreSQL، worker، backup/restore، monitoring، penetration test وSLA |

لا يجوز تسمية النظام Production-ready قبل استيفاء بوابة Production حتى لو نجح الديمو.

## 6. Future Features المؤجلة بقرار

- Connectors رسمية إضافية حسب Regulatory Scope، لا scraper عام.
- ترجمة قانونية منفصلة تحفظ الأصل دون استبداله.
- بحث دلالي بعد قياس قصور البحث النصي، وليس لمجرد تسمية النظام RAG.
- Collaboration وassignments وnotifications بعد تثبيت نموذج الصلاحيات.
- Analytics تاريخية وbenchmarking بعد وجود بيانات عملاء مصرح بها.
- API/adapter خارجي لـGRC مع idempotency وdelivery receipts.

## 7. Product Acceptance Metrics

- نسبة النتائج ذات citation وlocator صالحين.
- نسبة الوثائق unchanged التي لم تنشئ version أو task جديدة.
- زمن انتقال التغير من المصدر إلى Dashboard.
- Precision للـrelevant regulations وfalse exclusion rate.
- متوسط زمن المراجع من finding إلى قرار.
- نسبة `Needs Review` المغلقة بإضافة Evidence.
- عدد المهام المنشأة بلا gap مثبت: الهدف صفر.
- عدد الإجراءات الخارجية قبل الاعتماد: الهدف صفر.

هذه مقاييس قبول منتج وتشغيل، وليست ادعاءً بدقة قانونية أو ROI تجاري.
