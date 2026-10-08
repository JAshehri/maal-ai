from __future__ import annotations

from typing import Any

from .settings import settings


AI_TASK_POLICY: tuple[dict[str, Any], ...] = (
    {
        "task": "source_discovery_and_hashing",
        "execution": "deterministic",
        "model_allowed": False,
        "human_gate": False,
    },
    {
        "task": "numeric_unit_and_date_comparison",
        "execution": "deterministic",
        "model_allowed": False,
        "human_gate": False,
    },
    {
        "task": "document_fact_and_obligation_extraction",
        "execution": "deterministic_first_optional_model",
        "model_allowed": True,
        "human_gate": True,
    },
    {
        "task": "applicability_and_gap_assessment",
        "execution": "evidence_rules_with_unknown_states",
        "model_allowed": True,
        "human_gate": True,
    },
    {
        "task": "compliance_task_drafting",
        "execution": "draft_only",
        "model_allowed": True,
        "human_gate": True,
    },
    {
        "task": "legal_approval_or_external_execution",
        "execution": "prohibited",
        "model_allowed": False,
        "human_gate": True,
    },
)


def ai_operating_posture() -> dict[str, Any]:
    return {
        "role": "evidence-grounded decision support",
        "provider": settings.llm_provider,
        "model": settings.llm_model if settings.llm_provider == "anthropic" else "deterministic-rules-1.0",
        "live_model_enabled": settings.llm_provider == "anthropic",
        "human_review_required": True,
        "external_execution_allowed": False,
        "max_retrieval_retries": 2,
        "max_model_retries": settings.llm_max_retries,
        "stores_chain_of_thought": False,
        "stores_decision_summary": True,
        "tasks": [dict(item) for item in AI_TASK_POLICY],
    }


def product_capabilities() -> dict[str, Any]:
    return {
        "stage": "mvp",
        "mode": "demo" if settings.demo_mode else "live_company_data",
        "live_regulatory_sources": ["NCA", "SASO"],
        "supported_company_documents": ["PDF", "DOCX", "XLSX", "PPTX", "TXT", "CSV"],
        "features": {
            "company_onboarding": True,
            "regulatory_change_detection": True,
            "applicability_filtering": True,
            "on_demand_file_review": True,
            "impact_traceability": True,
            "thirty_day_watch_window": True,
            "human_review": True,
            "external_grc": False,
            "multi_tenant_isolation": False,
            "managed_ocr": False,
        },
    }
