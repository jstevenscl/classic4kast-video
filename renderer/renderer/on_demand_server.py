"""
Fire-on-demand HTTP server: replaces both nginx (static HLS serving) and
live_main.py's always-on multi-city poller. This is what makes fleet CPU
cost scale with concurrent VIEWERS instead of configured CHANNELS (see
weatherstar-native-demo.mp4 / CURRENT.md for the always-on cost that made
this necessary) -- render_mode below decides how far that tradeoff goes
per channel.

Per-channel WeatherStarChannel.render_mode (set on the Channels tab, see
weatherstar_service.RENDER_MODES) -- three deliberately distinct tradeoffs,
not fleet-wide, so a mixed fleet isn't forced to pick one answer for every
city:

  "on_demand" (default): the loading loop is a PERSISTENT baseline, not
    just a cold-start filler -- _prewarm() starts it for every such
    channel at container boot (and picks up newly-added/retoggled
    channels on its own poll cycle), and the reaper re-arms it after
    every idle-stop instead of leaving the channel dark. A viewer's very
    first request for such a channel -- even one nobody has ever
    watched -- resolves instantly to a real, playable stream (the stale
    "WEATHER LOADING" frame), never a 404/503 gap. Costs ~5% CPU at rest
    per channel (see loading_stream.py's -re fix).

  "fire_on_start": true zero CPU at rest -- nothing runs for this channel,
    not even the loading loop, until its very first request ever (or its
    first request after an idle-stop). That request reactively starts the
    loading loop AND the real render task together (same _get_or_start
    path as on_demand's cold start), so there's still a brief "WEATHER
    LOADING" gap before real content swaps in -- the difference from
    on_demand is only what happens at rest: _prewarm skips these channels
    entirely, and the reaper does NOT re-arm loading after idle-stop, so
    CPU drops back to genuinely zero rather than the ~5% baseline.

  "always_on": the real render pipeline starts at boot/config-poll and is
    never idle-stopped -- zero cold-start delay ever, at that city's full
    steady-state cost (~30-40% CPU) regardless of viewership.

Sequence for a slug on a real request (see _get_or_start):
  1. If render_mode is on_demand, loading is already running (pre-warmed
     at boot, or re-armed by the reaper after the last idle-stop) -- the
     request is served immediately. fire_on_start channels have nothing
     running yet at this point; _ensure_loading starts it reactively here.
  2. If no live_stream.run() task is active yet, kick one off in the
     background. Its on_ready callback (invoked right after the first real
     data fetch, immediately before it starts its own ffmpeg) stops the
     loading loop first, THEN lets the real ffmpeg take over the same path
     -- strictly sequential, never concurrent writers to the same output.
  3. The request handler still polls briefly for the requested file to
     exist as a safety net (covers the loading-loop's own brief startup
     gap).

Idle timeout is fetched live from the control plane's Settings page
(weatherstar_idle_timeout_seconds) so it's a real admin-configurable
setting, not a hardcoded env var -- falls back to
IDLE_TIMEOUT_FALLBACK_SECONDS (env var, default 600s) when the control
plane isn't configured/reachable, matching every other control_plane_client
fallback in this repo.
"""
import asyncio
import logging
import os
import time

from aiohttp import web

# Must configure logging before importing live_main -- its own module-level
# basicConfig() call would otherwise win (logging.basicConfig is a no-op
# after the first call in a process) and every line here would be mislabeled
# "[live-main]".
logging.basicConfig(level=logging.INFO, format='[on-demand %(asctime)s] %(message)s')
log = logging.getLogger(__name__)

# basicConfig sets the ROOT logger, and every other logger propagates to it
# by default -- httpx logs one INFO line per outbound request (NWS/radar/SPC/
# control-plane API calls, dozens per data-refresh cycle) and httpcore logs its own
# connection-level detail underneath that. Neither is useful at steady state;
# push both down to WARNING so `docker logs` shows our own renderer/reaper
# events instead of being buried in per-request noise. (aiohttp's default
# per-HTTP-request access log is silenced separately -- see main()'s
# access_log=None.)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
# aiohttp's own access log -- one line per HTTP request to this server (every
# .m3u8/.ts segment fetch, so several per second per active viewer). Same
# reasoning as httpx above.
logging.getLogger('aiohttp.access').setLevel(logging.WARNING)

from renderer import control_plane_client, loading_stream  # noqa: E402
from renderer.live_stream import run as run_live_stream  # noqa: E402
from renderer.live_main import STATIC_CITY  # noqa: E402

DATA_ROOT = os.environ.get('DATA_ROOT', '/data')
LISTEN_PORT = int(os.environ.get('LISTEN_PORT', '8090'))
REAPER_INTERVAL_SECONDS = 30
# How often _prewarm re-polls the channel list to pick up newly
# added channels -- matches live_main.py's own CONFIG_POLL_SECONDS default,
# not latency-sensitive (a brand new channel just waits one extra cycle
# before its loading loop is pre-started; requesting it directly still
# works immediately via _get_or_start's own fallback).
PREWARM_POLL_SECONDS = int(os.environ.get('CONFIG_POLL_SECONDS', '30'))
# How long the request handler waits for a cold-started stream to produce the
# requested file before giving up and 503ing -- generous, but this is the
# viewer's one-time cold-start hit, not a steady-state cost.
FILE_WAIT_TIMEOUT_SECONDS = 20


class _CityState:
	def __init__(self):
		self.task = None  # asyncio.Task running live_stream.run (restart-wrapped)
		self.loading_proc = None
		self.loading_png = None
		self.last_access = 0.0
		# Guards the check-then-create-task section in _get_or_start -- found
		# live 2026-08-22: two nearly-simultaneous requests for the same
		# never-yet-started slug (a player retrying its own initial
		# connection attempt, not an edge case) could BOTH observe
		# `state.task is None` before either one had actually set it, since
		# the `await _lookup_city(slug)` in between yields control back to
		# the event loop. Both then created their own _run_city_forever
		# task -- two independent ffmpeg encoders writing the SAME
		# stream.m3u8/segments concurrently, visible to the viewer as
		# constant glitching/clock skip (two different encoders' frames
		# interleaving in the same output). Not related to either of the
		# same day's other WeatherStar fixes (the audio-decode-desync
		# watchdog, the frame-write pacing decouple) -- this is a genuinely
		# separate bug, and the only one of the three that actually explains
		# a fresh cold-started channel glitching immediately.
		self.lock = asyncio.Lock()
		# Edge-detects the control plane's force_render flag (set by the
		# admin UI's "Re-render now" button) so _prewarm only acts on it
		# once per press, not on every poll while the flag is still True
		# waiting for a fresh render to report back and clear it.
		self.force_render_seen = False


_states = {}  # slug -> _CityState

# None = not yet fetched successfully (briefly open at process startup,
# until the first poll below completes); '' = the control plane deliberately
# has no key configured (not gated); non-empty = required ?key= value. Only
# updated on a SUCCESSFUL poll -- a transient control-plane outage holds the
# last known-good value rather than failing open, since (once WeatherStar's
# public URL is a real public domain, not a Tailscale-private address) this
# is the only thing standing between the internet and a free stream of a
# guessable-slug channel. See control_plane_client.fetch_stream_key's own
# docstring.
_stream_key_cache = {'value': None}


async def _poll_stream_key():
	while True:
		key = await control_plane_client.fetch_stream_key()
		if key is not None:
			_stream_key_cache['value'] = key
		await asyncio.sleep(PREWARM_POLL_SECONDS)


async def _all_known_cities():
	if control_plane_client.is_configured():
		channels = await control_plane_client.fetch_active_channels()
		return [control_plane_client.channel_to_city(c, DATA_ROOT) for c in channels]
	return [STATIC_CITY]


async def _lookup_city(slug):
	for city in await _all_known_cities():
		if city['slug'] == slug:
			return city
	return None


def _ensure_loading(slug, city, state):
	"""Idempotent -- safe to call whether or not a loading loop is already
	running for this slug (prewarm, idle re-arm, and crash-restart all funnel
	through this instead of duplicating the None-check)."""
	if state.loading_proc is not None:
		return
	hls_dir = f"{DATA_ROOT}/{city['slug']}/hls"
	proc, png_path = loading_stream.start(hls_dir, city.get('name'))
	state.loading_proc, state.loading_png = proc, png_path
	log.info(f'{slug}: loading loop (re)started')


async def _prewarm():
	"""Applies each channel's render_mode as its resting state (see this
	module's own docstring for the three modes) -- on_demand gets the cheap
	loading-loop baseline, always_on gets the real pipeline, fire_on_start
	gets nothing at all (true zero CPU until its first request, handled
	reactively by _get_or_start). Runs once at startup, then re-polls to
	catch channels added -- or retoggled -- after this process started."""
	while True:
		try:
			for city in await _all_known_cities():
				state = _states.setdefault(city['slug'], _CityState())
				# Same lock _get_or_start uses -- without it, this poll and a
				# real viewer's cold-start request racing each other for the
				# same never-yet-started slug could both pass the
				# `state.task is None` check (this loop's own await above,
				# over all cities, is enough of a yield point for that other
				# coroutine to interleave in).
				async with state.lock:
					# force_render ("Re-render now" in the admin UI) restarts an
					# ALREADY-live channel fresh -- re-fetches data and starts a new
					# ffmpeg (picking up any config change, e.g. hls_list_size, that
					# only takes effect on a fresh start) -- rather than just falling
					# through to the loading-screen baseline below, which would drop
					# whoever's currently watching back to "loading" and wait for a
					# real request to restart it. A channel that ISN'T currently live
					# has nothing to force -- its next real view already fetches fresh
					# data, so force_render is a no-op there.
					if city.get('force_render'):
						if not state.force_render_seen:
							state.force_render_seen = True
							if state.task is not None and not state.task.done():
								log.info(f"{city['slug']}: force-render requested -- restarting live render")
								state.task.cancel()
								try:
									await state.task
								except BaseException:  # noqa: BLE001 -- cancellation itself, or any error mid-teardown; either way we're about to start fresh
									pass
								state.last_access = time.time()
								state.task = asyncio.create_task(_run_city_forever(city, state))
					else:
						state.force_render_seen = False

					if state.task is not None and not state.task.done():
						continue
					mode = city.get('render_mode', 'on_demand')
					if mode == 'always_on':
						log.info(f"{city['slug']}: always_on -- starting real render pipeline at boot/poll")
						# always_on never goes through _get_or_start (the
						# normal place last_access gets touched), so it stays
						# at its 0.0 default -- harmless while always_on (the
						# reaper skips the idle check for this mode
						# entirely), but if later switched to
						# on_demand/fire_on_start the very next reaper cycle
						# would log a nonsensical "idle for <unix-epoch-sized
						# number>s" before correctly stopping it. Keep it
						# current so that log line stays sane.
						state.last_access = time.time()
						state.task = asyncio.create_task(_run_city_forever(city, state))
					elif mode == 'fire_on_start':
						pass  # true zero CPU at rest -- nothing until the first real request
					else:
						_ensure_loading(city['slug'], city, state)
		except Exception as exc:  # noqa: BLE001 -- one bad poll must not stop prewarming everything else already running
			log.error(f'prewarm ERROR: {type(exc).__name__}: {exc}')
		await asyncio.sleep(PREWARM_POLL_SECONDS)


async def _run_city_forever(city, state):
	"""Same restart-on-crash wrapper as live_main.py's _run_city_forever, but
	also re-arms the loading screen on each restart -- a mid-stream crash
	should show "loading" again during the brief data-refetch, not serve
	stale/broken segments."""
	while True:
		async def on_ready():
			if state.loading_proc is not None:
				# Thread offload + hard timeout -- same reasoning as
				# live_stream.py's _stop_ffmpeg call sites (see that file's
				# 2026-08-22 comment): this whole renderer is one shared
				# process/event loop across every city, so a blocking
				# terminate()/wait() that ever took longer than expected
				# would stall every OTHER city's frame loop for that long
				# too, not just this one's handoff. Lower risk here than
				# live_stream's case (loading_stream's ffmpeg is a simple
				# self-contained process, no piped stdin/writer-thread
				# race) but the failure mode if it ever did hang would be
				# just as bad, so worth the same defense.
				try:
					await asyncio.wait_for(
						asyncio.to_thread(loading_stream.stop, state.loading_proc, state.loading_png), timeout=10,
					)
				except asyncio.TimeoutError:
					log.error(f"{city['slug']}: loading_stream.stop didn't finish within 10s -- abandoning it")
				state.loading_proc = None
			# Fire-and-forget: report_render_result was defined in the
			# EDM-era client but never actually called anywhere, so Fleet
			# Status never reflected a real render outcome. A reporting
			# failure here must not take down the stream itself -- same
			# is_configured()-guarded, try/except-wrapped pattern as this
			# module's other control-plane calls.
			if control_plane_client.is_configured():
				try:
					await control_plane_client.report_render_result(city['slug'], True)
				except Exception as exc:  # noqa: BLE001
					log.error(f"{city['slug']}: failed to report render success: {type(exc).__name__}: {exc}")
		try:
			await run_live_stream(city, on_ready=on_ready)
		except Exception as exc:  # noqa: BLE001
			log.error(f"{city['slug']}: live_stream.run crashed, restarting in 10s: {type(exc).__name__}: {exc}")
			_ensure_loading(city['slug'], city, state)
			if control_plane_client.is_configured():
				try:
					await control_plane_client.report_render_result(city['slug'], False, str(exc))
				except Exception as report_exc:  # noqa: BLE001
					log.error(f"{city['slug']}: failed to report render failure: {type(report_exc).__name__}: {report_exc}")
			await asyncio.sleep(10)


async def _get_or_start(slug):
	state = _states.setdefault(slug, _CityState())
	state.last_access = time.time()
	if state.task is not None and not state.task.done():
		return state, None

	# Whole check-then-create section under the lock, not just the create --
	# the check above is a fast-path only (avoids acquiring the lock on
	# every request once a stream is already running); the real guard
	# against two concurrent cold-starts is re-checking state.task again
	# once inside. See _CityState.lock's comment for what this fixes.
	async with state.lock:
		if state.task is not None and not state.task.done():
			return state, None

		city = await _lookup_city(slug)
		if city is None:
			return state, web.Response(status=404, text=f'unknown weatherstar channel: {slug}')

		log.info(f"{slug}: cold start (first request since idle-stop or process start)")
		# Normally already running (prewarmed at boot / re-armed on
		# idle-stop) -- this only actually starts anything the first time a
		# channel is ever requested before the prewarm loop has gotten to
		# it.
		_ensure_loading(slug, city, state)
		state.task = asyncio.create_task(_run_city_forever(city, state))
		return state, None


async def _wait_for_file(path):
	deadline = time.time() + FILE_WAIT_TIMEOUT_SECONDS
	while time.time() < deadline:
		if os.path.exists(path):
			return True
		await asyncio.sleep(0.2)
	return False


async def _serve_hls_file(slug, filename):
	state, err = await _get_or_start(slug)
	if err is not None:
		return err

	path = f'{DATA_ROOT}/{slug}/hls/{filename}'
	if not await _wait_for_file(path):
		return web.Response(status=503, text='stream still starting, try again shortly')

	content_type = 'application/vnd.apple.mpegurl' if filename.endswith('.m3u8') else 'video/mp2t'
	resp = web.FileResponse(path)
	resp.content_type = content_type
	resp.headers['Cache-Control'] = 'no-cache'
	return resp


async def handle_hls_file(request):
	"""Unkeyed route -- only reachable at all if no stream key is currently
	configured (see main()'s route registration comment for why this route
	and the keyed one below can coexist safely)."""
	if _stream_key_cache['value']:
		return web.Response(status=403, text='invalid or missing key')
	return await _serve_hls_file(request.match_info['slug'], request.match_info['filename'])


async def handle_hls_file_keyed(request):
	"""Keyed route -- .../{slug}/{key}/{filename}. The key is a PATH
	segment, not a ?key= query param, specifically so it survives plain
	relative-URL resolution from the manifest to each .ts segment a player
	derives from it (a query string on the manifest URL is not guaranteed
	to carry over the same way -- see backend/app/api/v1/weatherstar.py's
	_deploy_to_instance comment for the full reasoning)."""
	required_key = _stream_key_cache['value']
	if not required_key or request.match_info['key'] != required_key:
		return web.Response(status=403, text='invalid or missing key')
	return await _serve_hls_file(request.match_info['slug'], request.match_info['filename'])


async def _reaper():
	"""Stops idle channels' live render pipelines so fleet CPU cost tracks
	concurrent viewers, not configured channels -- then immediately re-arms
	the loading loop (cheap, ~4% CPU with the -re fix) so the channel drops
	back to its normal persistent-baseline state instead of going dark.
	Re-fetches the idle timeout every cycle (not once at startup) so a
	change on the Settings page takes effect without a container restart."""
	while True:
		await asyncio.sleep(REAPER_INTERVAL_SECONDS)
		try:
			idle_timeout = await control_plane_client.fetch_idle_timeout_seconds()
			now = time.time()
			for slug, state in list(_states.items()):
				if state.task is None or state.task.done():
					continue
				city = await _lookup_city(slug)
				if city is None:
					continue  # channel deleted/disabled since it started -- leave whatever's running alone
				mode = city.get('render_mode', 'on_demand')
				if mode == 'always_on':
					continue  # never idle-stop -- this channel's whole point is zero cold-start delay
				if now - state.last_access > idle_timeout:
					log.info(f'{slug}: idle for {int(now - state.last_access)}s (limit {idle_timeout}s), stopping')
					task = state.task
					task.cancel()
					# Must wait for the real ffmpeg's own cancellation
					# cleanup (live_stream.run's finally block) to actually
					# finish before starting a new writer against the same
					# HLS path -- cancel() only schedules the CancelledError,
					# it doesn't block until torn down. Skipping this wait
					# risked two ffmpeg processes writing stream.m3u8
					# concurrently for the few seconds cleanup can take.
					try:
						await task
					except asyncio.CancelledError:
						pass
					state.task = None
					if mode == 'fire_on_start':
						continue  # true zero CPU at rest -- do NOT re-arm the loading loop
					_ensure_loading(slug, city, state)
		except Exception as exc:  # noqa: BLE001 -- one bad reaper pass must not kill every running stream
			log.error(f'reaper ERROR: {type(exc).__name__}: {exc}')


_LOGO_PATH = os.path.join(os.path.dirname(__file__), 'assets', 'static', 'logo.png')


async def handle_logo(request):
	return web.FileResponse(_LOGO_PATH, headers={'Cache-Control': 'public, max-age=86400'})


async def handle_status(request):
	"""Internal-only (no route through nginx's /weatherstar/ prefix reaches
	this -- only the control plane calls it, over the docker-internal network,
	same trust model as vod-xc's own unauthenticated /activity/ endpoint) --
	lets the control plane's admin UI show which channels currently have a
	real viewer, something Dispatcharr itself can never see for a
	"Redirect"-profile deploy (the player is sent straight here,
	Dispatcharr's own proxy never sees the connection at all)."""
	idle_timeout = await control_plane_client.fetch_idle_timeout_seconds()
	now = time.time()
	out = []
	for city in await _all_known_cities():
		slug = city['slug']
		state = _states.get(slug)
		mode = city.get('render_mode', 'on_demand')
		live = bool(state and state.task is not None and not state.task.done())
		loading = bool(state and state.loading_proc is not None)
		last_access = state.last_access if state and state.last_access else None
		idle_for = (now - last_access) if last_access else None
		# always_on's task runs continuously regardless of viewers -- only
		# last_access (touched on every real HTTP request, see _get_or_start)
		# tells us if anyone's actually watching it right now, so it needs
		# its own status distinct from a real on_demand/fire_on_start "live".
		if mode == 'always_on':
			status = 'watching' if (idle_for is not None and idle_for < idle_timeout) else 'idle (always-on)'
		elif live:
			status = 'watching'
		elif loading:
			status = 'idle (loading screen)'
		else:
			status = 'cold'
		out.append({
			'slug': slug,
			'city_name': city.get('name'),
			'render_mode': mode,
			'status': status,
			'idle_seconds': round(idle_for) if idle_for is not None else None,
		})
	return web.json_response(out)


def main():
	app = web.Application()
	app.router.add_get('/status', handle_status)
	app.router.add_get('/weatherstar/logo.png', handle_logo)
	# Both routes always registered -- aiohttp dispatches by path SEGMENT
	# COUNT (.../slug/filename vs .../slug/key/filename), so they never
	# collide. Which one actually serves anything is decided per-request by
	# _stream_key_cache's current value (see each handler's own docstring):
	# only one of the two ever returns non-403 at a time.
	app.router.add_get('/weatherstar/{slug}/{filename}', handle_hls_file)
	app.router.add_get('/weatherstar/{slug}/{key}/{filename}', handle_hls_file_keyed)

	async def _on_startup(_app):
		asyncio.create_task(_prewarm())
		asyncio.create_task(_reaper())
		asyncio.create_task(_poll_stream_key())

	app.on_startup.append(_on_startup)
	web.run_app(app, host='0.0.0.0', port=LISTEN_PORT, print=None)


if __name__ == '__main__':
	main()
