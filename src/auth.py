from __future__ import annotations

import hmac
import hashlib
import json
import secrets
from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from . import db
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
    username: str | None = None
    display_name: str | None = None


PASSWORD_ITERATIONS = 310_000
SESSION_HOURS = 12


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PASSWORD_ITERATIONS,
        urlsafe_b64encode(salt).decode("ascii"),
        urlsafe_b64encode(digest).decode("ascii"),
    )


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, raw_iterations, raw_salt, raw_digest = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), urlsafe_b64decode(raw_salt), int(raw_iterations)
        )
        return hmac.compare_digest(candidate, urlsafe_b64decode(raw_digest))
    except (ValueError, TypeError):
        return False


def _public_user(row: Any) -> dict[str, Any]:
    return {
        "user_id": row["user_id"], "username": row["username"],
        "display_name": row["display_name"], "role": row["role"],
        "active": bool(row["active"]), "created_at": row["created_at"],
    }


def has_users(db_path=None) -> bool:
    db.init_db(db_path)
    with db.connect(db_path) as connection:
        return connection.execute("SELECT 1 FROM app_users LIMIT 1").fetchone() is not None


def create_user(*, username: str, display_name: str, password: str, role: str, db_path=None) -> dict[str, Any]:
    if role not in {"admin", "analyst"}:
        raise ValueError("unsupported user role")
    normalized = username.strip().lower()
    user_id = db.stable_id("user", normalized)
    now = _now()
    try:
        with db.connect(db_path) as connection:
            connection.execute(
                """INSERT INTO app_users
                   (user_id, username, display_name, password_hash, role, active, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
                (user_id, normalized, display_name.strip(), _hash_password(password), role, now, now),
            )
            row = connection.execute("SELECT * FROM app_users WHERE user_id=?", (user_id,)).fetchone()
    except Exception as exc:
        if "UNIQUE constraint failed" in str(exc):
            raise ValueError("username already exists") from exc
        raise
    return _public_user(row)


def setup_first_admin(*, username: str, display_name: str, password: str, db_path=None) -> dict[str, Any]:
    db.init_db(db_path)
    with db.connect(db_path) as connection:
        if connection.execute("SELECT 1 FROM app_users LIMIT 1").fetchone():
            raise PermissionError("initial administrator has already been configured")
    return create_user(
        username=username, display_name=display_name, password=password, role="admin", db_path=db_path
    )


def list_users(db_path=None) -> list[dict[str, Any]]:
    with db.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT * FROM app_users ORDER BY role, display_name COLLATE NOCASE"
        ).fetchall()
    return [_public_user(row) for row in rows]


def login(*, username: str, password: str, db_path=None) -> dict[str, Any]:
    db.init_db(db_path)
    with db.connect(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM app_users WHERE username=? COLLATE NOCASE AND active=1",
            (username.strip(),),
        ).fetchone()
    stored_hash = row["password_hash"] if row else _hash_password("invalid-password-sentinel")
    if not _verify_password(password, stored_hash) or not row:
        raise AuthenticationFailure("invalid username or password", status_code=401)
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    created_at = datetime.now(timezone.utc)
    expires_at = created_at + timedelta(hours=SESSION_HOURS)
    session_id = db.stable_id("session", token_hash)
    with db.connect(db_path) as connection:
        connection.execute(
            """INSERT INTO auth_sessions
               (session_id, user_id, token_hash, created_at, expires_at, last_used_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, row["user_id"], token_hash, created_at.isoformat(),
             expires_at.isoformat(), created_at.isoformat()),
        )
    return {"access_token": token, "token_type": "bearer", "expires_at": expires_at.isoformat(),
            "user": _public_user(row)}


def _session_identity(token: str, db_path=None) -> Identity | None:
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = _now()
    with db.connect(db_path) as connection:
        row = connection.execute(
            """SELECT u.*, s.session_id FROM auth_sessions s
               JOIN app_users u USING(user_id)
               WHERE s.token_hash=? AND s.revoked_at IS NULL AND s.expires_at>? AND u.active=1""",
            (token_hash, now),
        ).fetchone()
        if row:
            connection.execute(
                "UPDATE auth_sessions SET last_used_at=? WHERE session_id=?", (now, row["session_id"])
            )
    if not row:
        return None
    return Identity(user_id=row["user_id"], role=row["role"], username=row["username"],
                    display_name=row["display_name"])


def logout(token: str, db_path=None) -> None:
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with db.connect(db_path) as connection:
        connection.execute(
            "UPDATE auth_sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL",
            (_now(), token_hash),
        )


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
    bearer_token: str | None = None,
) -> Identity:
    """Authenticate local MVP headers or a token-bound pilot identity.

    `token` mode ignores caller-supplied identity/role headers, preventing role
    spoofing. `local` mode is deliberately limited to local development and still
    requires an explicit user id so audit events never receive an invented actor.
    """
    if bearer_token:
        identity = _session_identity(bearer_token)
        if identity is None:
            raise AuthenticationFailure("session is invalid or expired", status_code=401)
    else:
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
    configured = has_users() or mode == "local" or bool(_token_identities(settings.api_keys_json))
    return {
        "mode": mode,
        "configured": configured,
        "interactive_login": has_users(),
        "pilot_ready": has_users() or (mode == "token" and configured),
        "production_ready": False,
        "roles": sorted(ALLOWED_ROLES),
    }
