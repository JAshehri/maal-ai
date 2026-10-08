from __future__ import annotations

import hmac
import json
from dataclasses import dataclass
from typing import Any

from .settings import settings


ALLOWED_ROLES = frozenset({"admin", "analyst", "reviewer"})


class AuthenticationFailure(RuntimeError):
    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class Identity:
    user_id: str
    role: str


def _token_identities(raw: str) -> list[tuple[str, Identity]]:
    """Parse pilot API identities without ever returning or logging their tokens."""
    if not raw.strip():
        return []
    try:
        payload: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AuthenticationFailure("server authentication configuration is invalid", status_code=503) from exc
    if not isinstance(payload, dict):
        raise AuthenticationFailure("server authentication configuration is invalid", status_code=503)
    identities: list[tuple[str, Identity]] = []
    for token, item in payload.items():
        if not isinstance(token, str) or not token or not isinstance(item, dict):
            raise AuthenticationFailure("server authentication configuration is invalid", status_code=503)
        user_id, role = item.get("user_id"), item.get("role")
        if not isinstance(user_id, str) or not user_id.strip() or role not in ALLOWED_ROLES:
            raise AuthenticationFailure("server authentication configuration is invalid", status_code=503)
        identities.append((token, Identity(user_id=user_id.strip(), role=role)))
    return identities


def authenticate(
    *,
    allowed_roles: tuple[str, ...],
    x_role: str | None,
    x_user_id: str | None,
    x_api_token: str | None,
) -> Identity:
    """Authenticate local MVP headers or a token-bound pilot identity.

    `token` mode ignores caller-supplied identity/role headers, preventing role
    spoofing. `local` mode is deliberately limited to local development and still
    requires an explicit user id so audit events never receive an invented actor.
    """
    mode = settings.auth_mode.strip().lower()
    if mode == "token":
        if not x_api_token:
            raise AuthenticationFailure("API token required", status_code=401)
        identity = None
        for candidate, mapped_identity in _token_identities(settings.api_keys_json):
            if hmac.compare_digest(candidate, x_api_token):
                identity = mapped_identity
        if identity is None:
            raise AuthenticationFailure("invalid API token", status_code=401)
    elif mode == "local":
        if settings.api_token and (
            not x_api_token or not hmac.compare_digest(settings.api_token, x_api_token)
        ):
            raise AuthenticationFailure("invalid API token", status_code=401)
        if x_role not in ALLOWED_ROLES:
            raise AuthenticationFailure("valid X-Role header required", status_code=403)
        if not x_user_id or not x_user_id.strip():
            raise AuthenticationFailure("X-User-Id header required", status_code=401)
        identity = Identity(user_id=x_user_id.strip(), role=x_role)
    else:
        raise AuthenticationFailure("unsupported authentication mode", status_code=503)

    if identity.role not in allowed_roles:
        raise AuthenticationFailure(f"role must be one of {allowed_roles}", status_code=403)
    return identity


def authentication_posture() -> dict[str, Any]:
    mode = settings.auth_mode.strip().lower()
    configured = mode == "local" or bool(_token_identities(settings.api_keys_json))
    return {
        "mode": mode,
        "configured": configured,
        "pilot_ready": mode == "token" and configured,
        "production_ready": False,
        "roles": sorted(ALLOWED_ROLES),
    }
