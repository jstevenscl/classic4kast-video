"""Classic4Kast Video+'s SQLite store -- weatherstar_channels (fleet channel config,
ported field-for-field from EDM's app/models/weatherstar.py) and
dispatcharr_connections (multi-instance Dispatcharr targets, ported
schema+CRUD from VOD & DVR Manager's vod_db.py). Plain sqlite3, no ORM --
matches VOD Manager's own vod_db.py convention (module-level _connect()/
close() per call, not a long-lived connection or a context-manager
decorator) rather than introducing SQLAlchemy for a two-table product.

FastAPI routes are async, but every function in this module is a plain
synchronous call -- callers wrap them in asyncio.to_thread(...), same
pattern VOD Manager's routes.py uses for its own vod_db calls, rather than
this module trying to be async itself.
"""

import json
import logging
import re
import sqlite3
import time
from datetime import datetime, timezone

from config import DATA_DIR
from secrets_util import decrypt_value, encrypt_value

logger = logging.getLogger(__name__)

DB_PATH = DATA_DIR / "classic4kast.sqlite"

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,98}[a-z0-9]$")
RENDER_MODES = {"on_demand", "fire_on_start", "always_on"}
COUNTRIES = {"US", "CA", "INTL"}

DEFAULT_SCREENS = {
    "showHazards": True,
    "showCurrent": True,
    "showHourly": True,
    "showHourlyGraph": True,
    "showExtendedForecast": True,
    "showRadar": True,
    "showLatestObservations": False,
    "showRegionalForecast": False,
    "showLocalForecast": False,
    "showAlmanac": False,
    "showMarineForecast": False,
    "showAQI": False,
    "showTravel": False,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # WAL + a real timeout so the agent endpoints (polled every few seconds
    # by the renderer) never trip "database is locked" against an admin UI
    # write happening at the same moment.
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=30.0)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.row_factory = sqlite3.Row
    return conn


def _commit_with_retry(conn: sqlite3.Connection, retries: int = 5) -> None:
    for attempt in range(retries):
        try:
            conn.commit()
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == retries - 1:
                raise
            time.sleep(0.5 * (attempt + 1))


def init_db() -> None:
    conn = _connect()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS weatherstar_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT NOT NULL UNIQUE,
            city_name TEXT NOT NULL,
            location_query TEXT NOT NULL,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            units TEXT NOT NULL DEFAULT 'imperial',
            screens TEXT NOT NULL DEFAULT '{}',
            enabled INTEGER NOT NULL DEFAULT 1,
            country TEXT NOT NULL DEFAULT 'US',
            ec_city_id TEXT,
            render_mode TEXT NOT NULL DEFAULT 'on_demand',
            force_render INTEGER NOT NULL DEFAULT 0,
            last_render_at TEXT,
            last_render_status TEXT,
            last_render_error TEXT,
            deployments TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS web_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT NOT NULL UNIQUE,
            channel_name TEXT NOT NULL,
            source_type TEXT NOT NULL DEFAULT 'url',
            enabled INTEGER NOT NULL DEFAULT 1,
            render_mode TEXT NOT NULL DEFAULT 'on_demand',

            target_url TEXT,
            viewport_width INTEGER NOT NULL DEFAULT 1280,
            viewport_height INTEGER NOT NULL DEFAULT 720,
            screenshot_interval_ms INTEGER NOT NULL DEFAULT 1000,
            page_load_wait_ms INTEGER NOT NULL DEFAULT 2000,
            device_scale_factor REAL NOT NULL DEFAULT 1.0,
            dismiss_selector TEXT,
            session_state_encrypted TEXT,

            grafana_base_url TEXT,
            grafana_dashboard_uid TEXT,
            grafana_panel_id TEXT,
            grafana_api_token TEXT,
            grafana_org_id INTEGER NOT NULL DEFAULT 1,
            grafana_time_from TEXT NOT NULL DEFAULT 'now-1h',
            grafana_time_to TEXT NOT NULL DEFAULT 'now',
            grafana_extra_query TEXT,

            force_render INTEGER NOT NULL DEFAULT 0,
            last_render_at TEXT,
            last_render_status TEXT,
            last_render_error TEXT,
            deployments TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS dispatcharr_connections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT NOT NULL,
            url TEXT NOT NULL,
            token TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
    """)
    # ADD COLUMN for a table that may already exist from before this column
    # was introduced -- CREATE TABLE IF NOT EXISTS above is a no-op against
    # an existing web_channels table, so new columns need their own
    # idempotent migration. SQLite has no "ADD COLUMN IF NOT EXISTS"; the
    # try/except-on-duplicate-column is the standard workaround.
    try:
        conn.execute("ALTER TABLE web_channels ADD COLUMN dismiss_selector TEXT")
    except sqlite3.OperationalError as exc:
        if "duplicate column" not in str(exc).lower():
            raise
    try:
        conn.execute("ALTER TABLE web_channels ADD COLUMN session_state_encrypted TEXT")
    except sqlite3.OperationalError as exc:
        if "duplicate column" not in str(exc).lower():
            raise
    _commit_with_retry(conn)
    conn.close()


# ── Channels ─────────────────────────────────────────────────────────────────

def _channel_out(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["screens"]     = json.loads(d["screens"] or "{}")
    d["deployments"] = json.loads(d["deployments"] or "[]")
    d["enabled"]      = bool(d["enabled"])
    d["force_render"] = bool(d["force_render"])
    return d


def list_channels(enabled_only: bool = False) -> list[dict]:
    conn = _connect()
    sql = "SELECT * FROM weatherstar_channels"
    if enabled_only:
        sql += " WHERE enabled=1"
    sql += " ORDER BY city_name"
    rows = [_channel_out(r) for r in conn.execute(sql).fetchall()]
    conn.close()
    return rows


def get_channel(channel_id: int) -> dict | None:
    conn = _connect()
    row = conn.execute("SELECT * FROM weatherstar_channels WHERE id=?", (channel_id,)).fetchone()
    conn.close()
    return _channel_out(row) if row else None


def _validate_country(country: str, ec_city_id: str | None) -> None:
    if country not in COUNTRIES:
        raise ValueError(f"country must be one of {sorted(COUNTRIES)}")
    if country == "CA" and not (ec_city_id or "").strip():
        raise ValueError("ec_city_id is required when country is 'CA' (e.g. 'on-143')")


def create_channel(
    slug: str, city_name: str, location_query: str, lat: float, lon: float,
    units: str = "imperial", screens: dict | None = None, enabled: bool = True,
    render_mode: str = "on_demand", country: str = "US", ec_city_id: str | None = None,
) -> dict:
    slug = slug.strip().lower()
    if not _SLUG_RE.match(slug):
        raise ValueError("slug must be 3-100 lowercase alphanumeric/hyphen characters, not starting or ending with a hyphen")
    if units not in ("imperial", "metric"):
        raise ValueError("units must be 'imperial' or 'metric'")
    if render_mode not in RENDER_MODES:
        raise ValueError(f"render_mode must be one of {sorted(RENDER_MODES)}")
    _validate_country(country, ec_city_id)

    conn = _connect()
    existing = conn.execute("SELECT id FROM weatherstar_channels WHERE slug=?", (slug,)).fetchone()
    if existing:
        conn.close()
        raise ValueError(f"slug '{slug}' is already in use")

    now = _now()
    merged_screens = {**DEFAULT_SCREENS, **(screens or {})}
    cur = conn.execute(
        """INSERT INTO weatherstar_channels
           (slug, city_name, location_query, lat, lon, units, screens, enabled,
            country, ec_city_id, render_mode, force_render, deployments, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,0,'[]',?,?)""",
        (slug, city_name, location_query, lat, lon, units, json.dumps(merged_screens),
         1 if enabled else 0, country, (ec_city_id or "").strip() or None, render_mode, now, now),
    )
    channel_id = cur.lastrowid
    _commit_with_retry(conn)
    conn.close()
    return get_channel(channel_id)


def update_channel(
    channel_id: int, city_name: str | None = None, location_query: str | None = None,
    lat: float | None = None, lon: float | None = None, units: str | None = None,
    screens: dict | None = None, enabled: bool | None = None, render_mode: str | None = None,
    country: str | None = None, ec_city_id: str | None = None,
) -> dict:
    existing = get_channel(channel_id)
    if not existing:
        raise ValueError(f"weatherstar channel {channel_id} not found")
    if units is not None and units not in ("imperial", "metric"):
        raise ValueError("units must be 'imperial' or 'metric'")
    if render_mode is not None and render_mode not in RENDER_MODES:
        raise ValueError(f"render_mode must be one of {sorted(RENDER_MODES)}")
    if country is not None:
        _validate_country(country, ec_city_id if ec_city_id is not None else existing["ec_city_id"])

    fields, params = [], []
    if city_name is not None:
        fields.append("city_name=?"); params.append(city_name)
    if location_query is not None:
        fields.append("location_query=?"); params.append(location_query)
    if lat is not None:
        fields.append("lat=?"); params.append(lat)
    if lon is not None:
        fields.append("lon=?"); params.append(lon)
    if units is not None:
        fields.append("units=?"); params.append(units)
    if screens is not None:
        fields.append("screens=?"); params.append(json.dumps({**existing["screens"], **screens}))
    if enabled is not None:
        fields.append("enabled=?"); params.append(1 if enabled else 0)
    if render_mode is not None:
        fields.append("render_mode=?"); params.append(render_mode)
    if country is not None:
        fields.append("country=?"); params.append(country)
    if ec_city_id is not None:
        fields.append("ec_city_id=?"); params.append(ec_city_id.strip() or None)
    fields.append("updated_at=?"); params.append(_now())
    params.append(channel_id)

    conn = _connect()
    conn.execute(f"UPDATE weatherstar_channels SET {', '.join(fields)} WHERE id=?", params)
    _commit_with_retry(conn)
    conn.close()
    return get_channel(channel_id)


def delete_channel(channel_id: int) -> None:
    if not get_channel(channel_id):
        raise ValueError(f"weatherstar channel {channel_id} not found")
    conn = _connect()
    conn.execute("DELETE FROM weatherstar_channels WHERE id=?", (channel_id,))
    _commit_with_retry(conn)
    conn.close()


def trigger_render(channel_id: int) -> dict:
    if not get_channel(channel_id):
        raise ValueError(f"weatherstar channel {channel_id} not found")
    conn = _connect()
    conn.execute("UPDATE weatherstar_channels SET force_render=1, updated_at=? WHERE id=?", (_now(), channel_id))
    _commit_with_retry(conn)
    conn.close()
    return get_channel(channel_id)


# ── Deployments (JSON list column, one entry per Dispatcharr connection) ────

def add_deployment(channel_id: int, deployment: dict) -> dict:
    channel = get_channel(channel_id)
    if not channel:
        raise ValueError(f"weatherstar channel {channel_id} not found")
    deployments = [*channel["deployments"], deployment]
    conn = _connect()
    conn.execute("UPDATE weatherstar_channels SET deployments=?, updated_at=? WHERE id=?",
                 (json.dumps(deployments), _now(), channel_id))
    _commit_with_retry(conn)
    conn.close()
    return get_channel(channel_id)


def remove_deployment(channel_id: int, connection_id: int) -> dict:
    channel = get_channel(channel_id)
    if not channel:
        raise ValueError(f"weatherstar channel {channel_id} not found")
    deployments = [d for d in channel["deployments"] if d.get("connection_id") != connection_id]
    conn = _connect()
    conn.execute("UPDATE weatherstar_channels SET deployments=?, updated_at=? WHERE id=?",
                 (json.dumps(deployments), _now(), channel_id))
    _commit_with_retry(conn)
    conn.close()
    return get_channel(channel_id)


def update_deployment(channel_id: int, connection_id: int, updates: dict) -> dict:
    """Merge `updates` into the stored deployment record for one connection.
    Raises ValueError if there's no deployment for that connection (caller
    maps this to a 404)."""
    channel = get_channel(channel_id)
    if not channel:
        raise ValueError(f"weatherstar channel {channel_id} not found")
    deployments = channel["deployments"]
    if not any(d.get("connection_id") == connection_id for d in deployments):
        raise ValueError(f"no deployment for channel {channel_id} on connection {connection_id}")
    deployments = [
        {**d, **updates} if d.get("connection_id") == connection_id else d
        for d in deployments
    ]
    conn = _connect()
    conn.execute("UPDATE weatherstar_channels SET deployments=?, updated_at=? WHERE id=?",
                 (json.dumps(deployments), _now(), channel_id))
    _commit_with_retry(conn)
    conn.close()
    return get_channel(channel_id)


# ── Agent sync (renderer-facing) ─────────────────────────────────────────────

def agent_list_active_channels() -> list[dict]:
    """What the renderer polls for -- enabled channels only, in the shape it
    can hand straight through to per-city render logic (see renderer/renderer/
    control_plane_client.py's channel_to_city())."""
    conn = _connect()
    rows = conn.execute("SELECT * FROM weatherstar_channels WHERE enabled=1 ORDER BY slug").fetchall()
    conn.close()
    out = []
    for row in rows:
        c = _channel_out(row)
        out.append({
            "slug": c["slug"],
            "city_name": c["city_name"],
            "query": c["location_query"],
            "lat": c["lat"],
            "lon": c["lon"],
            "units": c["units"],
            "screens": c["screens"],
            "render_mode": c["render_mode"],
            "country": c["country"],
            "ec_city_id": c["ec_city_id"],
            "force_render": c["force_render"],
        })
    return out


def agent_report_render_result(slug: str, success: bool, error: str | None = None) -> None:
    conn = _connect()
    row = conn.execute("SELECT id FROM weatherstar_channels WHERE slug=?", (slug,)).fetchone()
    if not row:
        conn.close()
        raise ValueError(f"unknown weatherstar channel slug '{slug}'")
    conn.execute(
        """UPDATE weatherstar_channels
           SET last_render_at=?, last_render_status=?, last_render_error=?, force_render=0, updated_at=?
           WHERE id=?""",
        (_now(), "success" if success else "error", None if success else (error or "unknown error"), _now(), row["id"]),
    )
    _commit_with_retry(conn)
    conn.close()


# ── Dispatcharr connections ─────────────────────────────────────────────────
# Ported schema+CRUD from VOD & DVR Manager's vod_db.py (dispatcharr_connections
# table) -- token is encrypted at rest via secrets_util, same as VOD Manager.
# Zero rows here = pure standalone renderer mode, no Dispatcharr UI shown.

def create_dispatcharr_connection(label: str, url: str, token: str) -> int:
    conn = _connect()
    cur = conn.execute(
        "INSERT INTO dispatcharr_connections (label, url, token, created_at) VALUES (?,?,?,?)",
        (label, url.rstrip("/"), encrypt_value(token), _now()),
    )
    connection_id = cur.lastrowid
    _commit_with_retry(conn)
    conn.close()
    return connection_id


def list_dispatcharr_connections() -> list[dict]:
    conn = _connect()
    rows = [dict(r) for r in conn.execute("SELECT * FROM dispatcharr_connections ORDER BY created_at ASC").fetchall()]
    conn.close()
    for r in rows:
        r["token"] = decrypt_value(r["token"])
    return rows


def get_dispatcharr_connection(connection_id: int) -> dict | None:
    conn = _connect()
    row = conn.execute("SELECT * FROM dispatcharr_connections WHERE id=?", (connection_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["token"] = decrypt_value(d["token"])
    return d


def update_dispatcharr_connection(
    connection_id: int, label: str | None = None, url: str | None = None, token: str | None = None,
) -> None:
    conn = _connect()
    if label is not None:
        conn.execute("UPDATE dispatcharr_connections SET label=? WHERE id=?", (label, connection_id))
    if url is not None:
        conn.execute("UPDATE dispatcharr_connections SET url=? WHERE id=?", (url.rstrip("/"), connection_id))
    if token is not None:
        conn.execute("UPDATE dispatcharr_connections SET token=? WHERE id=?", (encrypt_value(token), connection_id))
    _commit_with_retry(conn)
    conn.close()


def delete_dispatcharr_connection(connection_id: int) -> None:
    conn = _connect()
    conn.execute("DELETE FROM dispatcharr_connections WHERE id=?", (connection_id,))
    _commit_with_retry(conn)
    conn.close()
