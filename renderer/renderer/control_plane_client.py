"""
Thin client for the control plane's WeatherStar agent endpoints -- the
3-endpoint contract any control plane implementation must expose:
GET .../agent/channels/ with an X-Api-Key header, returns a list of
{slug, query, lat, lon, units, screens, force_render}.

CONTROL_PLANE_URL is intentionally optional: with it unset, live_main.py
falls back to a single static city, preserving the "runs standalone without
a control plane" design goal from the approved plan.
"""
import os

import httpx
from timezonefinder import TimezoneFinder

CONTROL_PLANE_URL = os.environ.get('CONTROL_PLANE_URL') or None
AGENT_TOKEN = os.environ.get('AGENT_TOKEN', '')

# The backend's WeatherStarChannel model has no timezone field at all
# (checked backend/app/models/weatherstar.py) -- WS4KP's own client-side JS
# apparently derives it from the geocoded location itself, but our renderer
# needs a real per-city tz server-side (clock display, "tomorrow" day-name
# calculations). One instance, reused across all channel_to_city() calls --
# TimezoneFinder loads a real timezone-boundary dataset once (~100ms), not
# per-lookup.
_tzfinder = TimezoneFinder()


def is_configured():
	return bool(CONTROL_PLANE_URL)


async def fetch_active_channels():
	async with httpx.AsyncClient() as client:
		r = await client.get(
			f'{CONTROL_PLANE_URL}/api/agent/channels/',
			headers={'X-Api-Key': AGENT_TOKEN}, timeout=15,
		)
		r.raise_for_status()
		return r.json()


IDLE_TIMEOUT_FALLBACK_SECONDS = int(os.environ.get('IDLE_TIMEOUT_SECONDS', '600'))


async def fetch_idle_timeout_seconds():
	"""Live per-fleet setting (control plane Settings page -> weatherstar_idle_timeout_seconds),
	polled by the on-demand server's reaper so a change takes effect without a
	container restart. Falls back to IDLE_TIMEOUT_FALLBACK_SECONDS (env var, or
	600s) when the control plane isn't configured/reachable -- same standalone-safe
	pattern as the rest of this module."""
	if not is_configured():
		return IDLE_TIMEOUT_FALLBACK_SECONDS
	try:
		async with httpx.AsyncClient() as client:
			r = await client.get(
				f'{CONTROL_PLANE_URL}/api/agent/settings/',
				headers={'X-Api-Key': AGENT_TOKEN}, timeout=10,
			)
			r.raise_for_status()
			return int(r.json()['idle_timeout_seconds'])
	except Exception:
		return IDLE_TIMEOUT_FALLBACK_SECONDS


async def fetch_stream_key():
	"""Live per-fleet setting (control plane Settings/WeatherStar config page ->
	weatherstar_stream_key) gating the public-facing HLS endpoint -- see
	on_demand_server.py's key check. Unlike fetch_idle_timeout_seconds
	above, a failure here returns None (not a fallback value) and is
	distinct from an empty string (a real, deliberately-unset key): this is
	a security control, not just a UX setting, so the caller must be able
	to tell "couldn't reach the control plane this cycle" apart from "no key
	is required" and hold onto its last known-good value rather than failing
	OPEN (unrestricted access) on a transient blip."""
	if not is_configured():
		return None
	try:
		async with httpx.AsyncClient() as client:
			r = await client.get(
				f'{CONTROL_PLANE_URL}/api/agent/settings/',
				headers={'X-Api-Key': AGENT_TOKEN}, timeout=10,
			)
			r.raise_for_status()
			return r.json().get('stream_key') or ''
	except Exception:
		return None


HLS_LIST_SIZE_FALLBACK = int(os.environ.get('HLS_LIST_SIZE', '16'))


async def fetch_hls_list_size():
	"""Live per-fleet setting (control plane Settings -> HLS buffer window),
	same polling/fallback pattern as fetch_idle_timeout_seconds above. Only
	takes effect on a channel's next ffmpeg start (cold start, idle-stop/
	resume, or a watchdog/force-render restart) -- it's an ffmpeg startup
	argument, not something that can change mid-stream."""
	if not is_configured():
		return HLS_LIST_SIZE_FALLBACK
	try:
		async with httpx.AsyncClient() as client:
			r = await client.get(
				f'{CONTROL_PLANE_URL}/api/agent/settings/',
				headers={'X-Api-Key': AGENT_TOKEN}, timeout=10,
			)
			r.raise_for_status()
			return int(r.json().get('hls_list_size') or HLS_LIST_SIZE_FALLBACK)
	except Exception:
		return HLS_LIST_SIZE_FALLBACK


HLS_TIME_SECONDS_FALLBACK = int(os.environ.get('HLS_TIME_SECONDS', '6'))


async def fetch_hls_time_seconds():
	"""Live per-fleet setting (control plane Settings -> HLS segment length),
	same polling/fallback pattern as fetch_hls_list_size above -- but
	targets a different failure mode: segment-boundary join stutter, not
	buffer starvation. Only takes effect on a channel's next ffmpeg start."""
	if not is_configured():
		return HLS_TIME_SECONDS_FALLBACK
	try:
		async with httpx.AsyncClient() as client:
			r = await client.get(
				f'{CONTROL_PLANE_URL}/api/agent/settings/',
				headers={'X-Api-Key': AGENT_TOKEN}, timeout=10,
			)
			r.raise_for_status()
			return int(r.json().get('hls_time_seconds') or HLS_TIME_SECONDS_FALLBACK)
	except Exception:
		return HLS_TIME_SECONDS_FALLBACK


async def report_render_result(slug, success, error=None):
	async with httpx.AsyncClient() as client:
		r = await client.post(
			f'{CONTROL_PLANE_URL}/api/agent/render-result/',
			headers={'X-Api-Key': AGENT_TOKEN, 'Content-Type': 'application/json'},
			json={'slug': slug, 'success': success, 'error': error}, timeout=15,
		)
		r.raise_for_status()


def channel_to_city(channel, data_root='/data'):
	"""Normalizes a control-plane agent-channel record into the shape
	live_stream.run() expects -- keeps the wire shape and our internal city
	shape independently free to diverge."""
	tz = _tzfinder.timezone_at(lat=channel['lat'], lng=channel['lon']) or 'America/Chicago'
	return {
		'slug': channel['slug'],
		# city_name ("Austin, TX") is what's meant to display on-screen and
		# in the loading splash -- query is the raw geocoder search string
		# (often a ZIP or a long "City, Region, Country" form, e.g. "London,
		# England, United Kingdom"), never intended as display text. Bug
		# found live: this used to prefer `query`, so every screen's
		# location field showed the full geocoder query instead of the
		# short display name.
		'name': channel.get('city_name') or channel.get('query') or channel['slug'],
		'lat': channel['lat'],
		'lon': channel['lon'],
		'tz': tz,
		'units': channel.get('units', 'imperial'),
		'screens': channel.get('screens'),
		'render_mode': channel.get('render_mode', 'on_demand'),
		'country': channel.get('country', 'US'),
		'ec_city_id': channel.get('ec_city_id'),
		'data_root': data_root,
		'force_render': bool(channel.get('force_render')),
	}
