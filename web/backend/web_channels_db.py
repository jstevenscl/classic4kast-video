"""CRUD + agent-sync for web_channels (arbitrary-website / Grafana-dashboard
screenshot channels) -- a deliberate parallel to db.py's weatherstar_channels
section rather than a shared table/functions. Keeps every line of the
weather channel path untouched: reviewing this file's diff against db.py's
existing channel functions shows zero shared code, only a mirrored shape.

Served by a separate Node/Puppeteer renderer service (webchannel-renderer),
not the Python weather renderer -- see web_channel_routes.py's agent router
for the parallel 3-endpoint contract this feeds.
"""

import json
import re

from db import RENDER_MODES, _commit_with_retry, _connect, _now
from secrets_util import decrypt_value, encrypt_value

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,98}[a-z0-9]$")
SOURCE_TYPES = {"url", "grafana"}


def _validate_source_fields(source_type: str, target_url: str | None,
                             grafana_base_url: str | None, grafana_dashboard_uid: str | None,
                             grafana_panel_id: str | None) -> None:
    if source_type not in SOURCE_TYPES:
        raise ValueError(f"source_type must be one of {sorted(SOURCE_TYPES)}")
    if source_type == "url" and not (target_url or "").strip():
        raise ValueError("target_url is required when source_type is 'url'")
    if source_type == "grafana":
        missing = [
            name for name, value in (
                ("grafana_base_url", grafana_base_url),
                ("grafana_dashboard_uid", grafana_dashboard_uid),
                ("grafana_panel_id", grafana_panel_id),
            ) if not (value or "").strip()
        ]
        if missing:
            raise ValueError(f"source_type 'grafana' requires: {', '.join(missing)}")


def _web_channel_out(row) -> dict:
    d = dict(row)
    d["deployments"]  = json.loads(d["deployments"] or "[]")
    d["enabled"]       = bool(d["enabled"])
    d["force_render"]  = bool(d["force_render"])
    d["grafana_api_token"] = None  # never round-tripped to browser-facing callers; see get_web_channel_secret
    # Same reasoning as grafana_api_token -- the raw encrypted session blob
    # (cookies/localStorage, see set_web_channel_session_state) never goes
    # to a session-authed caller, only a derived yes/no the UI can show a
    # status badge from.
    d["has_session"] = d.pop("session_state_encrypted", None) is not None
    return d


def list_web_channels(enabled_only: bool = False) -> list[dict]:
    conn = _connect()
    sql = "SELECT * FROM web_channels"
    if enabled_only:
        sql += " WHERE enabled=1"
    sql += " ORDER BY channel_name"
    rows = [_web_channel_out(r) for r in conn.execute(sql).fetchall()]
    conn.close()
    return rows


def get_web_channel(channel_id: int) -> dict | None:
    conn = _connect()
    row = conn.execute("SELECT * FROM web_channels WHERE id=?", (channel_id,)).fetchone()
    conn.close()
    return _web_channel_out(row) if row else None


def create_web_channel(
    slug: str, channel_name: str, source_type: str = "url", enabled: bool = True,
    render_mode: str = "on_demand",
    target_url: str | None = None, viewport_width: int = 1280, viewport_height: int = 720,
    screenshot_interval_ms: int = 1000, page_load_wait_ms: int = 2000, device_scale_factor: float = 1.0,
    dismiss_selector: str | None = None,
    grafana_base_url: str | None = None, grafana_dashboard_uid: str | None = None,
    grafana_panel_id: str | None = None, grafana_api_token: str | None = None,
    grafana_org_id: int = 1, grafana_time_from: str = "now-1h", grafana_time_to: str = "now",
    grafana_extra_query: str | None = None,
) -> dict:
    slug = slug.strip().lower()
    if not _SLUG_RE.match(slug):
        raise ValueError("slug must be 3-100 lowercase alphanumeric/hyphen characters, not starting or ending with a hyphen")
    if render_mode not in RENDER_MODES:
        raise ValueError(f"render_mode must be one of {sorted(RENDER_MODES)}")
    _validate_source_fields(source_type, target_url, grafana_base_url, grafana_dashboard_uid, grafana_panel_id)

    conn = _connect()
    existing = conn.execute("SELECT id FROM web_channels WHERE slug=?", (slug,)).fetchone()
    if existing:
        conn.close()
        raise ValueError(f"slug '{slug}' is already in use")

    now = _now()
    cur = conn.execute(
        """INSERT INTO web_channels
           (slug, channel_name, source_type, enabled, render_mode,
            target_url, viewport_width, viewport_height, screenshot_interval_ms, page_load_wait_ms, device_scale_factor,
            dismiss_selector,
            grafana_base_url, grafana_dashboard_uid, grafana_panel_id, grafana_api_token, grafana_org_id,
            grafana_time_from, grafana_time_to, grafana_extra_query,
            force_render, deployments, created_at, updated_at)
           VALUES (?,?,?,?,?, ?,?,?,?,?,?, ?, ?,?,?,?,?, ?,?,?, 0,'[]',?,?)""",
        (slug, channel_name, source_type, 1 if enabled else 0, render_mode,
         (target_url or "").strip() or None, viewport_width, viewport_height,
         screenshot_interval_ms, page_load_wait_ms, device_scale_factor,
         (dismiss_selector or "").strip() or None,
         (grafana_base_url or "").strip() or None, (grafana_dashboard_uid or "").strip() or None,
         (grafana_panel_id or "").strip() or None, encrypt_value(grafana_api_token), grafana_org_id,
         grafana_time_from, grafana_time_to, (grafana_extra_query or "").strip() or None,
         now, now),
    )
    channel_id = cur.lastrowid
    _commit_with_retry(conn)
    conn.close()
    return get_web_channel(channel_id)


def update_web_channel(
    channel_id: int, channel_name: str | None = None, source_type: str | None = None,
    enabled: bool | None = None, render_mode: str | None = None,
    target_url: str | None = None, viewport_width: int | None = None, viewport_height: int | None = None,
    screenshot_interval_ms: int | None = None, page_load_wait_ms: int | None = None,
    device_scale_factor: float | None = None, dismiss_selector: str | None = None,
    grafana_base_url: str | None = None, grafana_dashboard_uid: str | None = None,
    grafana_panel_id: str | None = None, grafana_api_token: str | None = None,
    grafana_org_id: int | None = None, grafana_time_from: str | None = None, grafana_time_to: str | None = None,
    grafana_extra_query: str | None = None,
) -> dict:
    existing = get_web_channel(channel_id)
    if not existing:
        raise ValueError(f"web channel {channel_id} not found")
    if render_mode is not None and render_mode not in RENDER_MODES:
        raise ValueError(f"render_mode must be one of {sorted(RENDER_MODES)}")
    effective_source_type = source_type if source_type is not None else existing["source_type"]
    if source_type is not None or target_url is not None or grafana_base_url is not None:
        _validate_source_fields(
            effective_source_type,
            target_url if target_url is not None else existing["target_url"],
            grafana_base_url if grafana_base_url is not None else existing["grafana_base_url"],
            grafana_dashboard_uid if grafana_dashboard_uid is not None else existing["grafana_dashboard_uid"],
            grafana_panel_id if grafana_panel_id is not None else existing["grafana_panel_id"],
        )

    fields, params = [], []
    simple = {
        "channel_name": channel_name, "source_type": source_type, "render_mode": render_mode,
        "target_url": target_url, "viewport_width": viewport_width, "viewport_height": viewport_height,
        "screenshot_interval_ms": screenshot_interval_ms, "page_load_wait_ms": page_load_wait_ms,
        "device_scale_factor": device_scale_factor, "dismiss_selector": dismiss_selector,
        "grafana_base_url": grafana_base_url, "grafana_dashboard_uid": grafana_dashboard_uid,
        "grafana_panel_id": grafana_panel_id, "grafana_org_id": grafana_org_id,
        "grafana_time_from": grafana_time_from, "grafana_time_to": grafana_time_to,
        "grafana_extra_query": grafana_extra_query,
    }
    for column, value in simple.items():
        if value is not None:
            fields.append(f"{column}=?"); params.append(value)
    if enabled is not None:
        fields.append("enabled=?"); params.append(1 if enabled else 0)
    if grafana_api_token is not None:
        fields.append("grafana_api_token=?"); params.append(encrypt_value(grafana_api_token))
    fields.append("updated_at=?"); params.append(_now())
    params.append(channel_id)

    conn = _connect()
    conn.execute(f"UPDATE web_channels SET {', '.join(fields)} WHERE id=?", params)
    _commit_with_retry(conn)
    conn.close()
    return get_web_channel(channel_id)


def delete_web_channel(channel_id: int) -> None:
    if not get_web_channel(channel_id):
        raise ValueError(f"web channel {channel_id} not found")
    conn = _connect()
    conn.execute("DELETE FROM web_channels WHERE id=?", (channel_id,))
    _commit_with_retry(conn)
    conn.close()


def trigger_web_channel_render(channel_id: int) -> dict:
    if not get_web_channel(channel_id):
        raise ValueError(f"web channel {channel_id} not found")
    conn = _connect()
    conn.execute("UPDATE web_channels SET force_render=1, updated_at=? WHERE id=?", (_now(), channel_id))
    _commit_with_retry(conn)
    conn.close()
    return get_web_channel(channel_id)


# ── Interactive login-session capture (see web_channel_routes.py's
# websocket bridge + login_session.js) ──────────────────────────────────────

def set_web_channel_session_state(channel_id: int, session_state: dict | None) -> dict:
    """session_state: {'cookies': [...], 'localStorage': {...}} captured
    via the interactive login-session flow, or None to clear it (the
    admin's "Clear session" action, or forcing a fresh login next time).
    A separate function rather than a param on update_web_channel, same
    reasoning as the deployment functions below being separate from it --
    this needs a real None-means-clear sentinel, which update_web_channel's
    existing None-means-don't-touch convention can't express. Same
    encrypt-at-rest pattern as grafana_api_token (secrets_util) -- stored
    as one encrypted JSON string, never round-tripped in plaintext to
    session-authed callers (see _web_channel_out's has_session flag)."""
    if not get_web_channel(channel_id):
        raise ValueError(f"web channel {channel_id} not found")
    encrypted = encrypt_value(json.dumps(session_state)) if session_state is not None else None
    conn = _connect()
    conn.execute("UPDATE web_channels SET session_state_encrypted=?, updated_at=? WHERE id=?",
                 (encrypted, _now(), channel_id))
    _commit_with_retry(conn)
    conn.close()
    return get_web_channel(channel_id)


# ── Deployments (JSON list column, identical shape to weatherstar_channels') ─

def add_web_channel_deployment(channel_id: int, deployment: dict) -> dict:
    channel = get_web_channel(channel_id)
    if not channel:
        raise ValueError(f"web channel {channel_id} not found")
    deployments = [*channel["deployments"], deployment]
    conn = _connect()
    conn.execute("UPDATE web_channels SET deployments=?, updated_at=? WHERE id=?",
                 (json.dumps(deployments), _now(), channel_id))
    _commit_with_retry(conn)
    conn.close()
    return get_web_channel(channel_id)


def remove_web_channel_deployment(channel_id: int, connection_id: int) -> dict:
    channel = get_web_channel(channel_id)
    if not channel:
        raise ValueError(f"web channel {channel_id} not found")
    deployments = [d for d in channel["deployments"] if d.get("connection_id") != connection_id]
    conn = _connect()
    conn.execute("UPDATE web_channels SET deployments=?, updated_at=? WHERE id=?",
                 (json.dumps(deployments), _now(), channel_id))
    _commit_with_retry(conn)
    conn.close()
    return get_web_channel(channel_id)


def update_web_channel_deployment(channel_id: int, connection_id: int, updates: dict) -> dict:
    """Merge `updates` into the stored deployment record for one connection
    -- mirrors db.update_deployment exactly (see that function's own
    docstring). Raises ValueError if there's no deployment for that
    connection (caller maps this to a 404)."""
    channel = get_web_channel(channel_id)
    if not channel:
        raise ValueError(f"web channel {channel_id} not found")
    deployments = channel["deployments"]
    if not any(d.get("connection_id") == connection_id for d in deployments):
        raise ValueError(f"no deployment for web channel {channel_id} on connection {connection_id}")
    deployments = [
        {**d, **updates} if d.get("connection_id") == connection_id else d
        for d in deployments
    ]
    conn = _connect()
    conn.execute("UPDATE web_channels SET deployments=?, updated_at=? WHERE id=?",
                 (json.dumps(deployments), _now(), channel_id))
    _commit_with_retry(conn)
    conn.close()
    return get_web_channel(channel_id)


# ── Agent sync (webchannel-renderer-facing) ─────────────────────────────────

def agent_list_active_web_channels() -> list[dict]:
    """What the Node webchannel-renderer polls for -- enabled channels only,
    with grafana_api_token AND session_state decrypted (this is the ONE
    place either is ever returned in plaintext -- the token-authed agent
    endpoint, never the session-authed browser-facing CRUD above)."""
    conn = _connect()
    rows = conn.execute("SELECT * FROM web_channels WHERE enabled=1 ORDER BY slug").fetchall()
    conn.close()
    out = []
    for row in rows:
        d = dict(row)
        raw_session_state = decrypt_value(d["session_state_encrypted"])
        out.append({
            "slug": d["slug"],
            "channel_name": d["channel_name"],
            "source_type": d["source_type"],
            "render_mode": d["render_mode"],
            "target_url": d["target_url"],
            "viewport_width": d["viewport_width"],
            "viewport_height": d["viewport_height"],
            "screenshot_interval_ms": d["screenshot_interval_ms"],
            "page_load_wait_ms": d["page_load_wait_ms"],
            "device_scale_factor": d["device_scale_factor"],
            "dismiss_selector": d["dismiss_selector"],
            "session_state": json.loads(raw_session_state) if raw_session_state else None,
            "grafana_base_url": d["grafana_base_url"],
            "grafana_dashboard_uid": d["grafana_dashboard_uid"],
            "grafana_panel_id": d["grafana_panel_id"],
            "grafana_api_token": decrypt_value(d["grafana_api_token"]),
            "grafana_org_id": d["grafana_org_id"],
            "grafana_time_from": d["grafana_time_from"],
            "grafana_time_to": d["grafana_time_to"],
            "grafana_extra_query": d["grafana_extra_query"],
            "force_render": bool(d["force_render"]),
        })
    return out


def agent_report_web_render_result(slug: str, success: bool, error: str | None = None) -> None:
    conn = _connect()
    row = conn.execute("SELECT id FROM web_channels WHERE slug=?", (slug,)).fetchone()
    if not row:
        conn.close()
        raise ValueError(f"unknown web channel slug '{slug}'")
    conn.execute(
        """UPDATE web_channels
           SET last_render_at=?, last_render_status=?, last_render_error=?, force_render=0, updated_at=?
           WHERE id=?""",
        (_now(), "success" if success else "error", None if success else (error or "unknown error"), _now(), row["id"]),
    )
    _commit_with_retry(conn)
    conn.close()
