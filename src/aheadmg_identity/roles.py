"""Default role definitions and the startup sync into the identity DB.

Each app calls `sync_app_registration(...)` on startup to upsert its own
`app_catalog` row and its `app_role` rows, so the Hub's admin UI always
has an accurate picture of what can be assigned across the platform.
"""

from sqlalchemy.orm import Session

# The role granted automatically when a user is auto-created under a tenant
# in `open` admission mode. Must be one of the keys in APP_ROLES.
DEFAULT_ROLE = "member"

# (role_key, display_name, description) — ordered; sort_order is derived
# from position so the admin UI lists them sensibly. Apps that want a
# different role set can pass their own list into sync_app_registration.
APP_ROLES: list[tuple[str, str, str]] = [
    (
        "admin",
        "Administrator",
        "Full administration of the app.",
    ),
    (
        "member",
        "Member",
        "Standard access.",
    ),
]


def sync_app_registration(
    session: Session,
    *,
    slug: str,
    display_name: str,
    url: str,
    roles: list[tuple[str, str, str]] | None = None,
) -> None:
    """Upsert this app's `app_catalog` row and its `app_role` rows. Runs on
    every startup so the identity DB reflects the deployed app. Idempotent.

    Only code-owned fields (display_name, url, role definitions) are
    refreshed on update — admin-editable fields (icon, description on the
    catalog row, enabled, sort_order) are left untouched.
    """
    from .models import AppCatalog, AppRole

    role_set = roles if roles is not None else APP_ROLES

    app = session.get(AppCatalog, slug)
    if app is None:
        session.add(AppCatalog(slug=slug, display_name=display_name, url=url))
    else:
        app.display_name = display_name
        app.url = url

    for index, (role_key, role_name, role_desc) in enumerate(role_set, start=1):
        role = session.get(AppRole, (slug, role_key))
        if role is None:
            session.add(
                AppRole(
                    app_slug=slug,
                    role_key=role_key,
                    display_name=role_name,
                    description=role_desc,
                    sort_order=index * 10,
                )
            )
        else:
            role.display_name = role_name
            role.description = role_desc
            role.sort_order = index * 10

    session.commit()
