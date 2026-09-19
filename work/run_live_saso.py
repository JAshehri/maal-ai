import json
from pathlib import Path

from src import db
from src.demo import seed_demo
from src.regulatory.connectors.saso import SASOConnector
from src.regulatory.discovery import create_regulatory_scan, execute_regulatory_scan
from src.regulatory.registry import seed_regulatory_sources
from src.schemas import RegulatoryScanCreate


class FocusedLiveSASOConnector(SASOConnector):
    focus = (
        "أجهزة الاتصالات وتقنية المعلومات",
        "التوافق الكهرومغناطيسي",
        "المواد الخطرة في الأجهزة والمعدات الكهربائية",
    )

    def discover(self, source_id):
        all_documents = super().discover(source_id)
        selected = [item for item in all_documents if any(token in item.title for token in self.focus)]
        print(json.dumps({"official_list_count": len(all_documents), "focused_count": len(selected)}, ensure_ascii=False))
        return selected


db_path = Path("work/saso_live.db").resolve()
db.init_db(db_path)
demo = seed_demo(db_path)
sources = seed_regulatory_sources(db_path)
source_id = sources["SASO"]


def run(key):
    request = RegulatoryScanCreate(
        company_snapshot_id=demo["company_snapshot_id"],
        source_ids=[source_id],
        idempotency_key=key,
    )
    scan, _ = create_regulatory_scan(request, db_path)
    result = execute_regulatory_scan(
        scan["scan_id"], request=request, db_path=db_path,
        connector_overrides={source_id: FocusedLiveSASOConnector()},
    )
    return {"scan": result, "results": db.get_scan_results(scan["scan_id"], db_path)}


print(json.dumps({"first": run("saso-live-first-v2"), "second": run("saso-live-second-v2")}, ensure_ascii=False, indent=2, default=str))
