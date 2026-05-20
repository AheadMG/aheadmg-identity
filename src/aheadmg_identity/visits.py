"""Shared page-visit logging endpoint.

Each AheadMG app's frontend calls `POST /api/visits` from a top-level
React effect on every SPA route change. The endpoint writes one row to
`identity.user_page_visit`, attributed to the authenticated user, tagged
with the calling app's slug (taken from server config, NOT trusted from
the client). The Hub then queries this table to render its
"Resume where you left off" card.

The blueprint is shipped here so every app registers the same endpoint
shape — register it with `app.register_blueprint(visits_bp)` in
`create_app`.
"""

from flask import Blueprint, current_app, g, jsonify, request

from .auth import require_auth
from .db import db
from .models import UserPageVisit

visits_bp = Blueprint("visits", __name__)


# Defensive truncation so a misbehaving client can't bloat the column;
# matches the model's String(500) / String(200) widths.
_ROUTE_MAX = 500
_TITLE_MAX = 200


@visits_bp.post("/api/visits")
@require_auth
def log_visit():
    """Append a page visit for the current user on the calling app."""
    payload = request.get_json(silent=True) or {}
    route = (payload.get("route") or "").strip()
    title = (payload.get("title") or "").strip() or None

    # Drop silently rather than 400 — page-visit logging is fire-and-forget
    # telemetry; we don't want a malformed payload breaking SPA navigation.
    if not route:
        return jsonify(ok=False, error="route required"), 400

    visit = UserPageVisit(
        user_id=g.user.id,
        app_slug=current_app.config["APP_SLUG"],
        route=route[:_ROUTE_MAX],
        title=title[:_TITLE_MAX] if title else None,
    )
    db.Session.add(visit)
    db.Session.commit()
    return jsonify(ok=True), 201
