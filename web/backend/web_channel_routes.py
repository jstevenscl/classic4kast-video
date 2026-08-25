"""CRUD + agent-sync routes for web_channels (arbitrary-website / Grafana-
dashboard screenshot channels), polled by the separate Node/Puppeteer
webchannel-renderer service -- not the Python weather renderer. Deliberately
a standalone router pair (mirroring routes.py's router/agent_router split)
rather than routes added into routes.py, so the weather-channel routes file
never has to be touched for this feature.

Dispatcharr deploy endpoints below (deploy/deploy-bulk/undeploy/refresh/
profiles) mirror routes.py's weather deploy flow function-for-function --
kept as a separate implementation here (not shared/imported) for the same
reason the module docstring above gives for the CRUD split, but they DO
reuse routes.py's generic (not weather-specific) _client_for_connection
helper and the standalone DispatcharrClient, rather than re-implementing
Dispatcharr API auth from scratch.
"""

import asyncio
import logging
from typing import Optional

import httpx
import websockets
from fastapi import APIRouter, Header, HTTPException, WebSocket, WebSocketDisconnect

import db
import web_channels_db as wdb
from auth import verify_session
from config import get_public_url, get_stream_key, get_webchannel_renderer_url
from dispatcharr_client import DispatcharrClient
from routes import _GUARDS, _check_agent_token, _client_for_connection
from web_channel_models import (
    GrafanaTestRequest, WebChannelBulkDeployRequest, WebChannelCreate, WebChannelDeployRequest,
    WebChannelRenderResult, WebChannelSessionCapture, WebChannelUpdate, WebChannelUpdateChannelProfilesRequest,
)

logger = logging.getLogger(__name__)

web_channel_router = APIRouter(prefix="/api/webchannels", tags=["classic4kast-webchannels"])
web_channel_agent_router = APIRouter(prefix="/api/agent/web-channels", tags=["classic4kast-webchannel-agent"])


# ── CRUD (session-authed, same _GUARDS as routes.py's weather channel CRUD) ─

@web_channel_router.get("/", dependencies=_GUARDS)
async def get_web_channels(enabled_only: bool = False):
    return await asyncio.to_thread(wdb.list_web_channels, enabled_only)


@web_channel_router.post("/", dependencies=_GUARDS)
async def post_web_channel(body: WebChannelCreate):
    try:
        return await asyncio.to_thread(
            wdb.create_web_channel, body.slug, body.channel_name, body.source_type, body.enabled, body.render_mode,
            body.target_url, body.viewport_width, body.viewport_height,
            body.screenshot_interval_ms, body.page_load_wait_ms, body.device_scale_factor, body.dismiss_selector,
            body.grafana_base_url, body.grafana_dashboard_uid, body.grafana_panel_id, body.grafana_api_token,
            body.grafana_org_id, body.grafana_time_from, body.grafana_time_to, body.grafana_extra_query,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@web_channel_router.patch("/{channel_id}/", dependencies=_GUARDS)
async def patch_web_channel(channel_id: int, body: WebChannelUpdate):
    try:
        return await asyncio.to_thread(
            wdb.update_web_channel, channel_id, body.channel_name, body.source_type, body.enabled, body.render_mode,
            body.target_url, body.viewport_width, body.viewport_height,
            body.screenshot_interval_ms, body.page_load_wait_ms, body.device_scale_factor, body.dismiss_selector,
            body.grafana_base_url, body.grafana_dashboard_uid, body.grafana_panel_id, body.grafana_api_token,
            body.grafana_org_id, body.grafana_time_from, body.grafana_time_to, body.grafana_extra_query,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@web_channel_router.delete("/{channel_id}/", dependencies=_GUARDS)
async def remove_web_channel(channel_id: int):
    try:
        await asyncio.to_thread(wdb.delete_web_channel, channel_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True}


@web_channel_router.post("/{channel_id}/render/", dependencies=_GUARDS)
async def post_trigger_web_channel_render(channel_id: int):
    try:
        return await asyncio.to_thread(wdb.trigger_web_channel_render, channel_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@web_channel_router.post("/test-grafana/", dependencies=_GUARDS)
async def post_test_grafana(body: GrafanaTestRequest):
    """Server-side connectivity check for the Grafana form's "Test
    connection" button -- fetches one real render without persisting a
    channel, so a bad URL/token/UID surfaces immediately in the form rather
    than only after saving. Mirrors webchannel-renderer/src/grafana_source.js's
    request shape (same query params, same error-body-on-failure handling)
    since that's the exact code path a real channel runs -- kept as its own
    Python implementation here (session-authed, browser-facing) rather than
    proxied through the Node service (token-authed, not meant to be called
    with arbitrary unsaved form data)."""
    params = {
        "orgId": str(body.grafana_org_id), "panelId": body.grafana_panel_id,
        "width": "800", "height": "450", "from": "now-1h", "to": "now",
    }
    headers = {"Authorization": f"Bearer {body.grafana_api_token}"} if body.grafana_api_token else {}
    url = f"{body.grafana_base_url.rstrip('/')}/render/d-solo/{body.grafana_dashboard_uid}/test"
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            r = await client.get(url, params=params, headers=headers)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"could not reach Grafana: {exc}")
    content_type = r.headers.get("content-type", "")
    if r.status_code != 200 or not content_type.startswith("image/"):
        body_text = r.text[:300] if r.text else "(empty body)"
        raise HTTPException(
            status_code=502,
            detail=f"Grafana render failed (HTTP {r.status_code}, content-type {content_type or 'none'}): {body_text}",
        )
    return {"ok": True, "message": f"Received a valid image ({len(r.content)} bytes)"}


@web_channel_router.get("/status/", dependencies=_GUARDS)
async def get_web_channel_status():
    """Same role as routes.py's GET /api/status/ (proxies the Python
    renderer's own /status), pointed at the Node webchannel-renderer
    instead -- separate route since it's a different upstream, not a
    branch in the existing one."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            r = await client.get(f"{get_webchannel_renderer_url()}/status")
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"webchannel renderer unreachable: {exc}")
    return r.json()


# ── Dispatcharr deploy (mirrors routes.py's deploy flow -- see module
# docstring for why this is a separate implementation, not a shared one) ──

def _web_channel_stream_url(channel: dict) -> str:
    """Mirrors routes.py's _stream_url exactly, pointed at the webchannel
    proxy prefix (main.py's proxy_webchannel route) instead of
    /weatherstar/. webchannel-renderer/src/server.js now validates this
    same key path segment (manager.js's stream-key poll + server.js's
    keyed/unkeyed route matching, added to close C4K-5qh -- a stream key
    set in Settings used to gate weather channels only, not web ones)."""
    public_url = get_public_url()
    if not public_url:
        raise HTTPException(
            status_code=400,
            detail="Set the public URL first (Settings) -- a Dispatcharr connection needs a real "
                   "reachable address for this stream, e.g. a Tailscale address or public domain.",
        )
    stream_key = get_stream_key()
    key_segment = f"/{stream_key}" if stream_key else ""
    return f"{public_url.rstrip('/')}/webchannel/{channel['slug']}{key_segment}/stream.m3u8"


@web_channel_router.get("/{channel_id}/stream-url/", dependencies=_GUARDS)
async def get_web_channel_stream_url(channel_id: int):
    """Lets the frontend show/copy the real stream URL without duplicating
    the public-url/stream-key assembly logic client-side -- same rationale
    as DeployModal's own default-logo-URL construction, just exposed as a
    real endpoint instead since this is useful even with Dispatcharr
    integration off entirely (any HLS-capable player can use this URL
    directly)."""
    channel = await _get_web_channel_or_404(channel_id)
    return {"url": _web_channel_stream_url(channel)}


async def _deploy_web_channel_to_connection(
    client: DispatcharrClient, connection: dict, channel: dict,
    channel_group_id: int, name: str | None, stream_profile_id: int | None,
    logo_url: str | None, channel_profile_ids: list[int] | None = None,
) -> dict:
    stream_url = _web_channel_stream_url(channel)

    group = await client.get(f"/api/channels/groups/{channel_group_id}/")

    existing = await client.get(
        "/api/channels/channels/",
        params={"channel_group": group["name"], "ordering": "-channel_number", "page_size": 1},
    )
    results = existing.get("results", existing) if isinstance(existing, dict) else existing
    next_number = int(results[0]["channel_number"]) + 1 if results else 1

    resolved_name = (name or "").strip() or channel["channel_name"]
    # tvg_id prefixed "web-" (vs weather's plain "classic4kast-{slug}") so a
    # web channel and a weather channel can never collide on tvg_id even if
    # someone reuses the same slug text across both features (slugs are
    # only unique within their own table, not across both).
    channel_payload = {
        "name": resolved_name,
        "channel_group_id": channel_group_id,
        "channel_number": next_number,
        "tvg_id": f"classic4kast-web-{channel['slug']}",
    }
    if stream_profile_id is not None:
        channel_payload["stream_profile_id"] = stream_profile_id
    if channel_profile_ids is not None:
        channel_payload["channel_profile_ids"] = channel_profile_ids

    resolved_logo_url = (logo_url or "").strip() or None
    if resolved_logo_url:
        try:
            logo = await client.post("/api/channels/logos/", {"name": resolved_name, "url": resolved_logo_url})
            channel_payload["logo_id"] = logo["id"]
        except Exception as exc:
            logger.warning("[classic4kast] logo creation skipped for web channel %s -> connection %s (likely duplicate URL): %s",
                            channel["id"], connection["id"], exc)

    stream = await client.post("/api/channels/streams/", {"name": resolved_name, "url": stream_url})
    dispatcharr_channel = await client.post(
        "/api/channels/channels/", {**channel_payload, "streams": [stream["id"]]},
    )

    return await asyncio.to_thread(wdb.add_web_channel_deployment, channel["id"], {
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


async def _get_web_channel_or_404(channel_id: int) -> dict:
    channel = await asyncio.to_thread(wdb.get_web_channel, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail=f"web channel {channel_id} not found")
    return channel


@web_channel_router.post("/{channel_id}/deploy/", dependencies=_GUARDS)
async def post_deploy_web_channel(channel_id: int, body: WebChannelDeployRequest):
    channel = await _get_web_channel_or_404(channel_id)
    if any(d.get("connection_id") == body.connection_id for d in channel["deployments"]):
        raise HTTPException(status_code=400, detail="already deployed to this connection -- remove it first to redeploy")

    connection, client = await _client_for_connection(body.connection_id)

    try:
        return await _deploy_web_channel_to_connection(
            client, connection, channel, body.channel_group_id, body.name,
            body.stream_profile_id, body.logo_url, body.channel_profile_ids,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[classic4kast] web channel deploy failed for channel %s -> connection %s: %s", channel_id, body.connection_id, exc)
        raise HTTPException(status_code=502, detail=f"Deploy failed: {exc}")


@web_channel_router.post("/{channel_id}/deploy-bulk/", dependencies=_GUARDS)
async def post_deploy_web_channel_bulk(channel_id: int, body: WebChannelBulkDeployRequest):
    channel = await _get_web_channel_or_404(channel_id)
    _web_channel_stream_url(channel)  # public URL checked once up front, same error for every connection

    group_name_lower = body.channel_group_name.strip().lower()
    profile_name_lower = (body.stream_profile_name or "").strip().lower() or None

    results = []
    for connection_id in body.connection_ids:
        current = await asyncio.to_thread(wdb.get_web_channel, channel_id)
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

            deployment = await _deploy_web_channel_to_connection(
                client, connection, channel, group["id"], body.name, stream_profile_id, body.logo_url,
                channel_profile_ids,
            )
            results.append({"connection_id": connection_id, "connection_label": connection["label"], "ok": True, "deployment": deployment})
        except Exception as exc:
            logger.error("[classic4kast] bulk web channel deploy failed for channel %s -> connection %s: %s", channel_id, connection_id, exc)
            results.append({"connection_id": connection_id, "connection_label": connection.get("label"), "ok": False, "error": str(exc)})

    return {"results": results}


@web_channel_router.delete("/{channel_id}/deploy/{connection_id}/", dependencies=_GUARDS)
async def delete_deploy_web_channel(channel_id: int, connection_id: int):
    channel = await _get_web_channel_or_404(channel_id)
    deployment = next((d for d in channel["deployments"] if d.get("connection_id") == connection_id), None)
    if deployment is None:
        raise HTTPException(status_code=404, detail="not deployed to this connection")

    connection, client = await _client_for_connection(connection_id)
    try:
        await client.delete(f"/api/channels/channels/{deployment['dispatcharr_channel_id']}/")
    except Exception as exc:
        logger.error("[classic4kast] failed to delete web channel %s on connection %s: %s", deployment["dispatcharr_channel_id"], connection_id, exc)
    try:
        await client.delete(f"/api/channels/streams/{deployment['dispatcharr_stream_id']}/")
    except Exception as exc:
        logger.error("[classic4kast] failed to delete stream %s on connection %s: %s", deployment["dispatcharr_stream_id"], connection_id, exc)

    return await asyncio.to_thread(wdb.remove_web_channel_deployment, channel_id, connection_id)


@web_channel_router.get("/{channel_id}/deploy/{connection_id}/profiles/", dependencies=_GUARDS)
async def get_web_channel_deploy_profiles(channel_id: int, connection_id: int):
    channel = await _get_web_channel_or_404(channel_id)
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


@web_channel_router.patch("/{channel_id}/deploy/{connection_id}/profiles/", dependencies=_GUARDS)
async def patch_web_channel_deploy_profiles(channel_id: int, connection_id: int, body: WebChannelUpdateChannelProfilesRequest):
    channel = await _get_web_channel_or_404(channel_id)
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
            logger.error("[classic4kast] failed to set profile %s membership for web channel %s -> connection %s: %s",
                         p["id"], channel_id, connection_id, exc)
            raise HTTPException(status_code=502, detail=f"Failed updating profile '{p.get('name', p['id'])}': {exc}")

    try:
        return await asyncio.to_thread(wdb.update_web_channel_deployment, channel_id, connection_id, {"channel_profile_ids": body.channel_profile_ids})
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@web_channel_router.post("/{channel_id}/deploy/{connection_id}/refresh/", dependencies=_GUARDS)
async def post_refresh_web_channel_deploy_url(channel_id: int, connection_id: int):
    channel = await _get_web_channel_or_404(channel_id)
    deployment = next((d for d in channel["deployments"] if d.get("connection_id") == connection_id), None)
    if deployment is None:
        raise HTTPException(status_code=404, detail="not deployed to this connection")

    new_url = _web_channel_stream_url(channel)
    _connection, client = await _client_for_connection(connection_id)
    try:
        await client.patch(f"/api/channels/streams/{deployment['dispatcharr_stream_id']}/", {"url": new_url})
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to update stream url on connection: {exc}")
    return {"ok": True, "url": new_url}


# ── Interactive login-session capture ────────────────────────────────────────
# Lets an admin watch a live view of a login-gated page (see
# webchannel-renderer/src/login_session.js) and log in themselves --
# including anything a scripted credential/form-fill could never get
# through, like UniFi's own MFA-gated cloud SSO -- then captures the
# resulting cookies/localStorage for the regular capture loop to reuse.

@web_channel_router.post("/{channel_id}/session/", dependencies=_GUARDS)
async def post_web_channel_session(channel_id: int, body: WebChannelSessionCapture):
    try:
        return await asyncio.to_thread(
            wdb.set_web_channel_session_state, channel_id,
            {"cookies": body.cookies, "localStorage": body.local_storage},
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@web_channel_router.delete("/{channel_id}/session/", dependencies=_GUARDS)
async def delete_web_channel_session(channel_id: int):
    try:
        return await asyncio.to_thread(wdb.set_web_channel_session_state, channel_id, None)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@web_channel_router.websocket("/{channel_id}/login-session/ws")
async def websocket_web_channel_login_session(websocket: WebSocket, channel_id: int):
    """Bridges the browser to webchannel-renderer's own login-session
    WebSocket route (server.js) -- pure message relay both directions, no
    persistence-sensitive data handled here at all (the frontend POSTs the
    captured session to post_web_channel_session above, over the normal
    authed REST path, once the Node side hands it back over this tunnel).

    A browser WebSocket can't set custom headers, so the session token
    travels as a query param instead of the usual X-Session-Token header --
    auth.verify_session() takes a plain token string either way, no change
    needed there. webchannel-renderer itself is only reachable from inside
    the compose network and does no auth of its own on this route -- this
    check is the only gate, same trust boundary the HLS proxy routes above
    already rely on (only `web` publishes a port)."""
    token = websocket.query_params.get("token")
    if not token or not verify_session(token):
        await websocket.close(code=4401)
        return

    channel = await asyncio.to_thread(wdb.get_web_channel, channel_id)
    if channel is None:
        await websocket.close(code=4404)
        return

    upstream_url = f"{get_webchannel_renderer_url().replace('http://', 'ws://').replace('https://', 'wss://')}/webchannel/{channel['slug']}/login-session"
    await websocket.accept()
    try:
        async with websockets.connect(upstream_url, open_timeout=10) as upstream:
            async def browser_to_upstream():
                while True:
                    msg = await websocket.receive_text()
                    await upstream.send(msg)

            async def upstream_to_browser():
                async for msg in upstream:
                    await websocket.send_text(msg)

            pumps = [asyncio.create_task(browser_to_upstream()), asyncio.create_task(upstream_to_browser())]
            try:
                await asyncio.wait(pumps, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for p in pumps:
                    p.cancel()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error("[classic4kast] login-session bridge error for web channel %s: %s", channel_id, exc)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ── Agent sync (token-authenticated, not a session login) ───────────────────
# Polled by webchannel-renderer/src/control_plane_client.js -- the same
# 3-endpoint shape as routes.py's weather agent_router, reimplemented against
# web_channels rather than sharing the weather endpoints (see this file's
# module docstring for why).

@web_channel_agent_router.get("/")
async def agent_get_web_channels(x_api_key: str = Header(default="", alias="X-Api-Key")):
    _check_agent_token(x_api_key)
    return await asyncio.to_thread(wdb.agent_list_active_web_channels)


@web_channel_agent_router.post("/render-result/")
async def agent_post_web_channel_render_result(body: WebChannelRenderResult, x_api_key: str = Header(default="", alias="X-Api-Key")):
    _check_agent_token(x_api_key)
    try:
        await asyncio.to_thread(wdb.agent_report_web_render_result, body.slug, body.success, body.error)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True}
