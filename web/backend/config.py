import hashlib
import os
import json
import secrets
from pathlib import Path

from cryptography.fernet import Fernet

DATA_DIR    = Path(os.environ.get("DATA_DIR", "/app/data"))
CONFIG_FILE = DATA_DIR / "config.json"

# 8283, not VOD & DVR Manager's 8282 -- ported/adjacent product, needs its
# own default port so both can run side by side without a compose collision.
APP_PORT    = int(os.environ.get("APP_PORT", "8283"))

# Single source of truth for the semantic version -- see VOD & DVR Manager's
# config.py for why (main.py's FastAPI(version=...) and any /version/ route
# both import this instead of repeating the literal).
APP_VERSION = "0.1.0"

# Persisted log file for main.py's rotating file handler.
LOG_DIR          = DATA_DIR / "logs"
LOG_FILE         = LOG_DIR / "classic4kast.log"
LOG_BACKUP_COUNT = 5


def _read_raw() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    return {}


def _write_raw(data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2))


# ── Renderer connection ──────────────────────────────────────────────────────
# Same-host-compose is the common case (RENDERER_URL defaults to the compose
# service name), but a split deployment (renderer elsewhere) just needs the
# env var overridden -- no config.json equivalent, this one's infra-shaped
# (set once at deploy time), not something edited from the admin UI.

def get_renderer_url() -> str:
    return os.environ.get("RENDERER_URL", "http://renderer:8090").rstrip("/")


# ── Web-channel renderer connection ─────────────────────────────────────────
# Same reasoning as get_renderer_url() above, pointed at the separate Node/
# Puppeteer webchannel-renderer service instead.

def get_webchannel_renderer_url() -> str:
    return os.environ.get("WEBCHANNEL_RENDERER_URL", "http://webchannel-renderer:8091").rstrip("/")


# ── Agent token ───────────────────────────────────────────────────────────────
# Shared secret the renderer presents (X-Api-Key) when polling the 3 agent
# endpoints -- one token for the whole fleet, not per-renderer, since (like
# EDM's WeatherStar agent) there is exactly one renderer to authenticate.
# Env var wins over config.json, same override convention as everything else
# in this file.

def get_agent_token() -> str:
    env_token = os.environ.get("AGENT_TOKEN")
    if env_token:
        return env_token
    return _read_raw().get("agent_token", "")


def save_agent_token(token: str) -> None:
    data = _read_raw()
    data["agent_token"] = token
    _write_raw(data)


def agent_token_from_env() -> bool:
    return bool(os.environ.get("AGENT_TOKEN"))


# ── Encryption key ───────────────────────────────────────────────────────────
# Lives inside config.json rather than its own file specifically so it rides
# along with config's existing backup/restore/reset lifecycle -- see VOD &
# DVR Manager's config.py for the full reasoning (identical here).

def get_or_create_encryption_key() -> bytes:
    data = _read_raw()
    key = data.get("encryption_key")
    if key:
        return key.encode()
    new_key = Fernet.generate_key()
    data["encryption_key"] = new_key.decode()
    _write_raw(data)
    return new_key


# ── WeatherStar public URL / stream key ─────────────────────────────────────
# Ported from EDM's weatherstar_service.py (WEATHERSTAR_PUBLIC_URL_KEY /
# WEATHERSTAR_STREAM_KEY_KEY), moved from a SystemSetting DB row to flat
# config.json since this product has no generic settings table.
#
# public_url: the address Dispatcharr instances use to reach this product's
# *renderer* HLS output when deployed as a channel -- usually a Tailscale
# address or other real-reachable address, not necessarily a public domain.
#
# stream_key: gates the public HLS endpoint once public_url IS a real public
# domain (see on_demand_server.py's key check in the renderer) -- baked into
# each deployed channel's Stream URL as a path segment (not a query param;
# a query string is NOT guaranteed to propagate to .ts segment requests a
# player derives via plain relative-URL resolution, a path segment is).

def get_public_url() -> str | None:
    return _read_raw().get("public_url") or None


def save_public_url(url: str) -> None:
    data = _read_raw()
    data["public_url"] = url.strip()
    _write_raw(data)


def get_stream_key() -> str | None:
    return _read_raw().get("stream_key") or None


def save_stream_key(key: str) -> None:
    data = _read_raw()
    data["stream_key"] = key.strip()
    _write_raw(data)


# ── Idle timeout (renderer on-demand reaper) ────────────────────────────────
# Polled live by the renderer's agent settings call so it can change without
# a container restart -- see renderer/renderer/control_plane_client.py's
# fetch_idle_timeout_seconds. Default matches that file's own
# IDLE_TIMEOUT_FALLBACK_SECONDS default of 600s.

def get_idle_timeout_seconds() -> int:
    return int(_read_raw().get("idle_timeout_seconds") or 600)


def save_idle_timeout_seconds(seconds: int) -> None:
    data = _read_raw()
    data["idle_timeout_seconds"] = max(10, int(seconds))
    _write_raw(data)


# ── Dispatcharr integration toggle ──────────────────────────────────────────
# Some users run this purely standalone (an HLS URL handed to a player
# directly, no Dispatcharr at all) and don't want the Dispatcharr nav item,
# deploy buttons, or connection-specific settings cluttering the UI. Default
# True -- Dispatcharr deploy is this product's primary use case, so it's
# opt-out, not opt-in. Purely a UI-visibility flag: turning it off does NOT
# touch any existing connections/deployments, just hides the controls for
# them (a user flips it back on and everything's still there).

def get_dispatcharr_enabled() -> bool:
    return bool(_read_raw().get("dispatcharr_enabled", True))


def save_dispatcharr_enabled(enabled: bool) -> None:
    data = _read_raw()
    data["dispatcharr_enabled"] = bool(enabled)
    _write_raw(data)


# ── HLS live-window size (player-side stutter cushion) ──────────────────────
# Number of segments ffmpeg keeps in the live manifest (renderer's own
# -hls_list_size). At the renderer's fixed 6s segment length, the default of
# 16 is a 96s window -- raised from the original 10 (60s) after live testing
# 2026-08-24 still showed occasional multi-second hangs even on a direct
# connection (no Dispatcharr Proxy hop involved), suggesting real segment-
# production jitter exists in the pipeline that a wider cushion can absorb.
# This is a FIXED amount of extra headroom, not unbounded growth -- doesn't
# reintroduce the kind of drift Dispatcharr's Proxy profile caused. Polled
# live by the renderer's agent settings call, same as idle_timeout_seconds
# above -- takes effect on that channel's next ffmpeg start (cold start,
# idle-stop/resume, or a watchdog restart), not instantly mid-stream, since
# it's an ffmpeg startup argument that can't change while a process is
# already running.

def get_hls_list_size() -> int:
    return int(_read_raw().get("hls_list_size") or 16)


def save_hls_list_size(size: int) -> None:
    data = _read_raw()
    data["hls_list_size"] = max(4, int(size))
    _write_raw(data)


# ── HLS segment length (join-point stutter, distinct from the buffer-window
# cushion above) ──────────────────────────────────────────────────────────
# Segment boundaries are their own source of player-side stutter -- a brief
# decoder hiccup at every join, independent of whether data was actually
# available in time (that's what hls_list_size protects against). Confirmed
# live 2026-08-24: bumping hls_list_size 10->16 alone did NOT fix observed
# VLC stutter (playback clock stayed in sync throughout, ruling out buffer
# starvation as the cause) -- pointing at join-point frequency instead, the
# same diagnosis this renderer's own history already reached once before
# (hls_time 2->6). Same live-configurable/polled-by-renderer pattern as
# hls_list_size; only takes effect on a channel's next restart.

def get_hls_time_seconds() -> int:
    return int(_read_raw().get("hls_time_seconds") or 6)


def save_hls_time_seconds(seconds: int) -> None:
    data = _read_raw()
    data["hls_time_seconds"] = max(2, int(seconds))
    _write_raw(data)


# ── Auth ──────────────────────────────────────────────────────────────────────
# PBKDF2-HMAC-SHA256, 260k iterations -- ported verbatim from VOD & DVR
# Manager's config.py (see that file's comment for the full rationale on why
# PBKDF2 over a plain hash). Env var names are this product's own
# (CLASSIC4KAST_ADMIN_USER/PASSWORD) rather than VOD Manager's.

_PBKDF2_ITERATIONS = 260_000


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ITERATIONS).hex()


def has_credentials() -> bool:
    if os.environ.get("CLASSIC4KAST_ADMIN_USER") and os.environ.get("CLASSIC4KAST_ADMIN_PASSWORD"):
        return True
    data = _read_raw()
    return bool(data.get("auth_username") and data.get("auth_hash"))


def verify_credentials(username: str, password: str) -> bool:
    env_user = os.environ.get("CLASSIC4KAST_ADMIN_USER", "")
    env_pass = os.environ.get("CLASSIC4KAST_ADMIN_PASSWORD", "")
    if env_user and env_pass:
        return (
            secrets.compare_digest(username.encode(), env_user.encode()) and
            secrets.compare_digest(password.encode(), env_pass.encode())
        )
    data        = _read_raw()
    stored_user = data.get("auth_username", "")
    stored_salt = data.get("auth_salt", "")
    stored_hash = data.get("auth_hash", "")
    if not (stored_user and stored_salt and stored_hash):
        return False
    if not secrets.compare_digest(username.encode(), stored_user.encode()):
        return False
    candidate = _hash_password(password, stored_salt)
    return secrets.compare_digest(candidate.encode(), stored_hash.encode())


def set_credentials(username: str, password: str) -> None:
    salt   = secrets.token_hex(16)
    hashed = _hash_password(password, salt)
    data   = _read_raw()
    data.update({"auth_username": username, "auth_salt": salt, "auth_hash": hashed})
    _write_raw(data)
