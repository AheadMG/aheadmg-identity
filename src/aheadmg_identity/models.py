from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Tenant admission modes — controls whether any user from an allowlisted
# tenant can sign in, or only those who have been pre-invited.
TENANT_MODE_OPEN = "open"
TENANT_MODE_INVITATION = "invitation"

# User statuses
USER_STATUS_INVITED = "invited"      # admin-created, hasn't signed in yet (oid still null)
USER_STATUS_ACTIVE = "active"        # signed in successfully at least once
USER_STATUS_DISABLED = "disabled"    # access revoked


class TenantAllowlist(Base):
    __tablename__ = "tenant_allowlist"
    __table_args__ = {"schema": "identity"}

    tenant_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    user_admission_mode: Mapped[str] = mapped_column(
        String(16), default=TENANT_MODE_INVITATION, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class User(Base):
    __tablename__ = "user"
    # An invited user has a row before they've signed in (no oid yet);
    # uniqueness is on (tenant_id, email) so an admin can't invite the same
    # person twice into the same tenant.
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_user_tenant_email"),
        {"schema": "identity"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    oid: Mapped[str | None] = mapped_column(String(36), nullable=True, unique=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # Optional free-text job title (e.g. "Programme Director"). Set by admins;
    # shown beneath the user's name in the app header.
    job_title: Mapped[str | None] = mapped_column(String(150), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=USER_STATUS_ACTIVE, nullable=False)
    invited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Capability is entirely role-based — see UserAppRole. "Platform
    # administrator" is the 'admin' role on the 'hub' app.


class AppCatalog(Base):
    """A registered AheadMG application. Drives the Hub's launcher grid and
    is the set of apps that roles can be granted against."""

    __tablename__ = "app_catalog"
    __table_args__ = {"schema": "identity"}

    slug: Mapped[str] = mapped_column(String(50), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    # `icon` is the small mark used in nav / list contexts (sidebar
    # app-switcher, admin lists). `feature_icon` is the larger / fuller
    # mark used in prominent contexts (resume card, hero tiles). Either
    # may be null — display surfaces fall back to icon, then to a
    # letter placeholder.
    icon: Mapped[str | None] = mapped_column(String(500), nullable=True)
    feature_icon: Mapped[str | None] = mapped_column(String(500), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class AppRole(Base):
    """A role that a given app defines. Each app owns its own role list and
    upserts it here on startup; the Hub admin UI reads this table to know
    which roles can be assigned for each app."""

    __tablename__ = "app_role"
    __table_args__ = {"schema": "identity"}

    app_slug: Mapped[str] = mapped_column(
        String(50), ForeignKey("identity.app_catalog.slug"), primary_key=True
    )
    role_key: Mapped[str] = mapped_column(String(50), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False)


class UserAppRole(Base):
    """A role grant: user `user_id` holds role `role_key` on app `app_slug`.
    A user can hold several roles on the same app (one row each). Holding
    at least one row for an app means the user can access that app at all.

    `role_key` is validated against AppRole in application code rather than
    by a composite foreign key — kept deliberately loose so an app can be
    seeded before all its roles exist."""

    __tablename__ = "user_app_role"
    __table_args__ = {"schema": "identity"}

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("identity.user.id"), primary_key=True
    )
    app_slug: Mapped[str] = mapped_column(
        String(50), ForeignKey("identity.app_catalog.slug"), primary_key=True
    )
    role_key: Mapped[str] = mapped_column(String(50), primary_key=True)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    granted_by_oid: Mapped[str | None] = mapped_column(String(36), nullable=True)


class UserPageVisit(Base):
    """Append-only log of in-app page navigations. Every front-end route
    change in a non-Hub app posts one row; the Hub home reads the latest
    row per user to render a "Resume where you left off" card.

    Append-only (no upsert) so we keep the full history — useful for a
    future "recent pages" view and basic analytics. The Hub itself does
    NOT log its own page visits; the launcher and admin pages are not
    something the user wants to "resume to".
    """

    __tablename__ = "user_page_visit"
    __table_args__ = (
        # Hot index for the resume-where-you-left-off query, which is
        # `latest visit for user X` ordered by visited_at DESC.
        Index("ix_user_page_visit_user_visited", "user_id", "visited_at"),
        {"schema": "identity"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("identity.user.id"), nullable=False
    )
    # Denormalised app slug rather than an FK to app_catalog — keeps the
    # write path cheap and avoids cascading deletes if an app is ever
    # removed from the catalog; we tolerate "orphan" rows for retired apps.
    app_slug: Mapped[str] = mapped_column(String(50), nullable=False)
    # The SPA route the user landed on, including any querystring. 500 is
    # generous; longer URLs are truncated client-side.
    route: Mapped[str] = mapped_column(String(500), nullable=False)
    # Optional human-readable label from `document.title` so the Hub's
    # resume card can say "Resume: Project Atlas — Discovery" rather than
    # echoing the raw route.
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    visited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = {"schema": "identity"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_oid: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    actor_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
