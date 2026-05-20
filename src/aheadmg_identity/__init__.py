"""aheadmg-identity — shared identity layer for AheadMG apps.

Each consuming app sets `SQL_CONNECTION_STRING`, `AZURE_CLIENT_ID` and
`APP_SLUG` on its Flask config, then calls `init_db(app)` and decorates
its endpoints with `require_auth` / `require_role`.
"""

from .auth import require_admin, require_auth, require_role, user_roles
from .db import Base, PLATFORM_SCHEMAS, db, init_db
from .models import (
    TENANT_MODE_INVITATION,
    TENANT_MODE_OPEN,
    USER_STATUS_ACTIVE,
    USER_STATUS_DISABLED,
    USER_STATUS_INVITED,
    AppCatalog,
    AppRole,
    AuditLog,
    TenantAllowlist,
    User,
    UserAppRole,
    UserPageVisit,
)
from .roles import APP_ROLES, DEFAULT_ROLE, sync_app_registration
from .visits import visits_bp

__all__ = [
    # db / schema plumbing
    "Base",
    "PLATFORM_SCHEMAS",
    "db",
    "init_db",
    # models
    "TenantAllowlist",
    "User",
    "AppCatalog",
    "AppRole",
    "UserAppRole",
    "UserPageVisit",
    "AuditLog",
    # model constants
    "TENANT_MODE_OPEN",
    "TENANT_MODE_INVITATION",
    "USER_STATUS_INVITED",
    "USER_STATUS_ACTIVE",
    "USER_STATUS_DISABLED",
    # roles
    "DEFAULT_ROLE",
    "APP_ROLES",
    "sync_app_registration",
    # auth
    "require_auth",
    "require_role",
    "require_admin",
    "user_roles",
    # blueprints
    "visits_bp",
]
