"""M3U playlist export -- a standalone alternative to Dispatcharr deploy for
users who just want a plain IPTV-style playlist (VLC, Threadfin, Jellyfin,
a smart TV app) instead of pushing channels into Dispatcharr.

Deliberately reuses the exact same public-URL/stream-key plumbing routes.py's
_stream_url() and web_channel_routes.py's _web_channel_stream_url() already
use for Dispatcharr's "Redirect" stream profile -- that address was always
meant to be reachable by whatever actually plays the stream, not just
Dispatcharr itself, so there's no separate "M3U base URL" setting here. A
user with Dispatcharr's Redirect profile already working has already proven
their Public URL is player-reachable.

A standalone module (not folded into routes.py) so it can import from both
routes.py and web_channel_routes.py without a circular import -- mirrors the
same "standalone router" reasoning web_channel_routes.py's own docstring
gives for its own split from routes.py.

-- found live 2026-09-02: this route must NOT sit behind the session-auth
_GUARDS the rest of /api/ uses. Dispatcharr (or Threadfin/Jellyfin) fetches
an M3U *source* URL on its own polling schedule, server-side, with no way to
attach the browser's X-Session-Token header -- adding it as a Dispatcharr
M3U source 401'd immediately. Same reasoning as main.py's proxy_weatherstar
route: access control for a non-interactive client has to be the stream key
baked into the URL itself, not the interactive session login. The
export page (which lists channel names/slugs) still lives behind the SPA's
own login gate same as before -- only the raw playlist URL is exempted here.
"""
import asyncio

from fastapi import APIRouter, HTTPException, Response

import db
import web_channels_db as wdb
from config import get_stream_key
from routes import _stream_url
from web_channel_routes import _web_channel_stream_url

router = APIRouter(prefix="/api/m3u", tags=["classic4kast-m3u"])


@router.get("/")
async def export_m3u(weather_slugs: str = "", web_slugs: str = "", key: str = ""):
    """weather_slugs/web_slugs are comma-separated channel slugs from their
    respective tables -- kept as two params (not one merged list) since a
    slug is only unique within its own table, not across both. `key` must
    match the configured stream key exactly when one is set (empty key =
    endpoint is unauthenticated, same default-open behavior the stream key
    itself already has elsewhere)."""
    configured_key = get_stream_key()
    if configured_key and key != configured_key:
        raise HTTPException(status_code=401, detail="invalid or missing stream key")

    weather_wanted = [s for s in weather_slugs.split(",") if s]
    web_wanted = [s for s in web_slugs.split(",") if s]

    lines = ["#EXTM3U"]

    if weather_wanted:
        by_slug = {c["slug"]: c for c in await asyncio.to_thread(db.list_channels)}
        for slug in weather_wanted:
            channel = by_slug.get(slug)
            if channel is None:
                continue
            lines.append(f'#EXTINF:-1 tvg-id="classic4kast-{slug}",{channel["city_name"]}')
            lines.append(_stream_url(channel))

    if web_wanted:
        by_slug = {c["slug"]: c for c in await asyncio.to_thread(wdb.list_web_channels)}
        for slug in web_wanted:
            channel = by_slug.get(slug)
            if channel is None:
                continue
            lines.append(f'#EXTINF:-1 tvg-id="classic4kast-{slug}",{channel["channel_name"]}')
            lines.append(_web_channel_stream_url(channel))

    content = "\n".join(lines) + "\n"
    return Response(
        content=content,
        media_type="audio/x-mpegurl",
        headers={
            "Content-Disposition": 'attachment; filename="classic4kast.m3u8"',
            # Same reasoning as main.py's proxy_weatherstar CORS note -- a
            # browser-based tool validating this URL (not just a server-side
            # poller) shouldn't get silently CORS-blocked.
            "Access-Control-Allow-Origin": "*",
        },
    )
