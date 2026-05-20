from functools import wraps
from typing import Any, Callable

import jwt
from flask import current_app, g, jsonify, request
from jwt import PyJWKClient

from .db import db
from .models import (
    TENANT_MODE_INVITATION,
    USER_STATUS_ACTIVE,
    USER_STATUS_DISABLED,
    TenantAllowlist,
    User,
    UserAppRole,
    _utcnow,
)
from .roles import DEFAULT_ROLE

# Multi-tenant JWKS endpoint — keys for any Entra tenant
_JWKS_URL = "https://login.microsoftonline.com/common/discovery/v2.0/keys"
_jwks_client = PyJWKClient(_JWKS_URL, cache_keys=True)


def _validate_token(token: str) -> dict[str, Any]:
    client_id = current_app.config["AZURE_CLIENT_ID"]
    signing_key = _jwks_client.get_signing_key_from_jwt(token).key
    # Accept both v1 token audience (api://<client_id>) and v2 (<client_id>).
    # Issuer check is disabled here because multi-tenant means it varies by
    # tid; we re-validate it manually below.
    claims = jwt.decode(
        token,
        signing_key,
        algorithms=["RS256"],
        audience=[client_id, f"api://{client_id}"],
        options={"verify_iss": False},
    )
    tid = claims.get("tid")
    if not tid:
        raise jwt.InvalidTokenError("token missing tid claim")
    # v1 issuer: https://sts.windows.net/{tid}/   v2: https://login.microsoftonline.com/{tid}/v2.0
    valid_issuers = {
        f"https://sts.windows.net/{tid}/",
        f"https://login.microsoftonline.com/{tid}/v2.0",
    }
    if claims.get("iss") not in valid_issuers:
        raise jwt.InvalidTokenError("issuer does not match tenant")
    return claims


def _claim_email(claims: dict[str, Any]) -> str:
    """Pull the user's email/UPN from whichever claim Entra populated. v2
    tokens put it in preferred_username; v1 tokens vary (upn, unique_name,
    sometimes email). Lowercased for case-insensitive matching against the
    DB."""
    for k in ("preferred_username", "upn", "unique_name", "email"):
        v = claims.get(k)
        if v:
            return v.lower()
    return ""


def user_roles(user: User, app_slug: str) -> set[str]:
    """The set of role_keys the user holds for the given app."""
    rows = (
        db.Session.query(UserAppRole.role_key)
        .filter_by(user_id=user.id, app_slug=app_slug)
        .all()
    )
    return {row[0] for row in rows}


def _admit_user(claims: dict[str, Any], tenant: TenantAllowlist) -> User | None:
    """Resolve the signed-in user against the allowlist rules. Returns the
    User row to log in as, or None if access should be denied at the
    tenant/user level. (Role-level checks happen separately in require_auth.)

    Lookup order is (1) by oid, (2) by (tenant_id, email). Email match runs
    in every admission mode so a pre-created row (an invite) is adopted on
    first sign-in rather than producing a duplicate.
    """
    oid = claims["oid"]
    email = _claim_email(claims)
    name = claims.get("name", "")
    app_slug = current_app.config["APP_SLUG"]

    user = db.Session.query(User).filter_by(oid=oid).first()

    if user is None:
        user = (
            db.Session.query(User)
            .filter_by(tenant_id=tenant.tenant_id, email=email)
            .first()
        )
        if user is not None:
            user.oid = oid

    if user is None:
        if tenant.user_admission_mode == TENANT_MODE_INVITATION:
            return None  # no invite, no auto-create
        # Open-mode tenant: auto-create the user AND grant the app's
        # baseline role, so an open-mode sign-in is actually usable
        # (the role gate in require_auth would otherwise reject them).
        user = User(
            oid=oid,
            tenant_id=tenant.tenant_id,
            email=email,
            name=name,
            status=USER_STATUS_ACTIVE,
            last_login_at=_utcnow(),
        )
        db.Session.add(user)
        db.Session.flush()  # populate user.id for the role grant's FK
        db.Session.add(
            UserAppRole(user_id=user.id, app_slug=app_slug, role_key=DEFAULT_ROLE)
        )
        db.Session.commit()
        return user

    if user.status == USER_STATUS_DISABLED:
        return None

    user.email = email or user.email
    user.name = name or user.name
    user.status = USER_STATUS_ACTIVE
    user.last_login_at = _utcnow()
    db.Session.commit()
    return user


def require_auth(fn: Callable) -> Callable:
    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return jsonify(error="missing bearer token"), 401
        token = header[7:]
        try:
            claims = _validate_token(token)
        except jwt.PyJWTError as e:
            return jsonify(error=f"invalid token: {e}"), 401

        tenant = db.Session.get(TenantAllowlist, claims["tid"])
        if tenant is None or not tenant.enabled:
            return jsonify(error="tenant not permitted"), 403

        user = _admit_user(claims, tenant)
        if user is None:
            current_app.logger.warning(
                "user not permitted: tid=%s oid=%s email=%s",
                claims.get("tid"), claims.get("oid"), _claim_email(claims),
            )
            return jsonify(error="user not permitted"), 403

        # Role gate — the user must hold at least one role for THIS app.
        # Zero roles == no access (this is how access is revoked: strip
        # all of a user's roles for the app).
        app_slug = current_app.config["APP_SLUG"]
        roles = user_roles(user, app_slug)
        if not roles:
            current_app.logger.warning(
                "no role for app: oid=%s app=%s", user.oid, app_slug
            )
            return jsonify(error="no role assigned for this application"), 403

        g.claims = claims
        g.user = user
        g.user_roles = roles
        return fn(*args, **kwargs)

    return wrapper


def require_role(role_key: str) -> Callable:
    """Decorator factory — gate an endpoint behind a specific role on this
    app. `require_admin` below is the common case."""

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        @require_auth
        def wrapper(*args: Any, **kwargs: Any):
            if role_key not in g.user_roles:
                return jsonify(error=f"requires the '{role_key}' role"), 403
            return fn(*args, **kwargs)

        return wrapper

    return decorator


# Platform administration is the 'admin' role on this app.
require_admin = require_role("admin")
