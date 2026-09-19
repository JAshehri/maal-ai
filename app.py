from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Callable

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src import db
from src.demo import seed_demo
from src.company_documents import ingest_company_document
from src.compliance_review import create_compliance_review, impact_graph, seed_core_demo, ui_overview
from src.generate_report import generate_report
from src.ingestion import register_document_version
from src.pipeline import create_run, execute_run
from src.grc import LocalGRCAdapter
from src.regulatory.discovery import create_regulatory_scan, execute_regulatory_scan
from src.regulatory.manual import register_manual_export_regulation
from src.regulatory.registry import seed_regulatory_sources
from src.review_service import ReviewForbidden, RevisionConflict, review_task
from src.schemas import (
    ComplianceReviewCreate, DocumentVersionCreate, ExportSectorRegulationCreate, GRCTaskCreate,
    RegulatoryScanCreate, ReviewRequest, RunCreate, Source, SourceCreate,
)
from src.settings import settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    seed_demo()
    seed_regulatory_sources()
    seed_core_demo()
    yield


app = FastAPI(
    title="مآل - وكيل التغيير التنظيمي",
    version="1.0.0",
    lifespan=lifespan,
    description="نظام دعم قرار قائم على الأدلة مع مراجعة بشرية إلزامية.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Role", "X-User-Id", "X-API-Token"],
)

STATIC_DIR = settings.root_dir / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def require_roles(*allowed: str) -> Callable:
    def dependency(
        x_role: Annotated[str | None, Header(alias="X-Role")] = None,
        x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
        x_api_token: Annotated[str | None, Header(alias="X-API-Token")] = None,
    ) -> tuple[str, str]:
        role = x_role or ""
        if role not in allowed:
            raise HTTPException(status_code=403, detail=f"role must be one of {allowed}")
        if settings.api_token and x_api_token != settings.api_token:
            raise HTTPException(status_code=401, detail="invalid API token")
        return x_user_id or f"demo-{role}", role
    return dependency


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/ready")
def ready(response: Response) -> dict:
    if not db.healthcheck():
        response.status_code = 503
        return {"status": "not_ready", "database": "unavailable"}
    return {"status": "ready", "database": "ok", "worker": "in_process_demo"}


@app.get("/demo/context")
def demo_context(_: tuple[str, str] = Depends(require_roles("analyst", "reviewer", "admin"))) -> dict:
    return seed_core_demo()


@app.get("/demo/files/new-project-proposal")
def demo_project_proposal(
    _: tuple[str, str] = Depends(require_roles("analyst", "reviewer", "admin")),
) -> FileResponse:
    return FileResponse(
        settings.root_dir / "data" / "demo" / "new_project_proposal.txt",
        media_type="text/plain; charset=utf-8",
        filename="new_project_proposal.txt",
    )


@app.get("/ui/overview")
def get_ui_overview(
    _: tuple[str, str] = Depends(require_roles("analyst", "reviewer", "admin")),
) -> dict:
    return ui_overview()


@app.post("/company-documents/upload", status_code=201)
async def upload_company_document(
    company_snapshot_id: str = Form(...),
    document_kind: str = Form(...),
    title: str | None = Form(None),
    department: str | None = Form(None),
    project_id: str | None = Form(None),
    file: UploadFile = File(...),
    _: tuple[str, str] = Depends(require_roles("analyst", "admin")),
) -> dict:
    content = await file.read(settings.max_regulatory_document_bytes + 1)
    if len(content) > settings.max_regulatory_document_bytes:
        raise HTTPException(status_code=413, detail="file exceeds configured size limit")
    try:
        return ingest_company_document(
            raw=content, filename=file.filename or "upload.bin",
            mime_type=file.content_type or "application/octet-stream",
            company_snapshot_id=company_snapshot_id, document_kind=document_kind,
            title=title, department=department, project_id=project_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/company-documents")
def company_documents(
    company_snapshot_id: str | None = None,
    _: tuple[str, str] = Depends(require_roles("analyst", "reviewer", "admin")),
) -> dict:
    return {"documents": db.list_company_documents(company_snapshot_id)}


@app.get("/company-documents/{document_id}")
def company_document(
    document_id: str,
    _: tuple[str, str] = Depends(require_roles("analyst", "reviewer", "admin")),
) -> dict:
    item = db.get_company_document(document_id)
    if not item:
        raise HTTPException(status_code=404, detail="company document not found")
    item["chunks"] = db.list_company_document_chunks(document_id)
    item["dependencies"] = db.list_dependencies(company_document_id=document_id)
    return item


@app.post("/compliance-reviews", status_code=201)
def compliance_review(
    payload: ComplianceReviewCreate,
    _: tuple[str, str] = Depends(require_roles("analyst", "admin")),
) -> dict:
    try:
        return create_compliance_review(payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/compliance-reviews/upload", status_code=201)
async def upload_and_review(
    company_snapshot_id: str = Form(...),
    document_kind: str = Form("project_proposal"),
    title: str | None = Form(None),
    department: str | None = Form(None),
    project_id: str | None = Form(None),
    idempotency_key: str = Form(...),
    file: UploadFile = File(...),
    _: tuple[str, str] = Depends(require_roles("analyst", "admin")),
) -> dict:
    content = await file.read(settings.max_regulatory_document_bytes + 1)
    if len(content) > settings.max_regulatory_document_bytes:
        raise HTTPException(status_code=413, detail="file exceeds configured size limit")
    try:
        ingested = ingest_company_document(
            raw=content, filename=file.filename or "upload.bin",
            mime_type=file.content_type or "application/octet-stream",
            company_snapshot_id=company_snapshot_id, document_kind=document_kind,
            title=title, department=department, project_id=project_id,
        )
        review = create_compliance_review(ComplianceReviewCreate(
            company_document_id=ingested["document"]["company_document_id"],
            company_snapshot_id=company_snapshot_id, idempotency_key=idempotency_key,
        ))
        return {"ingestion": ingested, "review": review}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/compliance-reviews/{review_id}")
def get_compliance_review(
    review_id: str,
    _: tuple[str, str] = Depends(require_roles("analyst", "reviewer", "admin")),
) -> dict:
    item = db.get_compliance_review(review_id)
    if not item:
        raise HTTPException(status_code=404, detail="compliance review not found")
    return item


@app.get("/compliance-reviews/{review_id}/report")
def get_compliance_review_report(
    review_id: str,
    _: tuple[str, str] = Depends(require_roles("analyst", "reviewer", "admin")),
) -> dict:
    item = db.get_compliance_review(review_id)
    if not item:
        raise HTTPException(status_code=404, detail="compliance review not found")
    return {"review": item, "impact_graph": impact_graph(),
            "disclaimer": "Decision support only. Synthetic demo financial inputs are explicitly labelled."}


@app.get("/impact-graph")
def get_impact_graph(
    _: tuple[str, str] = Depends(require_roles("analyst", "reviewer", "admin")),
) -> dict:
    return impact_graph()


@app.get("/sources")
def sources(_: tuple[str, str] = Depends(require_roles("analyst", "reviewer", "admin"))) -> dict:
    return {"sources": db.list_sources()}


@app.get("/regulatory-sources")
def regulatory_sources(
    _: tuple[str, str] = Depends(require_roles("analyst", "reviewer", "admin")),
) -> dict:
    return {"sources": db.list_sources()}


@app.get("/regulatory-documents")
def regulatory_documents(
    source_id: str | None = None,
    _: tuple[str, str] = Depends(require_roles("analyst", "reviewer", "admin")),
) -> dict:
    return {"documents": db.list_regulatory_documents(source_id)}


@app.get("/documents/versions")
def versions(
    source_id: str | None = None,
    _: tuple[str, str] = Depends(require_roles("analyst", "reviewer", "admin")),
) -> dict:
    rows = db.list_document_versions(source_id)
    for row in rows:
        row.pop("content", None)
    return {"versions": rows}


@app.post("/sources", status_code=201)
def create_source(payload: SourceCreate, _: tuple[str, str] = Depends(require_roles("admin"))) -> dict:
    source = Source(source_id=db.stable_id("source", payload.canonical_url), **payload.model_dump())
    return db.insert_source(source).model_dump(mode="json")


@app.post("/documents/versions", status_code=201)
def create_document_version(
    payload: DocumentVersionCreate,
    _: tuple[str, str] = Depends(require_roles("admin")),
) -> dict:
    try:
        version, clauses, warnings = register_document_version(payload)
    except (KeyError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "version": version.model_dump(mode="json"),
        "clauses": [item.model_dump(mode="json") for item in clauses],
        "security_warnings": warnings,
    }


@app.post("/runs", status_code=status.HTTP_202_ACCEPTED)
def start_run(
    payload: RunCreate,
    background_tasks: BackgroundTasks,
    _: tuple[str, str] = Depends(require_roles("analyst", "admin")),
) -> dict:
    try:
        run, created = create_run(payload)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if created:
        background_tasks.add_task(execute_run, run["run_id"])
    return {"run_id": run["run_id"], "status": run["phase"], "created": created}


@app.post("/regulatory-scans", status_code=status.HTTP_202_ACCEPTED)
def start_regulatory_scan(
    payload: RegulatoryScanCreate,
    background_tasks: BackgroundTasks,
    _: tuple[str, str] = Depends(require_roles("analyst", "admin")),
) -> dict:
    try:
        scan, created = create_regulatory_scan(payload)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if created:
        background_tasks.add_task(execute_regulatory_scan, scan["scan_id"], request=payload)
    return {"scan_id": scan["scan_id"], "status": scan["status"], "created": created}


@app.get("/regulatory-scans/{scan_id}")
def get_regulatory_scan(
    scan_id: str,
    _: tuple[str, str] = Depends(require_roles("analyst", "reviewer", "admin")),
) -> dict:
    scan = db.get_scan(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="regulatory scan not found")
    return {"scan": scan, "results": db.get_scan_results(scan_id), "fetch_events": db.list_source_fetch_events(scan_id)}


@app.get("/regulatory-scans/{scan_id}/changes")
def get_regulatory_scan_changes(
    scan_id: str,
    _: tuple[str, str] = Depends(require_roles("analyst", "reviewer", "admin")),
) -> dict:
    if not db.get_scan(scan_id):
        raise HTTPException(status_code=404, detail="regulatory scan not found")
    return {"results": [item for item in db.get_scan_results(scan_id) if item["outcome"] in {"new", "changed"}]}


@app.get("/dashboard/summary")
def dashboard_summary(
    _: tuple[str, str] = Depends(require_roles("analyst", "reviewer", "admin")),
) -> dict:
    return db.dashboard_summary()


@app.get("/runs/{run_id}")
def get_run(run_id: str, _: tuple[str, str] = Depends(require_roles("analyst", "reviewer", "admin"))) -> dict:
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    state = db.load_run_state(run_id)
    return {"run": run, "state": state.model_dump(mode="json") if state else None}


@app.get("/runs/{run_id}/findings")
def get_findings(run_id: str, _: tuple[str, str] = Depends(require_roles("analyst", "reviewer", "admin"))) -> dict:
    if not db.get_run(run_id):
        raise HTTPException(status_code=404, detail="run not found")
    return {
        "findings": [item.model_dump(mode="json") for item in db.list_findings(run_id)],
        "tasks": [item.model_dump(mode="json") for item in db.list_tasks(run_id)],
        "audit_events": db.list_audit_events(run_id),
    }


@app.get("/runs/{run_id}/report")
def get_report(run_id: str, _: tuple[str, str] = Depends(require_roles("analyst", "reviewer", "admin"))) -> dict:
    try:
        return generate_report(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc


@app.get("/changes/{change_id}")
def get_change(change_id: str, _: tuple[str, str] = Depends(require_roles("analyst", "reviewer", "admin"))) -> dict:
    change = db.get_change(change_id)
    if not change:
        raise HTTPException(status_code=404, detail="change not found")
    return change.model_dump(mode="json")


@app.post("/tasks/{task_id}/review")
def task_review(
    task_id: str,
    payload: ReviewRequest,
    identity: tuple[str, str] = Depends(require_roles("reviewer", "admin")),
) -> dict:
    user_id, role = identity
    try:
        task = review_task(task_id, payload, reviewer_id=user_id, role=role)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
    except ReviewForbidden as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return task.model_dump(mode="json")


@app.post("/export-sector/manual", status_code=201)
def create_manual_export_source(
    payload: ExportSectorRegulationCreate,
    _: tuple[str, str] = Depends(require_roles("admin")),
) -> dict:
    return register_manual_export_regulation(payload)


@app.post("/export-sector/manual/upload", status_code=201)
async def upload_manual_export_source(
    metadata_json: str = Form(...),
    file: UploadFile = File(...),
    _: tuple[str, str] = Depends(require_roles("admin")),
) -> dict:
    try:
        payload = ExportSectorRegulationCreate.model_validate_json(metadata_json)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    content = await file.read(settings.max_regulatory_document_bytes + 1)
    if len(content) > settings.max_regulatory_document_bytes:
        raise HTTPException(status_code=413, detail="file exceeds configured size limit")
    return register_manual_export_regulation(
        payload, file_content=content, filename=file.filename or "upload.bin",
        content_type=file.content_type or "application/octet-stream",
    )


@app.post("/grc/tasks", status_code=201)
def create_grc_task(
    payload: GRCTaskCreate,
    _: tuple[str, str] = Depends(require_roles("analyst", "admin")),
) -> dict:
    return LocalGRCAdapter().create_compliance_task(payload)


@app.post("/grc/tasks/{grc_task_id}/status")
def update_grc_task_status(
    grc_task_id: str,
    status_value: str,
    _: tuple[str, str] = Depends(require_roles("analyst", "admin")),
) -> dict:
    try:
        return LocalGRCAdapter().update_task_status(grc_task_id, status_value)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="GRC task not found") from exc
