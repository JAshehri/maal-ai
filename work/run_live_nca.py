import json
from pathlib import Path

from src import db
from src.demo import seed_demo
from src.regulatory.discovery import create_regulatory_scan, execute_regulatory_scan
from src.regulatory.registry import seed_regulatory_sources
from src.schemas import RegulatoryScanCreate


db_path = Path("work/nca_live.db").resolve()
db.init_db(db_path)
demo = seed_demo(db_path)
sources = seed_regulatory_sources(db_path)
source_id = sources["NCA"]


def run(key: str):
    request = RegulatoryScanCreate(
        company_snapshot_id=demo["company_snapshot_id"],
        source_ids=[source_id],
        idempotency_key=key,
    )
    scan, _ = create_regulatory_scan(request, db_path)
    result = execute_regulatory_scan(scan["scan_id"], request=request, db_path=db_path)
    return {
        "scan": result,
        "documents": db.list_regulatory_documents(source_id, db_path),
        "results": db.get_scan_results(scan["scan_id"], db_path),
        "events": db.list_source_fetch_events(scan["scan_id"], db_path),
    }


print(json.dumps({"first": run("nca-live-first-v2"), "second": run("nca-live-second-v2")}, ensure_ascii=False, indent=2, default=str))
