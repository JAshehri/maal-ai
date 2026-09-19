from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path
from typing import Any

from . import db
from .schemas import GRCTaskCreate


class GRCIntegrationService(ABC):
    @abstractmethod
    def create_compliance_task(self, task: GRCTaskCreate) -> dict[str, Any]: ...

    @abstractmethod
    def update_task_status(self, grc_task_id: str, status: str) -> dict[str, Any]: ...

    @abstractmethod
    def attach_evidence(self, grc_task_id: str, evidence_ref: str) -> dict[str, Any]: ...

    @abstractmethod
    def assign_owner(self, grc_task_id: str, owner: str) -> dict[str, Any]: ...

    @abstractmethod
    def set_priority(self, grc_task_id: str, priority: str) -> dict[str, Any]: ...

    @abstractmethod
    def set_due_date(self, grc_task_id: str, due_date: date) -> dict[str, Any]: ...


class LocalGRCAdapter(GRCIntegrationService):
    adapter_name = "local_demo"

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = db_path

    def create_compliance_task(self, task: GRCTaskCreate) -> dict[str, Any]:
        return db.create_grc_task(task, adapter_name=self.adapter_name, db_path=self.db_path)

    def update_task_status(self, grc_task_id: str, status: str) -> dict[str, Any]:
        return db.update_grc_task(grc_task_id, {"status": status}, db_path=self.db_path)

    def attach_evidence(self, grc_task_id: str, evidence_ref: str) -> dict[str, Any]:
        current = db.get_grc_task(grc_task_id, self.db_path)
        refs = list(dict.fromkeys([*current["evidence_refs"], evidence_ref]))
        return db.update_grc_task(grc_task_id, {"evidence_refs": refs}, db_path=self.db_path)

    def assign_owner(self, grc_task_id: str, owner: str) -> dict[str, Any]:
        return db.update_grc_task(grc_task_id, {"owner": owner}, db_path=self.db_path)

    def set_priority(self, grc_task_id: str, priority: str) -> dict[str, Any]:
        if priority not in {"critical", "high", "medium", "low"}:
            raise ValueError("invalid GRC priority")
        return db.update_grc_task(grc_task_id, {"priority": priority}, db_path=self.db_path)

    def set_due_date(self, grc_task_id: str, due_date: date) -> dict[str, Any]:
        return db.update_grc_task(grc_task_id, {"due_date": due_date.isoformat()}, db_path=self.db_path)
