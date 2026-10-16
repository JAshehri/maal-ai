from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import db
from .document_processing import SUPPORTED_EXTENSIONS, extract_document_content
from .schemas import CompanySnapshot
from .settings import settings


DOMAINS = [
    ("employment_labor", "العمل والتوظيف", "Employment / Labor", None),
    ("data_privacy", "خصوصية البيانات", "Data Privacy", None),
    ("cybersecurity", "الأمن السيبراني", "Cybersecurity", "NCA"),
    ("product_conformity", "مواصفات المنتجات والمطابقة", "Product Standards / Conformity", "SASO"),
    ("export_control", "الاستيراد والتصدير والرقابة على الصادرات", "Import / Export / Export Control", None),
    ("procurement_supply", "المشتريات وسلسلة الإمداد", "Procurement / Supply Chain", None),
]

BOOLEAN_RULES = {
    "has_employees": [r"\bemployees?\b", r"\bworkforce\b", r"\bstaff\b", r"موظف", r"العاملين"],
    "processes_personal_data": [r"personal data", r"personally identifiable", r"بيانات شخصية", r"بيانات الموظفين"],
    "uses_information_systems": [r"information systems?", r"IT systems?", r"network infrastructure", r"نظم المعلومات", r"أنظمة معلومات"],
    "manufactures_products": [r"\bmanufactur(?:e|es|ing)\b", r"production facilit", r"نصنع", r"تصنيع", r"مصنع"],
    "has_suppliers": [r"\bsuppliers?\b", r"supply chain", r"مورد", r"سلسلة الإمداد"],
    "imports_or_exports": [r"\bimports?\b", r"\bexports?\b", r"import/export", r"استيراد", r"تصدير"],
    "uses_cloud": [r"cloud services?", r"cloud platform", r"الحوسبة السحابية", r"خدمات سحابية"],
    "uses_operational_technology": [r"operational technology", r"\bOT systems?\b", r"أنظمة التشغيل الصناعية"],
    "operates_critical_systems": [r"critical systems?", r"critical infrastructure", r"أنظمة حساسة", r"بنية تحتية حرجة"],
    "handles_electronics": [r"electronics?", r"electronic control", r"embedded systems?", r"إلكترون", r"أنظمة مدمجة"],
}

LIST_PREFIXES = {
    "business_activities": ["activities", "business activities", "الأنشطة", "نشاط الشركة"],
    "products_services": ["products", "services", "products and services", "المنتجات", "الخدمات"],
    "departments": ["departments", "department", "الإدارات", "الإدارة"],
    "technologies": ["technologies", "technology", "التقنيات", "التقنية"],
    "materials": ["materials", "المواد"],
    "facilities": ["facilities", "facility", "المنشآت", "المنشأة"],
    "suppliers": ["suppliers", "الموردون", "الموردين"],
    "customers": ["customers", "العملاء"],
    "partnerships": ["partnerships", "الشراكات"],
    "certifications_licenses": ["certifications", "licenses", "الشهادات", "التراخيص"],
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def seed_regulatory_domains(db_path=None) -> None:
    with db.connect(db_path) as connection:
        for code, ar, en, connector in DOMAINS:
            connection.execute(
                """INSERT OR IGNORE INTO regulatory_domains
                   (domain_id, code, name_ar, name_en, connector_authority, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (db.stable_id("domain", code), code, ar, en, connector, _now()),
            )


def _fact_matches(text: str) -> list[tuple[str, Any, float, str]]:
    lower = text.casefold()
    facts: list[tuple[str, Any, float, str]] = []
    for fact_type, patterns in BOOLEAN_RULES.items():
        matched = next((pattern for pattern in patterns if re.search(pattern, lower, re.I)), None)
        if matched:
            if fact_type == "imports_or_exports" and re.search(
                r"(?:imports?|exports?|import/export|استيراد|تصدير).{0,50}(?:not confirmed|unknown|needs confirmation|غير مؤكد|غير معروف)",
                lower,
                re.I,
            ):
                continue
            negative = bool(re.search(
                rf"(?:\b(?:no|not|without)\b|لا يوجد|لا تقوم).{{0,24}}{matched}", lower, re.I
            ))
            facts.append((fact_type, not negative, 0.95 if not negative else 0.9, f"deterministic_pattern:{matched}"))
    for fact_type, prefixes in LIST_PREFIXES.items():
        for prefix in prefixes:
            match = re.search(rf"(?:^|\b){re.escape(prefix)}\s*[:\-]\s*(.+)$", text, re.I)
            if match:
                values = [item.strip(" .") for item in re.split(r"[,;،]", match.group(1)) if item.strip(" .")]
                if values:
                    facts.append((fact_type, values, 1.0, f"explicit_label:{prefix}"))
                break
    jurisdictions = []
    for value, patterns in {
        "SA": [r"Saudi Arabia", r"Kingdom of Saudi Arabia", r"KSA", r"المملكة العربية السعودية"],
        "AE": [r"United Arab Emirates", r"UAE", r"الإمارات العربية المتحدة"],
        "DE": [r"Germany", r"ألمانيا"], "US": [r"United States", r"USA", r"الولايات المتحدة"],
    }.items():
        if any(re.search(pattern, text, re.I) for pattern in patterns):
            jurisdictions.append(value)
    if jurisdictions:
        facts.append(("jurisdictions", jurisdictions, 1.0, "explicit_jurisdiction_mention"))
    regulators = [name for name in ("NCA", "SASO") if re.search(rf"\b{name}\b", text, re.I)]
    if regulators:
        facts.append(("regulators_referenced", regulators, 1.0, "explicit_regulator_mention"))
    manufacture = re.search(r"(?:manufactur(?:e|es|ing)|نصنع|تصنيع)\s+(.{3,100})", text, re.I)
    if manufacture:
        value = manufacture.group(1).strip(" .")
        facts.append(("products_services", [value], 0.9, "deterministic_manufacturing_phrase"))
    return facts


def _insert_fact(*, profile_version_id: str, document_id: str, chunk_id: str,
                 locator: dict, fact_type: str, value: Any, confidence: float,
                 method: str, db_path=None) -> str:
    value_json = _json(value)
    fact_id = db.stable_id("fact", profile_version_id, fact_type, chunk_id, value_json)
    with db.connect(db_path) as connection:
        connection.execute(
            """INSERT OR IGNORE INTO extracted_company_facts
               (fact_id, profile_version_id, fact_type, value_json, source_document_id,
                source_chunk_id, locator_json, confidence, extraction_method, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (fact_id, profile_version_id, fact_type, value_json, document_id, chunk_id,
             _json(locator), confidence, method, _now()),
        )
    return fact_id


def _merged_facts(profile_version_id: str, db_path=None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with db.connect(db_path) as connection:
        rows = connection.execute(
            """SELECT f.*, d.filename FROM extracted_company_facts f
               JOIN onboarding_documents d ON d.onboarding_document_id=f.source_document_id
               WHERE f.profile_version_id=? ORDER BY f.fact_type, f.created_at""", (profile_version_id,)
        ).fetchall()
    details, merged = [], {}
    for row in rows:
        item = dict(row); value = json.loads(item.pop("value_json")); locator = json.loads(item.pop("locator_json"))
        details.append({"fact_id": item["fact_id"], "type": item["fact_type"], "value": value,
                        "source_document": item["filename"], "locator": locator,
                        "confidence": item["confidence"], "extraction_method": item["extraction_method"]})
        current = merged.get(item["fact_type"])
        if isinstance(value, list):
            merged[item["fact_type"]] = list(dict.fromkeys((current or []) + value))
        elif current is None or value is True:
            merged[item["fact_type"]] = value
    return merged, details


def _build_scope(profile_version_id: str, facts: dict[str, Any], fact_details: list[dict[str, Any]], db_path=None) -> None:
    seed_regulatory_domains(db_path)
    rules = {
        "employment_labor": ("has_employees", "Mandatory baseline because employee presence is evidenced."),
        "data_privacy": ("processes_personal_data", "Mandatory baseline because personal data processing is evidenced."),
        "cybersecurity": ("uses_information_systems", "Mandatory baseline because information systems are evidenced."),
        "product_conformity": ("manufactures_products", "Mandatory baseline because manufacturing is evidenced."),
        "export_control": ("imports_or_exports", "Mandatory baseline because import/export activity is evidenced."),
        "procurement_supply": ("has_suppliers", "Mandatory baseline because suppliers are evidenced."),
    }
    with db.connect(db_path) as connection:
        domains = {row["code"]: dict(row) for row in connection.execute("SELECT * FROM regulatory_domains")}
    for code, (fact_type, rationale) in rules.items():
        value = facts.get(fact_type)
        if value is True:
            classification, status = "mandatory", "proposed"
        elif code == "export_control" and facts.get("manufactures_products") is True:
            classification, status, rationale = "needs_confirmation", "proposed", "Manufacturing is evidenced, but import/export activity is unknown."
        else:
            continue
        domain = domains[code]; scope_id = db.stable_id("scope", profile_version_id, code)
        with db.connect(db_path) as connection:
            connection.execute(
                """INSERT OR IGNORE INTO company_regulatory_scope
                   (scope_id, profile_version_id, domain_id, classification, status,
                    admin_override, rationale, created_at) VALUES (?, ?, ?, ?, ?, 0, ?, ?)""",
                (scope_id, profile_version_id, domain["domain_id"], classification, status, rationale, _now()),
            )
        for fact in fact_details:
            if fact["type"] == fact_type or (code == "export_control" and fact["type"] == "manufactures_products"):
                with db.connect(db_path) as connection:
                    source = connection.execute("SELECT source_document_id, source_chunk_id, locator_json FROM extracted_company_facts WHERE fact_id=?", (fact["fact_id"],)).fetchone()
                    connection.execute(
                        """INSERT OR IGNORE INTO regulatory_scope_evidence
                           (scope_evidence_id, scope_id, fact_id, source_document_id, source_chunk_id, locator_json, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (db.stable_id("scopeev", scope_id, fact["fact_id"]), scope_id, fact["fact_id"],
                         source["source_document_id"], source["source_chunk_id"], source["locator_json"], _now()),
                    )


def create_profile_from_documents(
    *,
    company_name: str,
    files: list[tuple[str, str, bytes]],
    db_path=None,
    retain_existing: bool = True,
) -> dict[str, Any]:
    if not files:
        raise ValueError("at least one company document is required")
    company_id = db.stable_id("company", company_name.casefold())
    now = _now()

    # Validate and extract every document before changing the active profile.
    # A bad/empty file must never leave a half-created company whose
    # current_version_id points to nothing.
    candidate_files = list(files)
    with db.connect(db_path) as connection:
        profile = connection.execute("SELECT * FROM company_profiles WHERE company_id=?", (company_id,)).fetchone()
        if profile and retain_existing:
            previous_documents = connection.execute(
                "SELECT filename, mime_type, storage_uri, sha256 FROM onboarding_documents WHERE profile_version_id=?",
                (profile["current_version_id"],),
            ).fetchall()
            supplied_hashes = {hashlib.sha256(raw).hexdigest() for _, _, raw in candidate_files}
            for prior in previous_documents:
                prior_path = (settings.root_dir / prior["storage_uri"]).resolve()
                if prior["sha256"] not in supplied_hashes and prior_path.exists():
                    candidate_files.append((prior["filename"], prior["mime_type"], prior_path.read_bytes()))

    prepared: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for filename, mime_type, raw in candidate_files:
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"unsupported company document format: {suffix or 'none'}")
        if not raw:
            raise ValueError(f"empty company document was removed: {filename}")
        digest = hashlib.sha256(raw).hexdigest()
        if digest in seen_hashes:
            continue
        extraction = extract_document_content(raw, filename)
        if not extraction.chunks:
            if extraction.overall_quality == "OCR_required":
                raise ValueError(f"document requires OCR and contains no extractable text: {filename}")
            raise ValueError(f"document contains no extractable text: {filename}")
        seen_hashes.add(digest)
        prepared.append({
            "filename": filename,
            "mime_type": mime_type,
            "raw": raw,
            "suffix": suffix,
            "digest": digest,
            "extraction": extraction,
        })
    if not prepared:
        raise ValueError("at least one non-empty company document is required")

    with db.connect(db_path) as connection:
        profile = connection.execute("SELECT * FROM company_profiles WHERE company_id=?", (company_id,)).fetchone()
        if not profile:
            connection.execute("INSERT INTO company_profiles VALUES (?, ?, NULL, 'onboarding', ?, ?)", (company_id, company_name, now, now))
        version_no = connection.execute(
            "SELECT COALESCE(MAX(version_no),0)+1 FROM company_profile_versions WHERE company_id=?",
            (company_id,),
        ).fetchone()[0]
        profile_version_id = db.stable_id("profilev", company_id, str(version_no), now)
        connection.execute(
            """INSERT INTO company_profile_versions
               (profile_version_id, company_id, version_no, status, payload_json, created_at)
               VALUES (?, ?, ?, 'draft', '{}', ?)""", (profile_version_id, company_id, version_no, now)
        )
    # Keep paths comfortably below the legacy Windows path limit while IDs in the
    # database retain their full collision-resistant value.
    storage_root = (settings.root_dir / "data" / "company" / "onboarding" / company_id[-12:] / profile_version_id[-12:]).resolve()
    for prepared_file in prepared:
        filename = prepared_file["filename"]
        mime_type = prepared_file["mime_type"]
        raw = prepared_file["raw"]
        suffix = prepared_file["suffix"]
        digest = prepared_file["digest"]
        extraction = prepared_file["extraction"]
        document_id = db.stable_id("ondoc", profile_version_id, digest)
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(filename).name).strip("-") or f"document{suffix}"
        path = (storage_root / document_id[-12:] / safe).resolve()
        if storage_root not in path.parents:
            raise ValueError("unsafe onboarding storage path")
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists(): path.write_bytes(raw)
        with db.connect(db_path) as connection:
            connection.execute(
                """INSERT INTO onboarding_documents
                   (onboarding_document_id, company_id, profile_version_id, filename, mime_type,
                    document_kind, sha256, storage_uri, created_at) VALUES (?, ?, ?, ?, ?, 'company_context', ?, ?, ?)""",
                (document_id, company_id, profile_version_id, Path(filename).name, mime_type, digest,
                 str(path.relative_to(settings.root_dir)).replace("\\", "/"), _now()),
            )
        for sequence, item in enumerate(extraction.chunks, 1):
            chunk_id = db.stable_id("onchunk", document_id, str(sequence), item.raw_text)
            with db.connect(db_path) as connection:
                connection.execute(
                    """INSERT INTO onboarding_document_chunks
                       (onboarding_chunk_id, onboarding_document_id, sequence_no, locator_json, text, text_sha256)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (chunk_id, document_id, sequence, _json(item.locator), item.raw_text,
                     hashlib.sha256(item.raw_text.encode()).hexdigest()),
                )
            for fact_type, value, confidence, method in _fact_matches(item.raw_text):
                _insert_fact(profile_version_id=profile_version_id, document_id=document_id, chunk_id=chunk_id,
                             locator=item.locator, fact_type=fact_type, value=value,
                             confidence=confidence, method=method, db_path=db_path)
    facts, details = _merged_facts(profile_version_id, db_path)
    _build_scope(profile_version_id, facts, details, db_path)
    payload = {"facts": facts, "document_count": len(prepared)}
    with db.connect(db_path) as connection:
        connection.execute("UPDATE company_profile_versions SET payload_json=? WHERE profile_version_id=?", (_json(payload), profile_version_id))
        connection.execute("UPDATE company_profiles SET current_version_id=?, updated_at=? WHERE company_id=?", (profile_version_id, _now(), company_id))
        connection.execute(
            """INSERT INTO onboarding_status(company_id, status, current_step, updated_at)
               VALUES (?, 'in_progress', 'review_scope', ?)
               ON CONFLICT(company_id) DO UPDATE SET status='in_progress', current_step='review_scope', last_error=NULL, updated_at=excluded.updated_at""",
            (company_id, _now()),
        )
    return get_onboarding(company_id, db_path)


def get_onboarding(company_id: str | None = None, db_path=None) -> dict[str, Any]:
    with db.connect(db_path) as connection:
        if company_id:
            profile = connection.execute("SELECT * FROM company_profiles WHERE company_id=?", (company_id,)).fetchone()
        else:
            profile = connection.execute("SELECT * FROM company_profiles ORDER BY updated_at DESC LIMIT 1").fetchone()
        if not profile:
            return {"status": "not_started", "company": None, "profile_version": None, "facts": [], "scope": [], "documents": []}
        if not profile["current_version_id"]:
            return {
                "status": "not_started",
                "current_step": "upload",
                "company": {"company_id": profile["company_id"], "name": profile["name"], "status": profile["status"]},
                "profile_version": None,
                "fact_summary": {},
                "facts": [],
                "scope": [],
                "documents": [],
                "notice": "Previous upload did not create a usable profile. Upload non-empty documents to continue.",
            }
        version = connection.execute("SELECT * FROM company_profile_versions WHERE profile_version_id=?", (profile["current_version_id"],)).fetchone()
        if not version:
            return {
                "status": "not_started",
                "current_step": "upload",
                "company": {"company_id": profile["company_id"], "name": profile["name"], "status": profile["status"]},
                "profile_version": None,
                "fact_summary": {},
                "facts": [],
                "scope": [],
                "documents": [],
                "notice": "The active company profile is unavailable. Upload company documents to rebuild it.",
            }
        status = connection.execute("SELECT * FROM onboarding_status WHERE company_id=?", (profile["company_id"],)).fetchone()
        docs = connection.execute("SELECT onboarding_document_id, filename, mime_type, created_at FROM onboarding_documents WHERE profile_version_id=? ORDER BY created_at", (version["profile_version_id"],)).fetchall()
        scope_rows = connection.execute(
            """SELECT s.*, d.code, d.name_ar, d.name_en, d.connector_authority
               FROM company_regulatory_scope s JOIN regulatory_domains d USING(domain_id)
               WHERE s.profile_version_id=? ORDER BY s.classification, d.name_en""", (version["profile_version_id"],)
        ).fetchall()
    facts, details = _merged_facts(version["profile_version_id"], db_path)
    return {"status": status["status"] if status else profile["status"],
            "current_step": status["current_step"] if status else "upload",
            "company": {"company_id": profile["company_id"], "name": profile["name"], "status": profile["status"]},
            "profile_version": {"profile_version_id": version["profile_version_id"], "version_no": version["version_no"],
                                "status": version["status"], "company_snapshot_id": version["company_snapshot_id"]},
            "fact_summary": facts, "facts": details, "scope": [dict(row) for row in scope_rows],
            "documents": [dict(row) for row in docs]}


def remove_profile_document(company_id: str, document_id: str, db_path=None) -> dict[str, Any]:
    """Remove a document from the active profile by creating a clean draft version.

    Approved historical versions remain immutable for audit purposes, while the
    newly active draft is rebuilt only from the documents the user kept. This
    prevents facts from a deleted document leaking into a later re-upload.
    """
    current = get_onboarding(company_id, db_path)
    if not current.get("company") or not current.get("profile_version"):
        raise KeyError(document_id)
    active_version_id = current["profile_version"]["profile_version_id"]
    with db.connect(db_path) as connection:
        target = connection.execute(
            """SELECT * FROM onboarding_documents
               WHERE onboarding_document_id=? AND company_id=? AND profile_version_id=?""",
            (document_id, company_id, active_version_id),
        ).fetchone()
        if not target:
            raise KeyError(document_id)
        remaining = connection.execute(
            """SELECT filename, mime_type, storage_uri FROM onboarding_documents
               WHERE profile_version_id=? AND onboarding_document_id!=? ORDER BY created_at""",
            (active_version_id, document_id),
        ).fetchall()

    files: list[tuple[str, str, bytes]] = []
    for item in remaining:
        path = (settings.root_dir / item["storage_uri"]).resolve()
        if not path.exists():
            raise ValueError(f"stored company document is unavailable: {item['filename']}")
        files.append((item["filename"], item["mime_type"], path.read_bytes()))

    if files:
        return create_profile_from_documents(
            company_name=current["company"]["name"],
            files=files,
            db_path=db_path,
            retain_existing=False,
        )

    now = _now()
    with db.connect(db_path) as connection:
        version_no = connection.execute(
            "SELECT COALESCE(MAX(version_no),0)+1 FROM company_profile_versions WHERE company_id=?",
            (company_id,),
        ).fetchone()[0]
        version_id = db.stable_id("profilev", company_id, str(version_no), now)
        connection.execute(
            """INSERT INTO company_profile_versions
               (profile_version_id, company_id, version_no, status, payload_json, created_at)
               VALUES (?, ?, ?, 'draft', '{"facts":{},"document_count":0}', ?)""",
            (version_id, company_id, version_no, now),
        )
        connection.execute(
            "UPDATE company_profiles SET current_version_id=?, status='onboarding', updated_at=? WHERE company_id=?",
            (version_id, now, company_id),
        )
        connection.execute(
            """INSERT INTO onboarding_status(company_id, status, current_step, updated_at)
               VALUES (?, 'in_progress', 'upload', ?)
               ON CONFLICT(company_id) DO UPDATE SET status='in_progress', current_step='upload', last_error=NULL, updated_at=excluded.updated_at""",
            (company_id, now),
        )
    return get_onboarding(company_id, db_path)


def approve_profile(company_id: str, *, expected_version: int, profile_edits: dict[str, Any],
                    scope_updates: list[dict[str, Any]], role: str, db_path=None) -> dict[str, Any]:
    current = get_onboarding(company_id, db_path)
    if not current.get("company") or current["profile_version"]["version_no"] != expected_version:
        raise ValueError("profile version conflict")
    version_id = current["profile_version"]["profile_version_id"]
    with db.connect(db_path) as connection:
        scopes = {row["code"]: row for row in connection.execute(
            """SELECT s.*, d.code FROM company_regulatory_scope s JOIN regulatory_domains d USING(domain_id)
               WHERE s.profile_version_id=?""", (version_id,)
        )}
        domains = {row["code"]: dict(row) for row in connection.execute("SELECT * FROM regulatory_domains")}
        for update in scope_updates:
            code, status = update["code"], update["status"]
            existing = scopes.get(code)
            if existing and existing["classification"] == "mandatory" and status == "removed" and role != "admin":
                raise PermissionError("mandatory domains require admin override")
            if existing:
                connection.execute("UPDATE company_regulatory_scope SET status=?, admin_override=? WHERE scope_id=?",
                                   (status, int(status == "removed" and role == "admin"), existing["scope_id"]))
            elif code in domains:
                connection.execute(
                    """INSERT INTO company_regulatory_scope
                       (scope_id, profile_version_id, domain_id, classification, status, admin_override, rationale, created_at)
                       VALUES (?, ?, ?, 'user_added', ?, 0, 'Added and confirmed by user.', ?)""",
                    (db.stable_id("scope", version_id, code), version_id, domains[code]["domain_id"], status, _now()),
                )
    facts = current["fact_summary"]
    activities = profile_edits.get("activities") or facts.get("business_activities") or []
    departments = profile_edits.get("departments") or facts.get("departments") or []
    products = profile_edits.get("products_services") or facts.get("products_services") or []
    jurisdictions = profile_edits.get("jurisdictions") or facts.get("jurisdictions") or []
    attributes = {key: value for key, value in facts.items() if isinstance(value, bool)}
    attributes.update({"departments": departments, "products_services": products,
                       "technologies": profile_edits.get("technologies") or facts.get("technologies") or []})
    snapshot_id = db.stable_id("snapshot", company_id, version_id)
    snapshot = CompanySnapshot(company_snapshot_id=snapshot_id, company_id=company_id,
                               name=current["company"]["name"], jurisdiction=(jurisdictions[0] if jurisdictions else "UNKNOWN"),
                               activities=activities, assets=[], attributes=attributes)
    db.insert_company_snapshot(snapshot, db_path)
    materialize_approved_company_evidence(
        snapshot_id, profile_version_id=version_id, db_path=db_path, strict=True,
    )
    payload = {"activities": activities, "products_services": products, "departments": departments,
               "technologies": attributes["technologies"], "jurisdictions": jurisdictions,
               "facts": facts, "user_confirmed": profile_edits}
    with db.connect(db_path) as connection:
        connection.execute("UPDATE company_profile_versions SET status='approved', company_snapshot_id=?, payload_json=?, approved_at=? WHERE profile_version_id=?",
                           (snapshot_id, _json(payload), _now(), version_id))
        connection.execute("UPDATE company_profiles SET status='approved', updated_at=? WHERE company_id=?", (_now(), company_id))
        connection.execute("UPDATE onboarding_status SET status='completed', current_step='dashboard', updated_at=? WHERE company_id=?", (_now(), company_id))
    return get_onboarding(company_id, db_path)


def materialize_approved_company_evidence(
    company_snapshot_id: str, *, profile_version_id: str | None = None,
    db_path=None, strict: bool = False,
) -> dict[str, Any]:
    """Make approved onboarding files available to requirement-level matching.

    This idempotent bridge also covers profiles approved before the requirement
    matching feature existed. It is intentionally called by the background scan,
    not application startup, so opening Maal remains fast.
    """
    from .company_documents import ingest_company_document

    with db.connect(db_path) as connection:
        rows = connection.execute(
            """SELECT od.filename, od.mime_type, od.storage_uri
                 FROM company_profile_versions v
                 JOIN onboarding_documents od USING(profile_version_id)
                WHERE (v.company_snapshot_id=? AND v.status='approved')
                   OR v.profile_version_id=?
                ORDER BY od.created_at""",
            (company_snapshot_id, profile_version_id or ""),
        ).fetchall()
    created_before = len(db.list_company_documents(company_snapshot_id, db_path))
    unavailable: list[str] = []
    failed: list[dict[str, str]] = []
    for item in rows:
        path = (settings.root_dir / item["storage_uri"]).resolve()
        if not path.exists():
            unavailable.append(item["filename"])
            if strict:
                raise ValueError(f"stored company document is unavailable: {item['filename']}")
            continue
        try:
            ingest_company_document(
                raw=path.read_bytes(), filename=item["filename"], mime_type=item["mime_type"],
                company_snapshot_id=company_snapshot_id, document_kind="other", title=item["filename"],
                department=None, project_id=None, db_path=db_path,
            )
        except Exception as exc:
            failed.append({"filename": item["filename"], "error": type(exc).__name__})
            if strict:
                raise
    created_after = len(db.list_company_documents(company_snapshot_id, db_path))
    return {
        "documents_seen": len(rows), "documents_created": max(0, created_after - created_before),
        "documents_available": created_after, "unavailable": unavailable, "failed": failed,
    }


def live_ui_overview(company_id: str, db_path=None) -> dict[str, Any]:
    onboarding = get_onboarding(company_id, db_path)
    if onboarding["status"] != "completed":
        raise ValueError("company profile is not approved")
    snapshot_id = onboarding["profile_version"]["company_snapshot_id"]
    with db.connect(db_path) as connection:
        scan_row = connection.execute(
            """SELECT * FROM regulatory_scan_runs WHERE company_snapshot_id=?
               ORDER BY started_at DESC LIMIT 1""", (snapshot_id,)
        ).fetchone()
        scope_rows = connection.execute(
            """SELECT s.classification, s.status, s.rationale, d.code, d.name_ar, d.name_en,
                      d.connector_authority
               FROM company_regulatory_scope s JOIN regulatory_domains d USING(domain_id)
               WHERE s.profile_version_id=? AND s.status!='removed' ORDER BY d.name_en""",
            (onboarding["profile_version"]["profile_version_id"],),
        ).fetchall()
        task_rows = connection.execute(
            """SELECT t.payload_json FROM task_drafts t JOIN runs r USING(run_id)
               WHERE r.company_snapshot_id=? ORDER BY t.updated_at DESC""",
            (snapshot_id,),
        ).fetchall()
        audit_rows = connection.execute(
            """SELECT a.* FROM audit_events a JOIN runs r USING(run_id)
               WHERE r.company_snapshot_id=? ORDER BY a.created_at DESC LIMIT 100""",
            (snapshot_id,),
        ).fetchall()
        feedback_rows = connection.execute(
            """SELECT decision, comment, reviewer_id, reviewer_role, created_at
                 FROM analysis_feedback WHERE company_id=?
                 ORDER BY created_at DESC LIMIT 100""",
            (company_id,),
        ).fetchall()
    sources = [item for item in db.list_sources(db_path) if item["authority"] in {"NCA", "SASO"} and item["enabled"]]
    scan = dict(scan_row) if scan_row else None
    results = db.get_scan_results(scan["scan_id"], db_path) if scan else []
    counts = {"new": 0, "updated": 0, "unchanged": 0, "filtered": 0, "needs_review": 0, "errors": scan.get("error_count", 0) if scan else 0}
    departments = set()
    high_priority = 0
    regulations = []
    for item in results:
        outcome = item["outcome"]
        if outcome == "new": counts["new"] += 1
        elif outcome == "changed": counts["updated"] += 1
        elif outcome == "unchanged": counts["unchanged"] += 1
        elif outcome == "filtered": counts["filtered"] += 1
        elif outcome == "needs_review": counts["needs_review"] += 1
        departments.update(item["department_ids"])
        if item["priority"] == "high": high_priority += 1
        document = db.get_regulatory_document(item["document_id"], db_path)
        current_version = db.get_document_version_preview(item["version_id"], db_path) if item.get("version_id") else None
        previous_version = (
            db.get_document_version_preview(item["previous_version_id"], db_path)
            if item.get("previous_version_id") and item.get("previous_version_id") != item.get("version_id")
            else None
        )
        if item["applicability_status"] == "not_applicable":
            recommended_action = "No impact analysis action. Retain the documented exclusion rationale for review."
        elif item["applicability_status"] == "needs_review":
            recommended_action = "Confirm product, system, or operational scope with additional company evidence before impact analysis."
        else:
            recommended_action = "Review applicability and map the current regulation to approved company controls."
        regulations.append({
            "document_id": item["document_id"],
            "regulation_name": item["title"], "authority": item["authority"],
            "jurisdiction": document.jurisdiction if document else "SA",
            "domain": document.regulatory_domain if document else "—", "category": document.category if document else None,
            "published_date": document.publication_date.isoformat() if document and document.publication_date else None,
            "effective_date": document.mandatory_application_date.isoformat() if document and document.mandatory_application_date else None,
            "canonical_url": item["canonical_url"], "outcome": outcome,
            "applicability": item["applicability_status"], "applicability_reason": item["applicability_rationale"],
            "priority": item["priority"], "department": ", ".join(item["department_ids"]) or "Needs confirmation",
            "affected_files": item["affected_files"], "estimated_exposure": None, "currency": None,
            "feedback_target_id": item.get("feedback_target_id"), "feedback": item.get("feedback"),
            "has_previous_version": bool(previous_version),
            "current_version_id": current_version.get("version_id") if current_version else None,
            "previous_version_id": previous_version.get("version_id") if previous_version else None,
            "current_text": current_version.get("content", "")[:1200] if current_version else None,
            "previous_text": previous_version.get("content", "")[:1200] if previous_version else None,
            "change_previews": item["change_previews"],
            "recommended_action": recommended_action,
        })
    scopes = [dict(row) for row in scope_rows]
    unconnected = [item for item in scopes if item["classification"] == "mandatory" and not item["connector_authority"]]
    tasks = []
    for row in task_rows:
        task = json.loads(row["payload_json"])
        reviews = db.list_reviews(task["task_id"], db_path)
        tasks.append({
            "task_id": task["task_id"], "action": task["action"],
            "owner_role": task.get("owner_role"), "proposed_due_date": task.get("proposed_due_date"),
            "review_status": task["review_status"], "revision": task["revision"],
            "reviews": [{"decision": review["decision"], "comment": review["comment"],
                         "reviewer": review["reviewer_id"], "created_at": review["created_at"]}
                        for review in reviews],
        })
    audit_events = []
    for row in audit_rows:
        item = dict(row)
        audit_events.append({"action": item["action"], "reason_summary": item["reason_summary"],
                             "created_at": item["created_at"], "actor_role": item["actor_role"]})
    for row in feedback_rows:
        audit_events.append({
            "action": f"analysis_feedback_{row['decision']}",
            "reason_summary": row["comment"],
            "created_at": row["created_at"],
            "actor_role": row["reviewer_role"],
        })
    if scan:
        for event in reversed(db.list_source_fetch_events(scan["scan_id"], db_path)):
            audit_events.append({
                "action": f"regulatory_source_{event['status']}",
                "reason_summary": event.get("error_message") or event["canonical_url"],
                "created_at": event["finished_at"], "actor_role": "system",
            })
    audit_events.sort(key=lambda item: item["created_at"], reverse=True)
    from .compliance_review import impact_graph
    graph = impact_graph(db_path, company_snapshot_id=snapshot_id)
    trace_paths = []
    for dep in graph["dependencies"]:
        locator = dep.get("locator") or {}
        section = dep.get("section_ref") or (
            f"Page {locator['page']}" if locator.get("page") else
            f"Slide {locator['slide']}" if locator.get("slide") else
            f"{locator.get('sheet')} · {locator.get('cell')}" if locator.get("sheet") else
            f"Line {locator['line_start']}" if locator.get("line_start") else "Document section"
        )
        trace_paths.append({
            "regulation": dep["authority"], "article": dep["article_ref"],
            "requirement": f"Requirement — {dep['article_ref']}",
            "document": dep["document_title"], "section": section,
            "department": dep["department"], "project": dep.get("project_id"),
            "relationship": dep["relationship_type"],
            "evidence": dep.get("document_quote"),
        })
    return {
        "company": {"name": onboarding["company"]["name"], "company_id": company_id,
                    "snapshot_id": snapshot_id, "profile_version": onboarding["profile_version"]["version_no"]},
        "profile": {"facts": onboarding["fact_summary"], "scope": scopes},
        "sources": [{"authority": item["authority"], "last_checked_at": item.get("last_checked_at"),
                     "last_success_at": item.get("last_success_at"), "source_id": item["source_id"]} for item in sources],
        "scan": ({"scan_id": scan["scan_id"], "status": scan["status"], "started_at": scan["started_at"],
                  "finished_at": scan["finished_at"], "documents_discovered": scan["documents_discovered"],
                  "versions_created": scan["versions_created"], **counts} if scan else None),
        "summary": {"new_updates": counts["new"], "updated_regulations": counts["updated"],
                    "high_priority": high_priority, "needs_review": counts["needs_review"],
                    "affected_departments": len(departments), "unconnected_mandatory_domains": len(unconnected),
                    "estimated_financial_exposure": None, "currency": None},
        "regulations": regulations, "unconnected_domains": unconnected,
        "financial": {"remediation": None, "project_delay": None, "downtime": None,
                      "contractual": None, "direct_penalty": None, "total": None, "currency": None},
        "traceability": {"nodes": [{"type": node["type"], "label": node["label"]}
                                    for node in graph["nodes"]], "paths": trace_paths},
        "human_review": {"tasks": tasks,
                         "pending_count": sum(1 for item in tasks if item["review_status"] == "pending_human_review"),
                         "audit_events": audit_events[:100]},
    }
