# نموذج تشغيل الذكاء الاصطناعي والأمن والخصوصية في مآل

تاريخ الحالة: 8 أكتوبر 2026

## 1. دور الذكاء الاصطناعي

دور AI في مآل هو **دعم قرار قائم على الأدلة**:

- استخراج facts ومرشحات الالتزامات من نصوص موثقة.
- تلخيص سبب القرار والإشارة إلى الأدلة.
- اقتراح مسودة تصحيح أو مهمة.
- التوقف عند نقص الدليل أو التعارض.

ولا يملك صلاحية:

- اعتماد الانطباق أو المخالفة قانونيًا.
- اختلاق جهة أو مادة أو تاريخ أو قيمة.
- تنفيذ مهمة أو تعديل ملف شركة.
- تجاوز Reviewer أو إرسال نتيجة إلى GRC خارجي.
- تخزين أو عرض سلسلة التفكير الداخلية.

## 2. Simplified AI Architecture

الأولوية للقواعد ثم النموذج الاختياري:

1. **Deterministic:** hash، versions، dates، units، thresholds، idempotency وrevision.
2. **Retrieval:** مواد ومقاطع وأدلة فعلية بمعرفات وlocators.
3. **Optional LLM:** استخراج/تصنيف/صياغة عندما تفعّل المؤسسة Anthropic.
4. **Pydantic validation:** رفض JSON غير الصالح أو الحقول الخارجة عن العقد.
5. **Human gate:** أي task تبقى Draft حتى Reviewer.

الإعداد الافتراضي `MAAL_LLM_PROVIDER=deterministic`. عدم وجود مفتاح API لا يمنع رحلة الـMVP الأساسية.

## 3. سياسة القرارات

| المهمة | آلية التنفيذ | LLM | اعتماد إنساني |
|---|---|---:|---:|
| اكتشاف المصدر وحساب البصمة | قواعد | ممنوع | لا |
| مقارنة الأرقام والوحدات والتواريخ | قواعد | ممنوع | عند التعارض |
| استخراج fact أو obligation | قواعد أولًا، نموذج اختياري | مسموح | نعم |
| Applicability وGap | Evidence + قواعد uncertainty | مساعد فقط | نعم |
| صياغة Compliance Task | Draft فقط | مسموح | إلزامي |
| قرار قانوني أو تنفيذ خارجي | ممنوع | ممنوع | إنسان ونظام معتمد |

التمثيل التنفيذي لهذه السياسة موجود في `src/ai_policy.py` ويظهر دون أسرار عبر `GET /system/capabilities`.

## 4. Human-in-the-Loop

- الحالات `unknown` و`insufficient_evidence` و`conflicting_evidence` توقف العلاج.
- لا تنشأ مهمة إلا عند gap مثبت.
- Reviewer يستطيع approve/edit/reject.
- `expected_revision` يمنع اعتماد نسخة قديمة.
- القرار والفاعل والوقت وbefore/after hash تحفظ في Audit Trail.
- الإجراء الخارجي غير مسموح في الـMVP؛ GRC الحالي Local Adapter.

## 5. Data Security

### مطبق في الـMVP

- الأسرار من environment ولا تطبع في السجلات.
- CORS محصور بالعناوين المسموحة.
- تنزيل المصادر الرسمية عبر HTTPS وallowlist للجهات.
- SHA-256 ونسخ immutable وعدم استبدال الوثائق السابقة.
- حد لحجم الملف وقائمة صيغ محددة ومسارات تخزين آمنة.
- كشف prompt injection ومعاملة محتوى الوثيقة كبيانات غير موثوقة.
- حد لطول مدخل LLM، مهلة، إعادة محاولة محدودة وStructured Output عند دعمه.
- `token` authentication mode يربط المفتاح بهوية ودور ويتجاهل هيدرات الدور التي يرسلها العميل.

### مطلوب قبل Production

- SSO/OIDC وRBAC مركزي ودور مالك المنشأة.
- تشفير مخزن بمفاتيح KMS، rotation وsecret manager.
- malware scanning وcontent disarm للملفات.
- tenant isolation واختبارات authorization شاملة.
- SIEM، alerting، rate limiting وWAF.
- penetration test وdependency/container scanning.

## 6. Access Control

الأدوار الحالية:

- `admin`: المصادر، الرفع اليدوي والاستثناء الإلزامي.
- `analyst`: onboarding، scan، analysis وإنشاء draft.
- `reviewer`: القراءة وقرار task.

أوضاع المصادقة:

- `MAAL_AUTH_MODE=local`: للديمو المحلي، ويتطلب `X-Role` و`X-User-Id` صريحين.
- `MAAL_AUTH_MODE=token`: للـPilot، ويقرأ هوية ودورًا مربوطين بالمفتاح من `MAAL_API_KEYS_JSON`؛ لا يثق بهيدر الدور.

وضع token خطوة Pilot فقط، وليس بديلًا عن SSO في Production.

## 7. Data Privacy

- لا يحول inference إلى fact بلا evidence وlocator.
- يحفظ النص الأصلي ولا يترجمه أو يستبدله تدميريًا.
- لا يعرض internal IDs أو Audit Trail كاملًا افتراضيًا في الواجهة.
- لا يرسل الملف إلى مزود LLM في الوضع deterministic.
- `MAAL_DATA_RETENTION_DAYS=0` يعني أن الحذف الآلي غير مفعل إلى أن تعتمد المؤسسة سياسة واضحة.

قبل Pilot يجب توثيق: الغرض، مالك البيانات، التصنيف، موقع الاستضافة، retention، deletion، backup، legal hold، والموافقة على إرسال البيانات لأي مزود خارجي.

## 8. حالات الفشل الآمنة

- لا citation: لا حكم نهائي.
- وحدة أو أساس قياس غير متوافق: `insufficient_evidence`.
- أدلة متعارضة: `conflicting_evidence`.
- Scope غير مثبت: `Needs Review` بدل الاستبعاد القطعي.
- JSON نموذج غير صالح: رفض وإعادة محاولة محدودة ثم خطأ صريح.
- مصدر غير رسمي أو host غير مسموح: رفض الاتصال.
- ملف مصور بلا نص: `OCR_required`، لا ادعاء باستخراجه.

## 9. AI Evaluation Gate

لا يعتمد LLM حي قبل وجود مجموعة تقييم مفصولة عن prompt والتطوير، وتحتوي على العربية والإنجليزية وحالات النفي والاستثناء والتعارض ونقص الدليل والحقن. يجب قياس:

- Citation validity.
- Extraction precision/recall لكل نوع حقل.
- Applicability false exclusion rate.
- Unsupported-claim rate، والهدف صفر في المخرجات المعتمدة.
- Human override rate.
- نسبة JSON/schema failures والمهلات.

نجاح الاختبارات الحتمية لا يعد إثباتًا لدقة Anthropic الحية.
