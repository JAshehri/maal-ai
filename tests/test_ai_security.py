from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from src.ai_policy import ai_operating_posture, product_capabilities
from src.auth import AuthenticationFailure, authenticate, authentication_posture
from src.llm_client import AnthropicLLMClient, LLMError
from src.settings import settings


class _StructuredAnswer(BaseModel):
    status: str


def test_ai_policy_forbids_model_approval_and_external_execution() -> None:
    posture = ai_operating_posture()
    prohibited = next(item for item in posture["tasks"] if item["task"] == "legal_approval_or_external_execution")
    assert prohibited["execution"] == "prohibited"
    assert prohibited["model_allowed"] is False
    assert prohibited["human_gate"] is True
    assert posture["stores_chain_of_thought"] is False


def test_product_capabilities_do_not_claim_unbuilt_production_features() -> None:
    capabilities = product_capabilities()
    assert capabilities["stage"] == "mvp"
    assert capabilities["live_regulatory_sources"] == ["NCA", "SASO"]
    assert capabilities["features"]["external_grc"] is False
    assert capabilities["features"]["multi_tenant_isolation"] is False
    assert capabilities["features"]["managed_ocr"] is False


def test_local_auth_requires_explicit_audit_identity() -> None:
    original_mode = settings.auth_mode
    try:
        object.__setattr__(settings, "auth_mode", "local")
        with pytest.raises(AuthenticationFailure) as failure:
            authenticate(
                allowed_roles=("analyst",), x_role="analyst", x_user_id=None, x_api_token=None
            )
        assert failure.value.status_code == 401
    finally:
        object.__setattr__(settings, "auth_mode", original_mode)


def test_token_auth_binds_role_and_identity_to_secret_not_headers() -> None:
    original_mode, original_keys = settings.auth_mode, settings.api_keys_json
    try:
        object.__setattr__(settings, "auth_mode", "token")
        object.__setattr__(settings, "api_keys_json", json.dumps({
            "secret-reviewer-token": {"user_id": "reviewer-42", "role": "reviewer"}
        }))
        identity = authenticate(
            allowed_roles=("reviewer",),
            x_role="admin",
            x_user_id="spoofed-admin",
            x_api_token="secret-reviewer-token",
        )
        assert identity.user_id == "reviewer-42"
        assert identity.role == "reviewer"
        posture = authentication_posture()
        assert posture["pilot_ready"] is True
        assert posture["production_ready"] is False
        with pytest.raises(AuthenticationFailure) as failure:
            authenticate(
                allowed_roles=("admin",),
                x_role="admin",
                x_user_id="spoofed-admin",
                x_api_token="secret-reviewer-token",
            )
        assert failure.value.status_code == 403
    finally:
        object.__setattr__(settings, "auth_mode", original_mode)
        object.__setattr__(settings, "api_keys_json", original_keys)


def test_llm_boundary_rejects_oversized_input_before_network_call() -> None:
    client = object.__new__(AnthropicLLMClient)
    original_limit = settings.llm_max_input_chars
    try:
        object.__setattr__(settings, "llm_max_input_chars", 10)
        with pytest.raises(LLMError, match="safe limit"):
            client.generate_model(system="123456", user="123456", response_model=_StructuredAnswer)
    finally:
        object.__setattr__(settings, "llm_max_input_chars", original_limit)
