# aheadmg-identity

Shared identity layer for AheadMG apps — SQLAlchemy models for the `identity.*`
tables (tenants, users, app catalog, role grants, audit log), Flask auth
decorators (`require_auth`, `require_role`) and the startup helpers that
create the platform's logical schemas. Equivalent on the backend to what
`@aheadmg/app-shell` is on the frontend.

## Install

Hosted as a private git repository — pip installs over HTTPS using a token:

```
pip install "aheadmg-identity @ git+https://x-access-token:${GITHUB_PACKAGES_TOKEN}@github.com/AheadMG/aheadmg-identity.git@v0.1.0"
```

For local dev: substitute a personal access token with `read:packages`
permission, or install from a relative checkout (`pip install -e
../aheadmg-identity`).

## Usage

Each app reads `SQL_CONNECTION_STRING`, `AZURE_CLIENT_ID` and `APP_SLUG`
from its Flask config; the package handles the rest.

```python
from flask import Flask
from aheadmg_identity import init_db, require_auth, require_role, sync_app_registration, db

app = Flask(__name__)
app.config.from_object(Config())     # exposes SQL_CONNECTION_STRING, AZURE_CLIENT_ID, APP_SLUG

init_db(app)                          # creates schemas + tables + scoped session

with app.app_context():
    sync_app_registration(
        db.Session, slug="flow", display_name="Ahead Flow",
        url="https://flow.aheadmg.com",
    )

@app.get("/api/me")
@require_auth                         # validates the token, sets g.user and g.user_roles
def me(): ...

@app.post("/api/admin/...")
@require_role("admin")
def admin_only(): ...
```

## Identity model

| Table | Purpose |
|---|---|
| `identity.tenant_allowlist` | Entra tenants permitted to sign in, with admission mode (`open` / `invitation`) |
| `identity.user` | Person record, scoped to a tenant; the Hub owns user lifecycle |
| `identity.app_catalog` | Apps registered on the platform (Hub, Flow, …) |
| `identity.app_role` | Each app's grantable roles |
| `identity.user_app_role` | A user holds a role on an app — at least one row = "can access this app" |
| `identity.audit_log` | Admin actions taken via the Hub |

A user with zero `user_app_role` rows for an app is denied access by
`require_auth`. That's how access is revoked: drop all the user's rows
for that app's slug.

## Releasing a new version

Bump `version` in `pyproject.toml`, commit, and push a matching git tag
(e.g. `v0.1.1`). The consuming apps' Dockerfiles pin to the tag.
