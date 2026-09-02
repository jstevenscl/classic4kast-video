"""Classic4Kast Video+'s API: admin auth, channel CRUD, Dispatcharr connections + deploy
logic, and the token-authed agent endpoints the renderer polls. Ported/
adapted from:
  - VOD & DVR Manager's routes.py (auth/login/settings pattern, per-IP lockout)
  - VOD & DVR Manager's vod_routes.py (dispatcharr-connections CRUD + redact/
    reveal pattern)
  - EDM's app/api/v1/weatherstar.py (channel CRUD, deploy/deploy-bulk/
    undeploy/refresh/refresh-all, channel-profile-membership, agent endpoints)

Biggest structural change from EDM: EDM had exactly one Dispatcharr
"Instance" (a DB-backed singleton). This product supports zero, one, or many
Dispatcharr connections (see db.py's dispatcharr_connections table), so every
deploy route takes a connection_id and constructs
DispatcharrClient(connection["url"], connection["token"]) per-call, same as
VOD & DVR Manager already does for its own multi-connection support.
"""
import asyncio
import logging
import os
import time
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

import db
from auth import create_session, revoke_all_sessions, revoke_session, verify_session
from config import (
    APP_VERSION, get_agent_token, get_dispatcharr_enabled, get_hls_list_size, get_hls_time_seconds,
    get_idle_timeout_seconds, get_public_url, get_renderer_url, get_stream_key, has_credentials,
    clear_credentials, credentials_choice_made, mark_credentials_choice_made, save_dispatcharr_enabled,
    save_hls_list_size, save_hls_time_seconds, save_idle_timeout_seconds, save_public_url, save_stream_key,
    set_credentials, verify_credentials,
)
from dispatcharr_client import DispatcharrClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["classic4kast-core"])

# Agent sync has its own token auth (not a session), so it's a separate,
# unauthenticated-at-the-router-level router -- the renderer container never
# needs a real admin login.
agent_router = APIRouter(prefix="/api/agent", tags=["classic4kast-agent"])

if not has_credentials():
    logger.warning(
        "[routes] No admin login is configured yet -- every API route is unauthenticated until "
        "one is set (Settings, or the first-run screen). If this instance is reachable from "
        "outside a trusted network, set a login now."
    )


# ── Guards ────────────────────────────────────────────────────────────────────

async def require_auth(x_session_token: Optional[str] = Header(None, alias="X-Session-Token")):
    if not has_credentials():
        return  # no credentials configured yet -- auth not enforced yet
    if not x_session_token or not verify_session(x_session_token):
        raise HTTPException(401, detail="unauthorized")


_GUARDS = [Depends(require_auth)]


def _check_agent_token(x_api_key: str) -> None:
    token = get_agent_token()
    if not token or x_api_key != token:
        raise HTTPException(status_code=401, detail="invalid or missing X-Api-Key")


# Brute-force protection for the admin login -- same shape as VOD & DVR
# Manager's routes.py (per-IP, in-memory, resets on restart).
_LOGIN_MAX_ATTEMPTS = 8
_LOGIN_WINDOW_SECONDS = 300
_LOGIN_LOCKOUT_SECONDS = 900
_LOGIN_SWEEP_INTERVAL_SECONDS = 600

_login_failed_attempts: dict[str, tuple[int, float]] = {}
_login_locked_until: dict[str, float] = {}
_login_last_sweep_at = 0.0


def _login_client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _sweep_expired_login_entries() -> None:
    global _login_last_sweep_at
    now = time.monotonic()
    if now - _login_last_sweep_at < _LOGIN_SWEEP_INTERVAL_SECONDS:
        return
    _login_last_sweep_at = now
    for ip, (_, window_started) in list(_login_failed_attempts.items()):
        if now - window_started > _LOGIN_WINDOW_SECONDS:
            _login_failed_attempts.pop(ip, None)
    for ip, expires in list(_login_locked_until.items()):
        if now >= expires:
            _login_locked_until.pop(ip, None)


def _login_locked_out(ip: str) -> bool:
    _sweep_expired_login_entries()
    expires = _login_locked_until.get(ip)
    if expires is None:
        return False
    if time.monotonic() >= expires:
        del _login_locked_until[ip]
        return False
    return True


def _record_login_failure(ip: str) -> None:
    now = time.monotonic()
    count, window_started = _login_failed_attempts.get(ip, (0, now))
    if now - window_started > _LOGIN_WINDOW_SECONDS:
        count, window_started = 0, now
    count += 1
    if count >= _LOGIN_MAX_ATTEMPTS:
        _login_locked_until[ip] = now + _LOGIN_LOCKOUT_SECONDS
        _login_failed_attempts.pop(ip, None)
        logger.warning("[routes] %s locked out of admin login for %ds after %d failed attempts",
                        ip, _LOGIN_LOCKOUT_SECONDS, count)
    else:
        _login_failed_attempts[ip] = (count, window_started)


# ── Request models ────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class CredentialsRequest(BaseModel):
    username: str
    password: str


class ChannelCreate(BaseModel):
    slug: str
    city_name: str
    location_query: str
    lat: float
    lon: float
    units: str = "imperial"
    screens: dict = {}
    enabled: bool = True
    render_mode: str = "on_demand"
    country: str = "US"
    ec_city_id: str | None = None


class ChannelUpdate(BaseModel):
    city_name: str | None = None
    location_query: str | None = None
    lat: float | None = None
    lon: float | None = None
    units: str | None = None
    screens: dict | None = None
    enabled: bool | None = None
    render_mode: str | None = None
    country: str | None = None
    ec_city_id: str | None = None


class RenderResult(BaseModel):
    slug: str
    success: bool
    error: str | None = None


class PublicUrlUpdate(BaseModel):
    url: str


class StreamKeyUpdate(BaseModel):
    key: str


class IdleTimeoutUpdate(BaseModel):
    seconds: int


class HlsListSizeUpdate(BaseModel):
    size: int


class HlsTimeUpdate(BaseModel):
    seconds: int


class DispatcharrEnabledUpdate(BaseModel):
    enabled: bool


class DispatcharrConnectionRequest(BaseModel):
    label: str
    url: str
    token: str


class DispatcharrConnectionUpdateRequest(BaseModel):
    label: str | None = None
    url: str | None = None
    token: str | None = None


class DispatcharrConnectionTestRequest(BaseModel):
    url: str
    token: str


class DeployRequest(BaseModel):
    connection_id: int
    channel_group_id: int
    name: str | None = None
    stream_profile_id: int | None = None
    logo_url: str | None = None
    # None (omitted): Dispatcharr's own default -- every profile on the
    # connection. []: no profiles. [ids]: exactly those profiles. Passed
    # straight through to Dispatcharr's channel_profile_ids semantics.
    channel_profile_ids: list[int] | None = None
    # None (omitted): auto-assign the group's next free number, same as
    # before. Set: use exactly this number -- Dispatcharr itself rejects the
    # request if it's already taken in that group, surfaced as a normal
    # deploy-failed error.
    channel_number: int | None = None


class BulkDeployRequest(BaseModel):
    connection_ids: list[int]
    channel_group_name: str
    stream_profile_name: str | None = None
    name: str | None = None
    logo_url: str | None = None
    # By NAME, not id -- profile/group ids are local to one Dispatcharr
    # connection and don't carry across the several connections a bulk
    # deploy targets. Resolved to each connection's own id independently.
    channel_profile_names: list[str] | None = None
    # Same explicit-number override as DeployRequest, applied identically on
    # every targeted connection -- there's no per-connection numbering in
    # bulk mode.
    channel_number: int | None = None


class UpdateChannelProfilesRequest(BaseModel):
    channel_profile_ids: list[int]


# ── Auth endpoints (no auth required) ────────────────────────────────────────

@router.post("/auth/login/")
async def login(body: LoginRequest, request: Request):
    ip = _login_client_ip(request)
    if _login_locked_out(ip):
        raise HTTPException(429, detail="Too many failed login attempts. Try again later.")
    if not verify_credentials(body.username, body.password):
        _record_login_failure(ip)
        raise HTTPException(401, detail="Invalid username or password")
    _login_failed_attempts.pop(ip, None)
    return {"token": create_session()}


@router.get("/auth/verify/")
async def auth_verify(x_session_token: Optional[str] = Header(None, alias="X-Session-Token")):
    if not has_credentials():
        return {"valid": True, "no_credentials": True}
    return {"valid": bool(x_session_token and verify_session(x_session_token))}


@router.post("/auth/logout/")
async def logout(x_session_token: Optional[str] = Header(None, alias="X-Session-Token")):
    if x_session_token:
        revoke_session(x_session_token)
    return {"ok": True}


# ── Settings endpoints ────────────────────────────────────────────────────────

def _credentials_env_override() -> bool:
    return bool(os.environ.get("CLASSIC4KAST_ADMIN_USER") and os.environ.get("CLASSIC4KAST_ADMIN_PASSWORD"))


@router.get("/settings/")
async def get_settings():
    return {
        "has_credentials": has_credentials(),
        "credentials_env_override": _credentials_env_override(),
        "credentials_choice_made": credentials_choice_made() or _credentials_env_override(),
        "version": APP_VERSION,
        "dispatcharr_enabled": get_dispatcharr_enabled(),
    }


@router.post("/settings/dispatcharr-enabled/", dependencies=_GUARDS)
async def set_dispatcharr_enabled_endpoint(body: DispatcharrEnabledUpdate):
    save_dispatcharr_enabled(body.enabled)
    return {"ok": True}


@router.post("/settings/credentials/")
async def set_credentials_endpoint(
    body: CredentialsRequest,
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token"),
):
    if _credentials_env_override():
        raise HTTPException(400, detail="Admin credentials are pinned via CLASSIC4KAST_ADMIN_USER/PASSWORD and can't be changed here.")
    if has_credentials():
        if not (x_session_token and verify_session(x_session_token)):
            raise HTTPException(401, detail="unauthorized")
    if not body.username.strip():
        raise HTTPException(400, detail="Username is required.")
    if len(body.password) < 6:
        raise HTTPException(400, detail="Password must be at least 6 characters.")
    set_credentials(body.username.strip(), body.password)
    mark_credentials_choice_made()
    revoke_all_sessions(except_token=x_session_token)
    # A fresh token so the caller (first-run screen, or Settings enabling
    # login for the first time) lands straight in the app instead of being
    # immediately bounced to a login screen for credentials it just typed.
    return {"ok": True, "token": create_session()}


@router.post("/settings/credentials/skip/")
async def skip_credentials_endpoint():
    """First-run "skip for now" -- records that the prompt was actually
    shown and dismissed, distinct from has_credentials() staying False, so
    the one-time prompt doesn't resurface on the next page load. Anyone can
    call this while no credentials exist yet (nothing to protect); once
    credentials are set, the first-run prompt can never show again anyway,
    so this route doesn't need to handle that case."""
    if has_credentials():
        return {"ok": True}
    mark_credentials_choice_made()
    return {"ok": True}


@router.delete("/settings/credentials/")
async def clear_credentials_endpoint(x_session_token: Optional[str] = Header(None, alias="X-Session-Token")):
    if _credentials_env_override():
        raise HTTPException(400, detail="Admin credentials are pinned via CLASSIC4KAST_ADMIN_USER/PASSWORD and can't be changed here.")
    if not has_credentials():
        return {"ok": True}
    if not (x_session_token and verify_session(x_session_token)):
        raise HTTPException(401, detail="unauthorized")
    clear_credentials()
    revoke_all_sessions()
    return {"ok": True}


# ── Config: public URL / stream key / idle timeout ──────────────────────────

@router.get("/config/public-url/", dependencies=_GUARDS)
async def get_public_url_endpoint():
    return {"url": get_public_url()}


@router.post("/config/public-url/", dependencies=_GUARDS)
async def set_public_url_endpoint(body: PublicUrlUpdate):
    save_public_url(body.url)
    return {"ok": True}


@router.get("/config/stream-key/", dependencies=_GUARDS)
async def get_stream_key_endpoint():
    return {"key": get_stream_key()}


@router.post("/config/stream-key/", dependencies=_GUARDS)
async def set_stream_key_endpoint(body: StreamKeyUpdate):
    save_stream_key(body.key)
    return {"ok": True}


@router.get("/config/idle-timeout/", dependencies=_GUARDS)
async def get_idle_timeout_endpoint():
    return {"seconds": get_idle_timeout_seconds()}


@router.post("/config/idle-timeout/", dependencies=_GUARDS)
async def set_idle_timeout_endpoint(body: IdleTimeoutUpdate):
    save_idle_timeout_seconds(body.seconds)
    return {"ok": True}


@router.get("/config/hls-list-size/", dependencies=_GUARDS)
async def get_hls_list_size_endpoint():
    return {"size": get_hls_list_size()}


@router.post("/config/hls-list-size/", dependencies=_GUARDS)
async def set_hls_list_size_endpoint(body: HlsListSizeUpdate):
    save_hls_list_size(body.size)
    return {"ok": True}


@router.get("/config/hls-time/", dependencies=_GUARDS)
async def get_hls_time_endpoint():
    return {"seconds": get_hls_time_seconds()}


@router.post("/config/hls-time/", dependencies=_GUARDS)
async def set_hls_time_endpoint(body: HlsTimeUpdate):
    save_hls_time_seconds(body.seconds)
    return {"ok": True}


# ── Renderer status proxy ────────────────────────────────────────────────────

@router.get("/status/", dependencies=_GUARDS)
async def get_status():
    """Which channels currently have a real viewer -- Dispatcharr itself
    can never show this for a "Redirect"-profile deploy (the player is
    redirected straight to the renderer, so Dispatcharr's own proxy never
    sees the connection). Proxies the renderer container's own /status."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            r = await client.get(f"{get_renderer_url()}/status")
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"renderer unreachable: {exc}")
    return r.json()


# ── Channel CRUD ─────────────────────────────────────────────────────────────

@router.get("/channels/", dependencies=_GUARDS)
async def get_channels(enabled_only: bool = False):
    return await asyncio.to_thread(db.list_channels, enabled_only)


@router.post("/channels/", dependencies=_GUARDS)
async def post_channel(body: ChannelCreate):
    try:
        return await asyncio.to_thread(
            db.create_channel, body.slug, body.city_name, body.location_query, body.lat, body.lon,
            body.units, body.screens, body.enabled, body.render_mode, body.country, body.ec_city_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/channels/{channel_id}/", dependencies=_GUARDS)
async def patch_channel(channel_id: int, body: ChannelUpdate):
    try:
        return await asyncio.to_thread(
            db.update_channel, channel_id, body.city_name, body.location_query, body.lat, body.lon,
            body.units, body.screens, body.enabled, body.render_mode, body.country, body.ec_city_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/channels/{channel_id}/", dependencies=_GUARDS)
async def remove_channel(channel_id: int):
    try:
        await asyncio.to_thread(db.delete_channel, channel_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True}


@router.post("/channels/{channel_id}/render/", dependencies=_GUARDS)
async def post_trigger_render(channel_id: int):
    try:
        return await asyncio.to_thread(db.trigger_render, channel_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── Dispatcharr connections ─────────────────────────────────────────────────
# Ported CRUD + redact/reveal pattern from VOD & DVR Manager's vod_routes.py.
# Zero rows = pure standalone mode; the frontend hides all Dispatcharr UI
# when this list is empty.

def _redact_connection(c: dict) -> dict:
    c = dict(c)
    c["has_token"] = bool(c.pop("token", None))
    return c


@router.get("/dispatcharr-connections/", dependencies=_GUARDS)
async def list_dispatcharr_connections_endpoint():
    rows = await asyncio.to_thread(db.list_dispatcharr_connections)
    return [_redact_connection(c) for c in rows]


@router.get("/dispatcharr-connections/{connection_id}/token/", dependencies=_GUARDS)
async def reveal_dispatcharr_connection_token(connection_id: int):
    connection = await asyncio.to_thread(db.get_dispatcharr_connection, connection_id)
    if not connection:
        raise HTTPException(404, detail="connection not found")
    return {"token": connection["token"]}


@router.post("/dispatcharr-connections/connect/", dependencies=_GUARDS)
async def test_dispatcharr_connection_endpoint(body: DispatcharrConnectionTestRequest):
    """Verify a Dispatcharr url/token actually works before it's saved --
    used by the "Test connection" button in the connection-add form."""
    client = DispatcharrClient(body.url.strip(), body.token.strip())
    try:
        raw = await client.get("/api/channels/groups/")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"could not connect: {exc}")
    groups = raw.get("results", raw) if isinstance(raw, dict) else raw
    return {"ok": True, "group_count": len(groups)}


@router.post("/dispatcharr-connections/", dependencies=_GUARDS)
async def create_dispatcharr_connection_endpoint(body: DispatcharrConnectionRequest):
    label, url, token = body.label.strip(), body.url.strip(), body.token.strip()
    if not label or not url or not token:
        raise HTTPException(400, detail="label, url, and token are all required")
    connection_id = await asyncio.to_thread(db.create_dispatcharr_connection, label, url, token)
    connection = await asyncio.to_thread(db.get_dispatcharr_connection, connection_id)
    return _redact_connection(connection)


@router.patch("/dispatcharr-connections/{connection_id}/", dependencies=_GUARDS)
async def update_dispatcharr_connection_endpoint(connection_id: int, body: DispatcharrConnectionUpdateRequest):
    if not await asyncio.to_thread(db.get_dispatcharr_connection, connection_id):
        raise HTTPException(404, detail="connection not found")
    await asyncio.to_thread(
        db.update_dispatcharr_connection, connection_id,
        body.label.strip() if body.label is not None else None,
        body.url.strip() if body.url is not None else None,
        body.token.strip() if body.token is not None else None,
    )
    connection = await asyncio.to_thread(db.get_dispatcharr_connection, connection_id)
    return _redact_connection(connection)


@router.delete("/dispatcharr-connections/{connection_id}/", dependencies=_GUARDS)
async def delete_dispatcharr_connection_endpoint(connection_id: int):
    if not await asyncio.to_thread(db.get_dispatcharr_connection, connection_id):
        raise HTTPException(404, detail="connection not found")
    await asyncio.to_thread(db.delete_dispatcharr_connection, connection_id)
    return {"ok": True}


async def _client_for_connection(connection_id: int) -> tuple[dict, DispatcharrClient]:
    connection = await asyncio.to_thread(db.get_dispatcharr_connection, connection_id)
    if not connection:
        raise HTTPException(404, detail=f"dispatcharr connection {connection_id} not found")
    return connection, DispatcharrClient(connection["url"], connection["token"])


@router.get("/dispatcharr-connections/{connection_id}/groups/", dependencies=_GUARDS)
async def get_connection_groups(connection_id: int):
    """Channel groups on this connection, pre-filtered to channel_count > 0
    -- excludes stream-import-only groups (Dispatcharr's own convention for
    organizing raw provider streams, never meaningful as a WeatherStar
    deploy target). Ported from EDM's WeatherStar.tsx, which used to apply
    this filter client-side; moved server-side here so the frontend can just
    consume filtered data directly instead of re-implementing the filter."""
    _connection, client = await _client_for_connection(connection_id)
    try:
        raw = await client.get("/api/channels/groups/")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"failed to list channel groups: {exc}")
    groups = raw.get("results", raw) if isinstance(raw, dict) else raw
    return [g for g in groups if int(g.get("channel_count") or 0) > 0]


@router.get("/dispatcharr-connections/{connection_id}/stream-profiles/", dependencies=_GUARDS)
async def get_connection_stream_profiles(connection_id: int):
    _connection, client = await _client_for_connection(connection_id)
    try:
        raw = await client.get("/api/core/streamprofiles/")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"failed to list stream profiles: {exc}")
    return raw if isinstance(raw, list) else raw.get("results", [])


@router.get("/dispatcharr-connections/{connection_id}/channel-profiles/", dependencies=_GUARDS)
async def get_connection_channel_profiles(connection_id: int):
    _connection, client = await _client_for_connection(connection_id)
    try:
        raw = await client.get("/api/channels/profiles/")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"failed to list channel profiles: {exc}")
    return raw.get("results", raw) if isinstance(raw, dict) else raw


# ── Deploy ────────────────────────────────────────────────────────────────────
# Creates a real custom Stream (this channel's public HLS URL) + a real
# Channel on the target Dispatcharr connection, in the chosen channel group,
# at that group's next free channel number. Direct port of EDM's
# _deploy_to_instance, adapted from a single global "instance" to a
# per-connection client + connection_id/connection_label deployment record.
#
# DEFAULT_STREAM_PROFILE_NAME: not enforced here (the caller picks a profile
# id/name explicitly, same as EDM), but this is the recommended default the
# frontend should pre-fill -- Dispatcharr's "Proxy" profile was measured
# live against this renderer causing 10-12 min/hour clock drift vs. a
# steady, direct origin stream. "Redirect" sends the player straight to the
# renderer's own stream instead of routing bytes through Dispatcharr, so
# there's no proxy-side buffering/timing to drift against in the first
# place. Keep this as the default -- it's a measured fix, not a stylistic
# choice.
DEFAULT_STREAM_PROFILE_NAME = "Redirect"


def _stream_url(channel: dict) -> str:
    public_url = get_public_url()
    if not public_url:
        raise HTTPException(
            status_code=400,
            detail="Set the public URL first (Settings) -- a Dispatcharr connection needs a real "
                   "reachable address for this stream, e.g. a Tailscale address or public domain.",
        )
    stream_key = get_stream_key()
    key_segment = f"/{stream_key}" if stream_key else ""
    return f"{public_url.rstrip('/')}/weatherstar/{channel['slug']}{key_segment}/stream.m3u8"


async def _deploy_to_connection(
    client: DispatcharrClient, connection: dict, channel: dict,
    channel_group_id: int, name: str | None, stream_profile_id: int | None,
    logo_url: str | None, channel_profile_ids: list[int] | None = None,
    channel_number: int | None = None,
) -> dict:
    stream_url = _stream_url(channel)

    group = await client.get(f"/api/channels/groups/{channel_group_id}/")

    if channel_number is not None:
        next_number = channel_number
    else:
        existing = await client.get(
            "/api/channels/channels/",
            params={"channel_group": group["name"], "ordering": "-channel_number", "page_size": 1},
        )
        results = existing.get("results", existing) if isinstance(existing, dict) else existing
        next_number = int(results[0]["channel_number"]) + 1 if results else 1

    resolved_name = (name or "").strip() or f"WeatherStar - {channel['city_name']}"
    # Channel's write field is "channel_group_id" -- "channel_group" is
    # silently ignored on create/update (confirmed live against Dispatcharr,
    # see EDM's own note on this), channel just lands in whatever group_id=1
    # happens to be.
    channel_payload = {
        "name": resolved_name,
        "channel_group_id": channel_group_id,
        "channel_number": next_number,
        "tvg_id": f"classic4kast-{channel['slug']}",
    }
    if stream_profile_id is not None:
        channel_payload["stream_profile_id"] = stream_profile_id
    if channel_profile_ids is not None:
        channel_payload["channel_profile_ids"] = channel_profile_ids

    resolved_logo_url = (logo_url or "").strip() or None
    if resolved_logo_url:
        # Channel has no direct logo_url write field either (same silent-
        # ignore behavior) -- logos are their own object; create one and
        # reference it by id. Non-fatal: skip attaching a logo rather than
        # failing the whole deploy over cosmetics (Dispatcharr enforces a
        # unique constraint on Logo.url with no working search, so a repeat
        # deploy using the same default icon would otherwise 400 here).
        try:
            logo = await client.post("/api/channels/logos/", {"name": resolved_name, "url": resolved_logo_url})
            channel_payload["logo_id"] = logo["id"]
        except Exception as exc:
            logger.warning("[classic4kast] logo creation skipped for channel %s -> connection %s (likely duplicate URL): %s",
                            channel["id"], connection["id"], exc)

    stream = await client.post("/api/channels/streams/", {"name": resolved_name, "url": stream_url})
    dispatcharr_channel = await client.post(
        "/api/channels/channels/", {**channel_payload, "streams": [stream["id"]]},
    )

    return await asyncio.to_thread(db.add_deployment, channel["id"], {
        "connection_id": connection["id"],
        "connection_label": connection["label"],
        "name": resolved_name,
        "stream_profile_id": stream_profile_id,
        "logo_url": resolved_logo_url,
        "channel_group_id": channel_group_id,
        "channel_group_name": group["name"],
        "channel_number": next_number,
        "dispatcharr_channel_id": dispatcharr_channel["id"],
        "dispatcharr_stream_id": stream["id"],
        "channel_profile_ids": channel_profile_ids,
    })


async def _get_channel_or_404(channel_id: int) -> dict:
    channel = await asyncio.to_thread(db.get_channel, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail=f"weatherstar channel {channel_id} not found")
    return channel


@router.post("/channels/{channel_id}/deploy/", dependencies=_GUARDS)
async def post_deploy_channel(channel_id: int, body: DeployRequest):
    channel = await _get_channel_or_404(channel_id)
    if any(d.get("connection_id") == body.connection_id for d in channel["deployments"]):
        raise HTTPException(status_code=400, detail="already deployed to this connection -- remove it first to redeploy")

    connection, client = await _client_for_connection(body.connection_id)

    try:
        return await _deploy_to_connection(
            client, connection, channel, body.channel_group_id, body.name,
            body.stream_profile_id, body.logo_url, body.channel_profile_ids,
            body.channel_number,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[classic4kast] deploy failed for channel %s -> connection %s: %s", channel_id, body.connection_id, exc)
        raise HTTPException(status_code=502, detail=f"Deploy failed: {exc}")


# Deploys to MULTIPLE connections in one call -- resolves the channel group
# (and, if given, stream profile) by NAME independently on each connection
# rather than requiring their numeric ids to line up. Each connection is
# attempted independently: one connection failing never blocks the others.
@router.post("/channels/{channel_id}/deploy-bulk/", dependencies=_GUARDS)
async def post_deploy_channel_bulk(channel_id: int, body: BulkDeployRequest):
    channel = await _get_channel_or_404(channel_id)

    # Public URL is checked once up front (same error for every connection),
    # not repeated per-connection below.
    _stream_url(channel)

    group_name_lower = body.channel_group_name.strip().lower()
    profile_name_lower = (body.stream_profile_name or "").strip().lower() or None

    results = []
    for connection_id in body.connection_ids:
        # Re-fetch each iteration -- add_deployment from a prior connection
        # in this same loop just mutated the deployments list, and this
        # check must see that (otherwise a duplicate connection_id in the
        # request could double-deploy).
        current = await asyncio.to_thread(db.get_channel, channel_id)
        if any(d.get("connection_id") == connection_id for d in (current or channel)["deployments"]):
            results.append({"connection_id": connection_id, "ok": False, "error": "already deployed to this connection"})
            continue

        connection = await asyncio.to_thread(db.get_dispatcharr_connection, connection_id)
        if connection is None:
            results.append({"connection_id": connection_id, "ok": False, "error": "connection not found"})
            continue
        client = DispatcharrClient(connection["url"], connection["token"])

        try:
            groups_raw = await client.get("/api/channels/groups/")
            groups = groups_raw.get("results", groups_raw) if isinstance(groups_raw, dict) else groups_raw
            group = next((g for g in groups if g["name"].strip().lower() == group_name_lower), None)
            if group is None:
                results.append({"connection_id": connection_id, "connection_label": connection["label"], "ok": False,
                                 "error": f'no channel group named "{body.channel_group_name}" on this connection'})
                continue

            stream_profile_id = None
            if profile_name_lower:
                profiles_raw = await client.get("/api/core/streamprofiles/")
                profiles = profiles_raw if isinstance(profiles_raw, list) else profiles_raw.get("results", [])
                profile = next((p for p in profiles if p["name"].strip().lower() == profile_name_lower), None)
                if profile is None:
                    results.append({"connection_id": connection_id, "connection_label": connection["label"], "ok": False,
                                     "error": f'no stream profile named "{body.stream_profile_name}" on this connection'})
                    continue
                stream_profile_id = profile["id"]

            channel_profile_ids = None
            if body.channel_profile_names is not None:
                cp_raw = await client.get("/api/channels/profiles/")
                cp_list = cp_raw.get("results", cp_raw) if isinstance(cp_raw, dict) else cp_raw
                cp_by_name = {p["name"].strip().lower(): p["id"] for p in cp_list}
                missing = [n for n in body.channel_profile_names if n.strip().lower() not in cp_by_name]
                if missing:
                    results.append({"connection_id": connection_id, "connection_label": connection["label"], "ok": False,
                                     "error": f'no channel profile(s) named {missing} on this connection'})
                    continue
                channel_profile_ids = [cp_by_name[n.strip().lower()] for n in body.channel_profile_names]

            deployment = await _deploy_to_connection(
                client, connection, channel, group["id"], body.name, stream_profile_id, body.logo_url,
                channel_profile_ids, body.channel_number,
            )
            results.append({"connection_id": connection_id, "connection_label": connection["label"], "ok": True, "deployment": deployment})
        except Exception as exc:
            logger.error("[classic4kast] bulk deploy failed for channel %s -> connection %s: %s", channel_id, connection_id, exc)
            results.append({"connection_id": connection_id, "connection_label": connection.get("label"), "ok": False, "error": str(exc)})

    return {"results": results}


@router.delete("/channels/{channel_id}/deploy/{connection_id}/", dependencies=_GUARDS)
async def delete_deploy_channel(channel_id: int, connection_id: int):
    channel = await _get_channel_or_404(channel_id)
    deployment = next((d for d in channel["deployments"] if d.get("connection_id") == connection_id), None)
    if deployment is None:
        raise HTTPException(status_code=404, detail="not deployed to this connection")

    connection, client = await _client_for_connection(connection_id)
    try:
        await client.delete(f"/api/channels/channels/{deployment['dispatcharr_channel_id']}/")
    except Exception as exc:
        logger.error("[classic4kast] failed to delete channel %s on connection %s: %s", deployment["dispatcharr_channel_id"], connection_id, exc)
    try:
        await client.delete(f"/api/channels/streams/{deployment['dispatcharr_stream_id']}/")
    except Exception as exc:
        logger.error("[classic4kast] failed to delete stream %s on connection %s: %s", deployment["dispatcharr_stream_id"], connection_id, exc)

    return await asyncio.to_thread(db.remove_deployment, channel_id, connection_id)


@router.get("/channels/{channel_id}/deploy/{connection_id}/profiles/", dependencies=_GUARDS)
async def get_deploy_profiles(channel_id: int, connection_id: int):
    """List every channel profile on this connection plus whether this
    deployment's Dispatcharr channel is currently enabled on each one."""
    channel = await _get_channel_or_404(channel_id)
    deployment = next((d for d in channel["deployments"] if d.get("connection_id") == connection_id), None)
    if deployment is None:
        raise HTTPException(status_code=404, detail="not deployed to this connection")

    _connection, client = await _client_for_connection(connection_id)
    dispatcharr_channel_id = deployment["dispatcharr_channel_id"]
    profiles_raw = await client.get("/api/channels/profiles/")
    profiles = profiles_raw.get("results", profiles_raw) if isinstance(profiles_raw, dict) else profiles_raw
    return [
        {"id": p["id"], "name": p["name"], "enabled": dispatcharr_channel_id in (p.get("channels") or [])}
        for p in profiles
    ]


@router.patch("/channels/{channel_id}/deploy/{connection_id}/profiles/", dependencies=_GUARDS)
async def patch_deploy_profiles(channel_id: int, connection_id: int, body: UpdateChannelProfilesRequest):
    """Update which of the connection's channel profiles this already-
    deployed channel is enabled on -- one PATCH per profile against
    Dispatcharr's own per-profile membership endpoint (no single bulk-by-
    channel call), then persists the resulting set on the deployment record."""
    channel = await _get_channel_or_404(channel_id)
    deployment = next((d for d in channel["deployments"] if d.get("connection_id") == connection_id), None)
    if deployment is None:
        raise HTTPException(status_code=404, detail="not deployed to this connection")

    _connection, client = await _client_for_connection(connection_id)
    dispatcharr_channel_id = deployment["dispatcharr_channel_id"]
    profiles_raw = await client.get("/api/channels/profiles/")
    profiles = profiles_raw.get("results", profiles_raw) if isinstance(profiles_raw, dict) else profiles_raw

    wanted = set(body.channel_profile_ids)
    for p in profiles:
        enabled = p["id"] in wanted
        try:
            await client.patch(f"/api/channels/profiles/{p['id']}/channels/{dispatcharr_channel_id}/", {"enabled": enabled})
        except Exception as exc:
            logger.error("[classic4kast] failed to set profile %s membership for channel %s -> connection %s: %s",
                         p["id"], channel_id, connection_id, exc)
            raise HTTPException(status_code=502, detail=f"Failed updating profile '{p.get('name', p['id'])}': {exc}")

    try:
        return await asyncio.to_thread(db.update_deployment, channel_id, connection_id, {"channel_profile_ids": body.channel_profile_ids})
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/channels/{channel_id}/deploy/{connection_id}/refresh/", dependencies=_GUARDS)
async def post_refresh_deploy_url(channel_id: int, connection_id: int):
    """PATCHes the already-deployed Stream's url to whatever the CURRENT
    public URL + stream key settings would produce -- e.g. after switching
    the public URL from a Tailscale address to a real public domain, or
    rotating the stream key. Deliberately does NOT touch the Channel itself
    (group, channel number, logo, EPG mapping, viewer favorites)."""
    channel = await _get_channel_or_404(channel_id)
    deployment = next((d for d in channel["deployments"] if d.get("connection_id") == connection_id), None)
    if deployment is None:
        raise HTTPException(status_code=404, detail="not deployed to this connection")

    new_url = _stream_url(channel)
    _connection, client = await _client_for_connection(connection_id)
    try:
        await client.patch(f"/api/channels/streams/{deployment['dispatcharr_stream_id']}/", {"url": new_url})
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to update stream url on connection: {exc}")
    return {"ok": True, "url": new_url}


@router.post("/refresh-all/", dependencies=_GUARDS)
async def post_refresh_all_deploy_urls():
    """Fleet-wide version of the single refresh above -- walks EVERY
    deployment of EVERY channel and PATCHes its Stream url to match the
    current public URL + stream key settings. Each deployment is attempted
    independently -- one connection being unreachable never blocks the rest."""
    channels = await asyncio.to_thread(db.list_channels)
    connections_by_id: dict[int, dict] = {}
    results = []
    for channel in channels:
        if not channel["deployments"]:
            continue
        new_url = _stream_url(channel)  # public URL missing -- fail loudly once, nothing downstream can succeed
        for d in channel["deployments"]:
            connection_id = d["connection_id"]
            try:
                if connection_id not in connections_by_id:
                    connections_by_id[connection_id] = await asyncio.to_thread(db.get_dispatcharr_connection, connection_id)
                connection = connections_by_id[connection_id]
                if connection is None:
                    raise RuntimeError("connection no longer exists")
                client = DispatcharrClient(connection["url"], connection["token"])
                await client.patch(f"/api/channels/streams/{d['dispatcharr_stream_id']}/", {"url": new_url})
                results.append({"channel_id": channel["id"], "slug": channel["slug"], "connection_id": connection_id,
                                 "connection_label": d.get("connection_label"), "ok": True})
            except Exception as exc:
                logger.error("[classic4kast] refresh-all failed for channel %s -> connection %s: %s", channel["id"], connection_id, exc)
                results.append({"channel_id": channel["id"], "slug": channel["slug"], "connection_id": connection_id,
                                 "connection_label": d.get("connection_label"), "ok": False, "error": str(exc)})
    return {"results": results}


# ── Agent sync (token-authenticated, not a session login) ───────────────────
# Polled by the renderer -- see renderer/renderer/control_plane_client.py.

@agent_router.get("/channels/")
async def agent_get_channels(x_api_key: str = Header(default="", alias="X-Api-Key")):
    _check_agent_token(x_api_key)
    return await asyncio.to_thread(db.agent_list_active_channels)


@agent_router.get("/settings/")
async def agent_get_settings(x_api_key: str = Header(default="", alias="X-Api-Key")):
    """Polled by the renderer's on-demand reaper -- lets the idle timeout AND
    the public-stream access key change live without a container restart."""
    _check_agent_token(x_api_key)
    return {
        "idle_timeout_seconds": get_idle_timeout_seconds(),
        "stream_key": get_stream_key(),
        "hls_list_size": get_hls_list_size(),
        "hls_time_seconds": get_hls_time_seconds(),
    }


@agent_router.post("/render-result/")
async def agent_post_render_result(body: RenderResult, x_api_key: str = Header(default="", alias="X-Api-Key")):
    _check_agent_token(x_api_key)
    try:
        await asyncio.to_thread(db.agent_report_render_result, body.slug, body.success, body.error)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True}
