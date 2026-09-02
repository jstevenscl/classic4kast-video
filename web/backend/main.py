"""Classic4Kast Video+ web backend -- FastAPI app scaffolding. Ported from VOD & DVR
Manager's main.py: logging setup with credential-redaction filters, static
SPA serving, SPA catch-all. Deliberately far lighter on the lifespan side --
this product has no background import/sync loops to run; init_db() at
startup is the only real lifespan work, so lifespan is a minimal
asynccontextmanager rather than VOD Manager's dozen background task loops.
"""
import logging
import re
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

import db
from config import APP_VERSION, LOG_BACKUP_COUNT, LOG_FILE, get_renderer_url, get_webchannel_renderer_url
from m3u_routes import router as m3u_router
from routes import agent_router, router
from web_channel_routes import web_channel_agent_router, web_channel_router

_LOG_FORMAT = "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"
logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT)

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
_file_handler = RotatingFileHandler(LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=LOG_BACKUP_COUNT, encoding="utf-8")
_file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
logging.getLogger().addHandler(_file_handler)
# uvicorn configures "uvicorn.access"/"uvicorn.error" with propagate=False and
# their own stdout/stderr handlers *before* this module is imported -- adding
# the file handler to the root logger alone would silently miss both, so it
# has to be attached to them directly too.
logging.getLogger("uvicorn.access").addHandler(_file_handler)
logging.getLogger("uvicorn.error").addHandler(_file_handler)

_TOKEN_QS_RE = re.compile(r"((?:token|key|api_key|password)=)[^&\s\"]*", re.IGNORECASE)


class _RedactCredentialsFilter(logging.Filter):
    """Query-string credentials (Dispatcharr tokens/API keys, the stream
    access key) must never land in plaintext in stdout/container logs on
    every request -- same reasoning as VOD & DVR Manager's main.py redaction
    filters, generalized here to a single query-param-name pattern since
    this product doesn't have VOD Manager's XC-protocol path-segment
    credentials."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            record.args = tuple(
                _TOKEN_QS_RE.sub(r"\1***", arg) if isinstance(arg, str) else arg
                for arg in record.args
            )
        return True


logging.getLogger("uvicorn.access").addFilter(_RedactCredentialsFilter())
logging.getLogger("httpx").addFilter(_RedactCredentialsFilter())

logger     = logging.getLogger("classic4kast")
STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    logger.info("Classic4Kast Video+ web backend started (version %s)", APP_VERSION)
    yield


app = FastAPI(title="Classic4Kast Video+", version=APP_VERSION, lifespan=lifespan)
app.include_router(router)
app.include_router(agent_router)
app.include_router(web_channel_router)
app.include_router(web_channel_agent_router)
app.include_router(m3u_router)


@app.get("/weatherstar/{full_path:path}", include_in_schema=False)
async def proxy_weatherstar(full_path: str, request: Request):
    """Reverse-proxy for the renderer's own HLS output (manifests, .ts
    segments, the default logo) -- an admin's browser generally can't reach
    the renderer container's own port directly (loopback-only in a typical
    deploy, or just a different host entirely in a split deployment), so
    every same-origin /weatherstar/... URL this app hands out (preview
    player, deployed Dispatcharr Stream URLs before "Redirect" takes over)
    has to actually be served from here. Deliberately NOT behind the
    session-auth guard other /api/ routes use: hls.js and a plain <video>
    tag fetch segments directly, with no X-Session-Token attached (that
    header is only ever injected by this app's own axios instance) -- access
    control for real public exposure is the separate stream-key mechanism
    the renderer itself already enforces on this same path.

    -- found live 2026-09-02: also needs Access-Control-Allow-Origin. A
    non-browser player (VLC, a TV app) doesn't care, but any *browser-based*
    HLS player fetching this cross-origin (Dispatcharr's own admin preview,
    a web IPTV client, hls.js anywhere but this app's own SPA origin) got
    silently blocked by CORS with no useful error -- Dispatcharr's preview
    modal just looped "Connection lost, reconnecting" while its own
    server-side validation logged the manifest as perfectly valid. Same
    open-by-default reasoning as the auth note above: this content has no
    stronger protection than the stream key regardless of origin, so there's
    nothing CORS was actually guarding here.
    """
    upstream = f"{get_renderer_url()}/weatherstar/{full_path}"
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            r = await client.get(upstream, params=request.query_params)
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"renderer unreachable: {exc}")
    excluded = {"content-encoding", "content-length", "transfer-encoding", "connection"}
    headers = {k: v for k, v in r.headers.items() if k.lower() not in excluded}
    headers["Access-Control-Allow-Origin"] = "*"
    return Response(content=r.content, status_code=r.status_code, headers=headers)


@app.get("/webchannel/{full_path:path}", include_in_schema=False)
async def proxy_webchannel(full_path: str, request: Request):
    """Reverse-proxy for the webchannel-renderer's own HLS output -- straight
    copy of proxy_weatherstar above with a different upstream, kept as a
    separate route/function (not a shared helper) so neither proxy handler
    ever needs a slug-lookup branch to decide which renderer to hit."""
    upstream = f"{get_webchannel_renderer_url()}/webchannel/{full_path}"
    # Longer than the weather proxy's timeout=15 above -- a fire_on_start web
    # channel's cold start (Chromium launch + page navigate + first
    # screenshot + first HLS segment) can legitimately take close to the
    # webchannel-renderer's own FILE_WAIT_TIMEOUT_SECONDS=20 window, and this
    # proxy must outlast that rather than 502ing a cold start that was
    # actually about to succeed.
    async with httpx.AsyncClient(timeout=25) as client:
        try:
            r = await client.get(upstream, params=request.query_params)
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"webchannel renderer unreachable: {exc}")
    excluded = {"content-encoding", "content-length", "transfer-encoding", "connection"}
    headers = {k: v for k, v in r.headers.items() if k.lower() not in excluded}
    headers["Access-Control-Allow-Origin"] = "*"  # see proxy_weatherstar's docstring
    return Response(content=r.content, status_code=r.status_code, headers=headers)


if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        # A path under /api/ that didn't match any registered route is a
        # real 404, not a client-side route -- letting it fall through to
        # the index.html fallback below would silently return 200 HTML to
        # a caller expecting JSON (bit the renderer during integration: a
        # stale agent-endpoint path returned 200 index.html, which then
        # failed JSON parsing far from the actual mismatch).
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="not found")
        # Anything Vite copied from frontend/public/ to the dist root (e.g.
        # favicon.svg) lands directly under STATIC_DIR, not under /assets --
        # without this check it fell through to the SPA fallback below and
        # got served as index.html (wrong content-type, wrong bytes). Real
        # client-side routes (e.g. /settings) don't correspond to a file, so
        # they still correctly fall through to the index.html fallback.
        if full_path:
            candidate = (STATIC_DIR / full_path).resolve()
            if candidate.is_file() and candidate.is_relative_to(STATIC_DIR.resolve()):
                return FileResponse(str(candidate))
        return FileResponse(str(STATIC_DIR / "index.html"))
