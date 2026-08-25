"""
Continuous live-streaming renderer: generates one fresh frame per second
(base screen + live clock + live ticker overlay) and appends it directly to
a persistent ffmpeg HLS encode. This replaces the "bake a clip once, loop it
forever via -c copy" model for the parts of the screen that need to move
every second -- the clock and the advisory ticker can't be right in a looped
clip no matter how often it's re-baked, because a loop is a fixed sequence
of frozen frames.

Measured cost of this exact model (test_live_clock.py, clock-only, 90s live
run): ~5.5-7.5% CPU sustained. This is NOT the earlier drawtext-on-a-loop
approach that was tried and reverted (~140% CPU) -- that continuously
re-filtered every decoded frame of a looping clip at 30fps forever; this
renders once per second and encodes just that one frame, so the work scales
with real time passing, not with playback frame rate.

Slow-changing data (NWS/EC fetch + screen composition, ~200-330ms) still
happens on the existing render_city-style interval in the background; only
the clock and ticker are redrawn every single frame.
"""
import asyncio
import glob
import io
import logging
import os
import queue
import random
import subprocess
import tempfile
import threading
import time
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo

from renderer import control_plane_client
from renderer.adapters import air_quality, astro, ec, nws, open_meteo, outlook_30day, radar, regional_map, spc, tides
from renderer.layout import RADAR, REGIONAL_MAP, SPC_OUTLOOK
from renderer.live_overlay import draw_clock, draw_ticker
from renderer.screens import (
	almanac,
	current_conditions,
	extended_forecast,
	hourly_forecast,
	hourly_graph,
	local_forecast,
	marine_forecast,
	regional_observations,
	travel_forecast,
)
from renderer.screens import air_quality as air_quality_screen
from renderer.screens import outlook_30day as outlook_30day_screen
from renderer.screens import radar as radar_screen
from renderer.screens import regional_map as regional_map_screen
from renderer.screens import regional_map_forecast as regional_map_forecast_screen
from renderer.screens import regional_map_forecast_night as regional_map_forecast_night_screen
from renderer.screens import spc_outlook
from renderer.screens import tide_info as tide_info_screen

RADAR_BOX = (RADAR['box']['w'], RADAR['box']['h'])
SPC_BOX = (SPC_OUTLOOK['box']['w'], SPC_OUTLOOK['box']['h'])
REGIONAL_MAP_BOX = (REGIONAL_MAP['box']['w'], REGIONAL_MAP['box']['h'])
REGIONAL_MAP_SPAN = 5.0  # matches Radar's own zoom level exactly (adapters/radar.py's fetch_radar_frames default) -- user confirmed Radar's zoom is correct, wanted Regional Observations to match it

# Maps a city's real control-plane 'screens' config (same field names the
# backend API returns, e.g. {'showCurrent': true, ...}) to our screen keys.
# showHazards isn't a
# screen (it toggles the hazard ticker banner, which we draw unconditionally
# today -- not yet wired to this flag) and showAQI has no corresponding
# screen built yet, so it's intentionally absent here rather than silently
# ignored.
SCREEN_CONFIG_KEYS = {
	'current_conditions': 'showCurrent',
	'hourly_forecast': 'showHourly',
	'hourly_forecast_2': 'showHourly',
	'hourly_forecast_3': 'showHourly',
	'extended_forecast': 'showExtendedForecast',
	'extended_forecast_2': 'showExtendedForecast',
	'almanac': 'showAlmanac',
	'local_forecast': 'showLocalForecast',
	'regional_observations': 'showLatestObservations',
	'travel_forecast': 'showTravel',
	'travel_forecast_2': 'showTravel',
	'travel_forecast_3': 'showTravel',
	'hourly_graph': 'showHourlyGraph',
	'regional_map': 'showRegionalForecast',
	'regional_map_forecast': 'showRegionalForecast',
	'regional_map_forecast_night': 'showRegionalForecast',
	'marine_forecast': 'showMarineForecast',
	'air_quality': 'showAQI',
	'tide_info': 'showTideInfo',
	'outlook_30day': 'showOutlook',
}
RADAR_CONFIG_KEY = 'showRadar'

# Which screens have a real data source per country (see
# adapters/nws.py/ec.py/open_meteo.py's own module docstrings for why CA/INTL
# are a strict subset, not just a translation of the same product set --
# Hazards/Regional Observations/Travel Forecast/Regional Map/radar/SPC
# Outlook are real NWS-specific constructs with no equivalent elsewhere).
# None means "no restriction beyond the city's own screens config" (US).
SCREEN_SUPPORT_BY_COUNTRY = {
	'US': None,
	# air_quality is in both non-US sets -- adapters/air_quality.py uses
	# Open-Meteo, which has real global coverage, unlike every other
	# CA/INTL-excluded screen here (NWS/CPC/NOAA CO-OPS, all US-only).
	'CA': {'current_conditions', 'hourly_forecast', 'hourly_forecast_2', 'hourly_forecast_3', 'extended_forecast', 'extended_forecast_2', 'almanac', 'air_quality'},
	'INTL': {'current_conditions', 'hourly_forecast', 'hourly_forecast_2', 'hourly_forecast_3', 'extended_forecast', 'extended_forecast_2', 'almanac', 'air_quality'},
}


def _screen_enabled(city, screen_key):
	"""Defaults to enabled if the city has no 'screens' config at all
	(standalone/no-control-plane operation) or the specific key is missing --
	matches config.js's STATIC_CITIES fallback philosophy of "just works"
	without requiring a control plane. Once a 'screens' dict IS present, an explicitly
	absent/false key really does mean off.

	Country support is checked FIRST and unconditionally -- even a stale/
	misconfigured screens dict (e.g. showLocalForecast still true on a
	channel switched from US to CA) must never trigger an NWS-only fetch
	for a non-US channel; there's no adapter function that would even work."""
	country = city.get('country', 'US')
	supported = SCREEN_SUPPORT_BY_COUNTRY.get(country)
	if supported is not None and screen_key not in supported:
		return False
	screens_cfg = city.get('screens')
	if screens_cfg is None:
		return True
	return bool(screens_cfg.get(SCREEN_CONFIG_KEYS[screen_key], False))


# Real WS4KP's Hourly Graph screen has no .date-time.time element at all --
# confirmed live via DOM inspection -- its legend occupies that same
# top-right space instead. Drawing our live clock there collided with the
# legend text (found from direct user feedback); this matches WS4KP's own
# choice to omit it rather than us inventing a new position.
NO_CLOCK_SCREENS = {'hourly_graph'}

log = logging.getLogger(__name__)

FPS = 4  # bumped from 1fps -- 1fps held each frame for a full second, which
# made ticker motion and screen cuts look steppy. Higher fps costs
# proportionally more render+encode work but each frame is still cheap
# (single-image encode, not continuous re-filtering), so this stays far
# below the rejected drawtext-on-a-loop approach's cost.
FRAME_INTERVAL_SECONDS = 1 / FPS
# Real WS4KP default (confirmed live in shared.min.js: `this.timing =
# {totalScreens:1, baseDelay:9000, delay:1}`, no per-screen override found
# for these 3 screens) -- 6s here earlier was a guess, not measured.
SCREEN_HOLD_SECONDS = 9
DATA_REFRESH_SECONDS = 60

# Watchdog for the audio-encode degradation found live 2026-08-22: after
# running for long enough (observed on a stream that had been up several
# days), ffmpeg's Vorbis decoder's internal DTS/PTS tracking permanently
# desyncs (real values seen: PTS in the ~90 BILLION range vs. an expected
# "next" pointer stuck at ~6 billion) and it starts rejecting every
# subsequent audio packet, logged as repeating "Not a Vorbis I audio packet"
# / "Error submitting packet to decoder" / "invalid dropping". This isn't a
# corrupted source file (every .ogg/.mp3 in the rotation individually
# decodes clean) -- it's -stream_loop -1 + a long-running real-time process
# accumulating drift, so periodic restart is the actual fix, not chasing a
# bad file. Two independent triggers since a stalled encoder doesn't always
# spam stderr right up until the moment output actually stops:
# 1. A burst of audio decode errors in a short window (the degrading case,
#    audible as stutter before it goes fully silent/stuck).
# 2. HLS segment output going stale for way longer than the ~2s cadence
#    (a safety net for any OTHER cause of the same "still running,
#    producing nothing" failure mode -- not exclusively the audio bug).
_AUDIO_ERROR_WINDOW_SECONDS = 15
_AUDIO_ERROR_THRESHOLD = 20
_STALE_SEGMENT_SECONDS = 15


class _State:
	"""Shared between the background data-refresh task and the frame loop.
	Plain mutable object, not a lock-protected structure -- the frame loop
	only ever reads a fully-assembled `screens`/`alert` pair that the
	refresh task swaps in atomically (list/attribute assignment is already
	atomic under asyncio's single-threaded event loop)."""

	def __init__(self):
		self.screens = None
		self.screen_names = None  # parallel to self.screens -- which SCREEN_CONFIG_KEYS entry each slot is, for NO_CLOCK_SCREENS lookup
		self.radar_frames = None
		self.alert = None
		self.last_spc_screen = None
		self.last_regional_map_screen = None
		self.last_regional_map_forecast_screen = None
		self.last_regional_map_forecast_night_screen = None


async def _refresh_loop(city, state, tz):
	# Every screen's .render(...) call below runs inline (NOT offloaded to
	# asyncio.to_thread) -- deliberately reverted 2026-08-24 after live
	# testing showed offloading made things WORSE, not better. Pillow's C
	# extensions release the GIL, so offloaded renders don't just get off
	# the event loop, they run in genuine cross-core PARALLEL with the
	# frame-writer thread AND ffmpeg's own encode/decode threads -- turning
	# one clean, serialized refresh-cycle block into scattered real
	# CPU-core contention during the burst, which showed up as MORE
	# frequent stutter, not less. run()'s own absolute-schedule frame-pacing
	# fix (2026-08-24, same day) already recovers cleanly from an occasional
	# big synchronous block like this one -- that's the layer that should
	# absorb this cost, not thread-level parallelism competing with ffmpeg
	# for the same cores.
	country = city.get('country', 'US')
	# NWS's own fetch functions don't accept a units param at all yet (a
	# separate, larger pre-existing gap -- imperial is hardcoded across all
	# 7 of its screen fetchers, not just these 3) -- only pass units through
	# to the two adapters that actually support it.
	units = city.get('units', 'imperial')
	while True:
		try:
			# Active alerts (hazard ticker) is an NWS-only product -- no EC/
			# Open-Meteo equivalent exists, so non-US channels just run
			# without a ticker rather than attempting a US-only fetch.
			alert = await nws.fetch_active_alerts(city['lat'], city['lon']) if country == 'US' else None
			named = []  # [(screen_key, PIL.Image), ...] -- only enabled screens, in a fixed order

			if _screen_enabled(city, 'current_conditions'):
				if country == 'CA':
					cc = await ec.fetch_current_conditions(city['ec_city_id'], city['lat'], city['lon'], units=units)
				elif country == 'INTL':
					cc = await open_meteo.fetch_current_conditions(city['lat'], city['lon'], city.get('name'), units=units)
				else:
					cc = await nws.fetch_current_conditions(city['lat'], city['lon'])
				named.append(('current_conditions', current_conditions.render(cc)))
			if _screen_enabled(city, 'hourly_forecast'):
				# 12 hours across 3 slides, not just the first 4 -- found
				# from direct user feedback ("add 2 more slides so they can
				# see 12 hours worth"), same 3-slides-of-N pattern as
				# extended_forecast/_2 below. All three adapters share the
				# same hours=N/slice shape already (see their own
				# fetch_hourly_forecast signatures).
				if country == 'CA':
					hourly = await ec.fetch_hourly_forecast(city['ec_city_id'], city['lat'], city['lon'], hours=12, units=units)
				elif country == 'INTL':
					hourly = await open_meteo.fetch_hourly_forecast(city['lat'], city['lon'], hours=12, units=units)
				else:
					hourly = await nws.fetch_hourly_forecast(city['lat'], city['lon'], hours=12)
				named.append(('hourly_forecast', hourly_forecast.render(hourly[:4])))
				if len(hourly) > 4:
					named.append(('hourly_forecast_2', hourly_forecast.render(hourly[4:8])))
				if len(hourly) > 8:
					named.append(('hourly_forecast_3', hourly_forecast.render(hourly[8:12])))
			if _screen_enabled(city, 'extended_forecast'):
				if country == 'CA':
					extended = await ec.fetch_extended_forecast(city['ec_city_id'], city['lat'], city['lon'], days=6, units=units)
				elif country == 'INTL':
					extended = await open_meteo.fetch_extended_forecast(city['lat'], city['lon'], days=6, units=units)
				else:
					extended = await nws.fetch_extended_forecast(city['lat'], city['lon'], days=6)
				named.append(('extended_forecast', extended_forecast.render(extended[:3])))
				# Real WS4KP+ ('WeatherStar 4000+', vbguyny/ws4kp -- confirmed
				# live against its PopulateExtendedForecast(WeatherParameters,
				# ScreenIndex) calls for ScreenIndex 1 AND 2) shows 6 real days
				# across 2 pages, not just 3 -- found from direct user feedback
				# comparing the two apps. Only added if the source actually
				# returned a 2nd page's worth (CA/INTL or a late-day US fetch
				# can come back short).
				if len(extended) > 3:
					named.append(('extended_forecast_2', extended_forecast.render(extended[3:6])))
			if _screen_enabled(city, 'almanac'):
				almanac_data = astro.fetch_almanac(city['lat'], city['lon'], tz)
				named.append(('almanac', almanac.render(almanac_data)))
			if _screen_enabled(city, 'local_forecast'):
				local = await nws.fetch_local_forecast(city['lat'], city['lon'])
				named.append(('local_forecast', local_forecast.render(local)))
			if _screen_enabled(city, 'regional_observations'):
				regional = await nws.fetch_regional_observations(city['lat'], city['lon'])
				named.append(('regional_observations', regional_observations.render(regional)))
			if _screen_enabled(city, 'travel_forecast'):
				# 12 cities across 3 slides, not just the first 4 -- found
				# from direct user feedback, same 3-slides-of-4 pattern as
				# hourly_forecast/extended_forecast above (see nws.
				# TRAVEL_CITIES' own comment for the expanded city list).
				travel = await nws.fetch_travel_forecast()
				named.append(('travel_forecast', travel_forecast.render(travel[:4], tz)))
				if len(travel) > 4:
					named.append(('travel_forecast_2', travel_forecast.render(travel[4:8], tz)))
				if len(travel) > 8:
					named.append(('travel_forecast_3', travel_forecast.render(travel[8:12], tz)))
			if _screen_enabled(city, 'hourly_graph'):
				graph_points = await nws.fetch_hourly_graph(city['lat'], city['lon'])
				named.append(('hourly_graph', hourly_graph.render(graph_points)))
			if _screen_enabled(city, 'marine_forecast'):
				marine = await nws.fetch_marine_forecast(city['lat'], city['lon'])
				named.append(('marine_forecast', marine_forecast.render(marine)))
			if _screen_enabled(city, 'air_quality'):
				try:
					aqi = await air_quality.fetch_air_quality(city['lat'], city['lon'])
				except Exception as aqi_exc:  # noqa: BLE001
					aqi = None
					log.error(f'Air quality fetch ERROR: {type(aqi_exc).__name__}: {aqi_exc}')
				if aqi is not None:
					named.append(('air_quality', air_quality_screen.render(aqi)))
			if _screen_enabled(city, 'tide_info'):
				try:
					tide_data = await tides.fetch_tide_info(city['lat'], city['lon'])
				except Exception as tide_exc:  # noqa: BLE001
					tide_data = None
					log.error(f'Tide info fetch ERROR: {type(tide_exc).__name__}: {tide_exc}')
				# None means no real coastal tide station is near this channel
				# (see tides.fetch_tide_info's MAX_STATION_DISTANCE_DEGREES) --
				# skipped, not shown with fabricated/mismatched station data.
				if tide_data is not None:
					named.append(('tide_info', tide_info_screen.render(tide_data)))
			if _screen_enabled(city, 'outlook_30day'):
				try:
					outlook_30day_data = await outlook_30day.fetch_30day_outlook(city['lat'], city['lon'])
				except Exception as outlook_30day_exc:  # noqa: BLE001
					outlook_30day_data = None
					log.error(f'30-day outlook fetch ERROR: {type(outlook_30day_exc).__name__}: {outlook_30day_exc}')
				if outlook_30day_data is not None:
					named.append(('outlook_30day', outlook_30day_screen.render(outlook_30day_data)))

			# SPC Outlook isn't a real WS4KP screen (no config flag maps to
			# it -- see SCREEN_CONFIG_KEYS), always included as an addition
			# for US channels. It's literally NOAA's US convective outlook
			# -- not "US-flavored", genuinely nothing to show for CA/INTL.
			if country == 'US':
				try:
					outlook_img = await spc.fetch_outlook(SPC_BOX)
					state.last_spc_screen = spc_outlook.render(outlook_img)
				except Exception as spc_exc:  # noqa: BLE001
					log.error(f'SPC outlook fetch ERROR (using last known good): {type(spc_exc).__name__}: {spc_exc}')
				if state.last_spc_screen is not None:
					named.append(('spc_outlook', state.last_spc_screen))

			if _screen_enabled(city, 'regional_map'):
				try:
					regmap_base, regmap_stations = await regional_map.fetch_map(
						city['lat'], city['lon'], REGIONAL_MAP_BOX, REGIONAL_MAP_SPAN, target_name=city.get('name'),
					)
					state.last_regional_map_screen = regional_map_screen.render(
						regmap_base, regmap_stations, city['lat'], city['lon'], REGIONAL_MAP_SPAN,
					)
				except Exception as regmap_exc:  # noqa: BLE001
					log.error(f'Regional map fetch ERROR (using last known good): {type(regmap_exc).__name__}: {regmap_exc}')
				if state.last_regional_map_screen is not None:
					named.append(('regional_map', state.last_regional_map_screen))
			if _screen_enabled(city, 'regional_map_forecast'):
				try:
					regmap_fc_base, regmap_fc_stations = await regional_map.fetch_map_forecast(
						city['lat'], city['lon'], REGIONAL_MAP_BOX, REGIONAL_MAP_SPAN, target_name=city.get('name'),
					)
					state.last_regional_map_forecast_screen = regional_map_forecast_screen.render(
						regmap_fc_base, regmap_fc_stations, city['lat'], city['lon'], REGIONAL_MAP_SPAN, tz,
					)
				except Exception as regmap_fc_exc:  # noqa: BLE001
					log.error(f'Regional map forecast fetch ERROR (using last known good): {type(regmap_fc_exc).__name__}: {regmap_fc_exc}')
				if state.last_regional_map_forecast_screen is not None:
					named.append(('regional_map_forecast', state.last_regional_map_forecast_screen))
			if _screen_enabled(city, 'regional_map_forecast_night'):
				try:
					regmap_fcn_base, regmap_fcn_stations = await regional_map.fetch_map_forecast_night(
						city['lat'], city['lon'], REGIONAL_MAP_BOX, REGIONAL_MAP_SPAN, target_name=city.get('name'),
					)
					state.last_regional_map_forecast_night_screen = regional_map_forecast_night_screen.render(
						regmap_fcn_base, regmap_fcn_stations, city['lat'], city['lon'], REGIONAL_MAP_SPAN, tz,
					)
				except Exception as regmap_fcn_exc:  # noqa: BLE001
					log.error(f'Regional map forecast (night) fetch ERROR (using last known good): {type(regmap_fcn_exc).__name__}: {regmap_fcn_exc}')
				if state.last_regional_map_forecast_night_screen is not None:
					named.append(('regional_map_forecast_night', state.last_regional_map_forecast_night_screen))
			# else: a screen's fetch hasn't succeeded even once yet this run --
			# state.screens is correspondingly short this cycle. The frame
			# loop's slot math works fine against a shorter list; the missing
			# screen just doesn't appear in rotation until its first success.

			state.screens = [img for _, img in named]
			state.screen_names = [name for name, _ in named]

			# Radar animates within its own screen slot (see the frame loop
			# in run()) instead of being one static image like every other
			# screen -- real motion over the last ~35-40 min, not faked.
			# IEM's composite is NEXRAD-derived -- US-only regardless of the
			# city's own screens config, same reasoning as SPC outlook above.
			radar_enabled = country == 'US' and (
				city['screens'].get(RADAR_CONFIG_KEY, False) if city.get('screens') is not None else True
			)
			if radar_enabled:
				raw_frames = await radar.fetch_radar_frames(city['lat'], city['lon'], RADAR_BOX, count=8)
				if raw_frames:
					state.radar_frames = [radar_screen.render(f, city.get('name')) for f in raw_frames]
			else:
				state.radar_frames = []  # explicitly disabled -- frame loop treats an empty (non-None) list as "no radar slot"
			state.alert = alert
			log.info(
				f"{city['slug']}: data refreshed, screens={state.screen_names}, "
				f"radar={'on' if state.radar_frames else 'off'}, alert={'yes: ' + alert['event'] if alert else 'none'}",
			)
		except Exception as exc:  # noqa: BLE001 -- one bad fetch cycle must not kill the stream
			log.error(f'data refresh ERROR: {type(exc).__name__}: {exc}')
		await asyncio.sleep(DATA_REFRESH_SECONDS)


MUSIC_ROOT = os.path.join(os.path.dirname(__file__), 'music')
# 'default' is public-safe (netbymatt/ws4kp-music, AI-generated, MIT-repo
# origin -- see renderer/music/default/NOTICE.md). 'extended' is a
# private-only set (uncertain-provenance tracks) that must be excluded from
# any public/standalone build -- this repo ships 'default' only, so glob
# just finds nothing under a nonexistent 'extended' dir if it's ever listed
# here. Controlled by an env var, not a hardcoded list, specifically so that
# future packaging can flip this without touching code.
MUSIC_SETS = os.environ.get('MUSIC_SETS', 'default,pixabay').split(',')


def _build_music_playlist():
	"""Real WS4KP-style background music, never wired in on either this
	renderer or the old Chromium pipeline (which explicitly ran Chromium
	with --mute-audio) until now, per explicit user request ("wanted and
	needed on live streams"). ffmpeg's concat demuxer needs a real file
	listing tracks -- written once per process start, not regenerated
	per-frame, shuffled so restarts don't always start the same track first.
	Returns None if no tracks are vendored (stream still works, just
	silent, rather than crashing the whole container over missing audio)."""
	tracks = []
	for music_set in MUSIC_SETS:
		music_dir = os.path.join(MUSIC_ROOT, music_set.strip())
		tracks += glob.glob(os.path.join(music_dir, '*.mp3')) + glob.glob(os.path.join(music_dir, '*.ogg'))
	if not tracks:
		log.warning(f'no music tracks found under {MUSIC_ROOT} (sets={MUSIC_SETS}) -- stream will have no audio')
		return None
	random.shuffle(tracks)
	fd, path = tempfile.mkstemp(suffix='.txt', prefix='music_playlist_')
	with os.fdopen(fd, 'w') as f:
		for track in tracks:
			escaped = track.replace("'", "'\\''")
			f.write(f"file '{escaped}'\n")
	return path


def _start_ffmpeg(hls_dir, hls_list_size, hls_time_seconds):
	os.makedirs(hls_dir, exist_ok=True)
	# A fresh ffmpeg instance's own -hls_flags delete_segments only prunes
	# ITS rolling window -- it has no idea a previous instance (killed by
	# the watchdog, or a prior container run) left segments behind under
	# the same directory, so those would otherwise accumulate forever.
	for stale in glob.glob(os.path.join(hls_dir, '*.ts')):
		try:
			os.remove(stale)
		except OSError:
			pass
	playlist_path = _build_music_playlist()

	args = [
		'ffmpeg', '-y', '-loglevel', 'warning',
		'-f', 'image2pipe', '-framerate', str(FPS), '-i', 'pipe:0',
	]
	if playlist_path:
		# -stream_loop -1: loop the whole playlist forever once it ends.
		# -re: read/decode at real playback speed, matching the video
		# input's own real-time pacing (our per-frame sleep loop) instead of
		# ffmpeg racing through the mp3 file as fast as it can decode it.
		# -thread_queue_size: found live 2026-08-24 -- ffmpeg's own stderr
		# ("[aist#1:0/mp3] Resumed reading at pts X ... after a lag of Ys")
		# showed this input's real-time reader falling behind under CPU
		# contention with this SAME process's live video compositing/encode,
		# and -- unlike the isolated single-event lags seen elsewhere --
		# never recovering: 0.3s -> 10s+ and climbing, a genuine unbounded
		# drift, not jitter. ffmpeg's default input thread queue (8 packets)
		# is tiny; a bigger one gives the audio reader room to read ahead
		# during a brief scheduling gap instead of immediately falling
		# behind real-time and never catching back up. Source files are
		# already 48kHz stereo matching the output exactly (confirmed via
		# ffprobe), so this isn't a resampling-cost problem -- it's the
		# audio reader thread not getting scheduled promptly enough,
		# something a queue can absorb but can't fix at its root if the
		# underlying contention is severe/sustained.
		args += ['-thread_queue_size', '4096', '-stream_loop', '-1', '-re', '-f', 'concat', '-safe', '0', '-i', playlist_path]
	args += [
		'-map', '0:v',
		*(['-map', '1:a'] if playlist_path else []),
		'-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'stillimage', '-b:v', '1500k',
		'-pix_fmt', 'yuv420p', '-g', str(FPS),  # one keyframe/sec, same as before
	]
	if playlist_path:
		# -af aresample=async=1: found live 2026-08-24 -- -thread_queue_size
		# above didn't fix the observed unbounded audio lag (still climbing
		# past 2s within a minute), which means it isn't brief scheduling
		# jitter a bigger read-ahead buffer can absorb, it's audio genuinely
		# never resyncing back to the reference timeline once it falls even
		# slightly behind. The video side already has a fully deterministic
		# clock (image2pipe + -framerate assigns synthetic, evenly-spaced
		# PTS from the declared framerate, NOT actual pipe arrival time --
		# confirmed, no -use_wallclock_as_timestamps is set anywhere) --
		# audio is the only side that can drift against it. aresample's
		# async mode is ffmpeg's own built-in mechanism for exactly this:
		# ongoing small sample-rate corrections (insert/drop/stretch a few
		# samples) to continuously pull audio PTS back toward the reference
		# timeline instead of letting a gap compound indefinitely. Keeping
		# -re on the input too (not removing it) -- it's still the only
		# thing bounding this input's decode work to real-time pace in a
		# long-running process; dropping it risks the decoder racing ahead
		# and buffering audio unboundedly instead of correcting drift.
		args += ['-af', 'aresample=async=1', '-c:a', 'aac', '-b:a', '128k', '-ac', '2']
	args += [
		# hls_list_size: now a live-configurable setting (control plane
		# Settings -> HLS buffer window, polled via
		# control_plane_client.fetch_hls_list_size(), default 16 -> 96s
		# window at this 6s segment length) rather than a hardcoded literal.
		# Originally raised 6->10 (12s->20s window at the OLD 2s segment
		# length) because with Dispatcharr's Redirect stream profile
		# (bypasses its own buffering proxy), the player has almost no
		# cushion of its own against the smallest jitter in segment
		# production timing (confirmed live: mostly a rock-steady
		# ~2.0-2.04s/segment, but with occasional ~2.3-3s outliers) -- too
		# small a window puts the player right at the live edge with
		# nothing to fall back on, visible as a brief stall/"blip" every so
		# often. Raised further to 16 by default 2026-08-24 after live
		# testing still showed occasional multi-second hangs even on a
		# direct connection (no Dispatcharr Proxy hop involved), suggesting
		# real segment-production jitter the pipeline benefits from more
		# cushion against. A wider window is a FIXED amount of extra
		# headroom, not unbounded growth like the proxy buffering that
		# caused the original multi-minute drift -- doesn't reintroduce that.
		# hls_time: now also live-configurable (control plane Settings ->
		# HLS segment length, default 6s, polled via
		# control_plane_client.fetch_hls_time_seconds()). Originally raised
		# 2->6 the night of 2026-08-22/23 -- every OTHER fix that night
		# targeted the pipeline's reliability (duplicate encoders, a
		# hung-shutdown zombie, the audio-decode watchdog) and none of them
		# touched the reported "skip every 2 seconds" stutter, which
		# persisted even with a single confirmed-healthy encoder and no
		# decode errors. That periodicity matching -hls_time exactly, even
		# once everything else was clean, pointed at something more
		# fundamental than our own timing: shorter HLS segments mean more
		# frequent player-side buffer-append/join points, a well-known
		# source of HLS micro-stutter independent of the encoder. Widening
		# 2s->6s cut segment boundaries to a third as often. Confirmed
		# 2026-08-24: a WIDER hls_list_size (buffer-starvation cushion, see
		# that setting's own comment) alone did NOT fix a live-observed VLC
		# stutter -- playback clock stayed in sync throughout, ruling out
		# starvation -- pointing right back at join-point frequency, hence
		# this being made independently tunable too rather than assuming
		# 6s was already the final answer.
		'-f', 'hls', '-hls_time', str(hls_time_seconds), '-hls_list_size', str(hls_list_size),
		# See loading_stream.py's identical flags for the full rationale --
		# this ffmpeg is a brand-new encoder timeline handed the SAME output
		# path a still-attached player may already be watching from a much
		# later media sequence number (the loading loop's, or a previous
		# cold-start's real content). Without a discontinuity marker,
		# hls.js can stall entirely instead of resyncing.
		'-hls_flags', 'delete_segments+omit_endlist+independent_segments',
		# start_number: a fresh int(time.time()) every restart, NEVER 0/the
		# default -- found live 2026-08-23. Without this, every restart
		# (cold start, watchdog recovery) renumbers from stream0.ts, and
		# _start_ffmpeg's own cleanup above only deletes files sitting in
		# THIS container's local disk -- it can't reach whatever a CDN
		# (Cloudflare, sitting in front of this over the public URL) or an
		# intermediate cache already has stored under that same low-numbered
		# filename from an EARLIER session. A viewer's report matched this
		# exactly: a cold start briefly played real footage from hours
		# earlier (stale cached stream0.ts/stream1.ts/etc.), threw a couple
		# of format errors (splicing an old cached segment into a
		# discontinuous new timeline), then settled once it reached segment
		# numbers high enough to have never been cached before. A
		# timestamp-based start number can't collide with anything from a
		# past session, so a cache can never have stale content under it.
		'-start_number', str(int(time.time())),
		'-mpegts_flags', 'initial_discontinuity+pat_pmt_at_frames+resend_headers',
		os.path.join(hls_dir, 'stream.m3u8'),
	]
	proc = subprocess.Popen(args, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
	error_times = deque()

	def _watch_stderr():
		# Daemon thread: draining stderr ourselves (rather than leaving it to
		# inherit the parent's) is what lets us actually see/count these
		# lines instead of them just scrolling past in `docker logs` -- and
		# it's required regardless once stderr=PIPE, since an undrained pipe
		# fills up and blocks ffmpeg once the OS buffer is full.
		for line in proc.stderr:
			text = line.decode('utf-8', 'replace')
			if 'Not a Vorbis I audio packet' in text or 'Error submitting packet to decoder' in text:
				error_times.append(time.time())
			# Everything else ffmpeg logs at -loglevel warning was previously
			# read here and silently discarded -- draining the pipe (required
			# regardless, see above) doesn't require throwing the content
			# away. Found live 2026-08-24: a real-audio-input pacing/lag
			# warning (loading_stream.py's OWN ffmpeg logs one on every
			# cold start, its stderr isn't piped at all so it reaches
			# `docker logs` directly) was suspected as a cause of reported
			# audio stutter, but this ffmpeg's real music-file input could
			# be logging something similar or different with zero
			# visibility until now -- forward it so the next report can
			# actually be correlated against what ffmpeg itself observed,
			# instead of guessing blind.
			stripped = text.rstrip()
			if stripped:
				log.info(f"{hls_dir}: ffmpeg: {stripped}")

	threading.Thread(target=_watch_stderr, daemon=True).start()

	# Frame writing runs on its own thread, decoupled from the render loop
	# via a bounded queue -- found live 2026-08-22: the render loop's own
	# `ffmpeg.stdin.write()`/`.flush()` were blocking calls sitting directly
	# in the async loop's per-frame budget (250ms at FPS=4). If ffmpeg's own
	# encoder ever falls slightly behind, that write blocks, stalling the
	# WHOLE render loop's timing for however long the write took. The
	# frame's *content* (drawn from real wall-clock time) still reflects
	# whenever it actually got rendered, so the viewer sees the on-screen
	# clock jump/skip rather than tick smoothly -- a real-time pacing bug,
	# not an encoding bug.
	#
	# maxsize=16 (~4s cushion at FPS=4): a first attempt at 4 (~1s) still
	# showed a skip roughly every 2 seconds once the OTHER bug found the
	# same day (the duplicate-encoder race, see on_demand_server.py) was
	# fixed -- that period lines up with -hls_time 2 below: ffmpeg's own
	# segment-file rollover (closing one .ts, opening the next) happens
	# every 2s and can briefly stall its readiness to read the next stdin
	# frame. A 1s buffer isn't enough to ride that out without dropping
	# frames outright, which is arguably worse than the original blocking
	# write (that only ever delayed content, never discarded it). If the
	# writer is still behind when a new frame is ready, drop that frame
	# (put_nowait) rather than let the render loop block on a full queue --
	# with this much headroom, that should only ever happen under real,
	# sustained backpressure, not routine per-segment housekeeping.
	frame_queue = queue.Queue(maxsize=16)

	def _write_frames():
		while True:
			data = frame_queue.get()
			if data is None:  # sentinel, set by _stop_ffmpeg
				return
			try:
				proc.stdin.write(data)
				proc.stdin.flush()
			except (BrokenPipeError, OSError):
				return

	threading.Thread(target=_write_frames, daemon=True).start()
	return proc, error_times, frame_queue


def _stop_ffmpeg(ffmpeg, frame_queue):
	# Stop the writer thread first (sentinel) so it isn't left trying to
	# write to a stdin we're about to close out from under it. put_nowait,
	# not put -- if the writer is itself stuck blocked on a hung ffmpeg's
	# stdin.write() (exactly the case a stale-segment restart is for), a
	# blocking put() on an already-full queue would hang this shutdown path
	# too. If the queue's full, don't bother -- closing stdin below makes
	# the writer's own write() raise and return on its own regardless.
	try:
		frame_queue.put_nowait(None)
	except queue.Full:
		pass
	# kill() FIRST, unconditionally -- found live 2026-08-23: this used to
	# try stdin.close() -> wait() -> terminate() -> wait() -> kill() in that
	# order, escalating only if each prior step failed. But close() itself
	# can hang (same root cause as the whole reason this function got
	# thread-offloaded with a timeout in the caller: writer thread mid-
	# blocking-write() against a truly-hung ffmpeg). When close() hangs, the
	# function never reaches terminate()/kill() at all -- the caller's
	# timeout gives up WAITING on this function, but the old process itself
	# was never actually killed, so it kept running and writing to the same
	# output path as the fresh replacement the caller started anyway.
	# Result: two live encoders on the same file, the exact duplicate-
	# encoder corruption this whole system exists to prevent, just via the
	# recovery path instead of the original cold-start race. SIGKILL doesn't
	# touch the pipe/fd at all, so it can't hang on the same thing -- send
	# it up front regardless of stdin state, THEN clean up stdin (which no
	# longer matters much once the process is actually dead).
	ffmpeg.kill()
	try:
		ffmpeg.wait(timeout=10)
	except subprocess.TimeoutExpired:
		pass  # genuinely stuck (e.g. uninterruptible D-state) -- nothing more to do from here
	try:
		ffmpeg.stdin.close()
	except (OSError, ValueError):
		pass


def _latest_segment_age(hls_dir):
	"""Seconds since the newest .ts segment was written, or None if there
	isn't one yet (stream just (re)started -- not a staleness signal)."""
	segments = glob.glob(os.path.join(hls_dir, '*.ts'))
	if not segments:
		return None
	newest = max(segments, key=os.path.getmtime)
	return time.time() - os.path.getmtime(newest)


def _render_frame(base_img, skip_clock, tz, alert, elapsed):
	"""The actual CPU-bound per-frame work (image copy, clock/ticker draw,
	PNG encode) -- pulled out to its own function so run()'s loop can hand
	it to asyncio.to_thread instead of running it inline. See the call
	site's comment for why."""
	img = base_img.copy()
	if not skip_clock:
		draw_clock(img, tz)
	draw_ticker(img, alert, elapsed)
	bio = io.BytesIO()
	img.save(bio, format='PNG')
	return bio.getvalue()


async def run(city, on_ready=None):
	"""on_ready: optional async callback invoked right before this starts its
	own ffmpeg (first real data fetch already complete) -- the on-demand
	server's cue to stop the temporary loading-screen loop, so the two never
	write to the same HLS output path concurrently."""
	tz = ZoneInfo(city.get('tz', 'America/Chicago'))
	# Matches the existing Chromium-pipeline's URL contract exactly
	# (/weatherstar/{slug}/stream.m3u8 -> alias /data/{slug}/hls/, see
	# weatherstar/nginx.conf) so this is a drop-in replacement -- no
	# downstream Dispatcharr channel config needs to change.
	hls_dir = f"{city['data_root']}/{city['slug']}/hls"
	state = _State()

	log.info(f"waiting for first data fetch before starting stream -- {city['slug']}")
	asyncio.create_task(_refresh_loop(city, state, tz))
	while state.screens is None or state.radar_frames is None:
		await asyncio.sleep(0.2)

	# Fetched once per run() invocation (i.e. per cold start / idle-resume /
	# force-render restart), not re-polled every watchdog restart within the
	# same run() -- a config change takes effect on the next one of those,
	# which happens often enough in practice without adding a network call
	# to the watchdog's already-time-sensitive restart path.
	hls_list_size = await control_plane_client.fetch_hls_list_size()
	hls_time_seconds = await control_plane_client.fetch_hls_time_seconds()
	if on_ready is not None:
		await on_ready()
	ffmpeg, error_times, frame_queue = _start_ffmpeg(hls_dir, hls_list_size, hls_time_seconds)
	log.info(f"{city['slug']}: live stream started -- {hls_dir}/stream.m3u8")

	stream_start = time.time()
	frame_count = 0
	last_watchdog_check = stream_start
	try:
		while True:
			t0 = time.time()
			elapsed = t0 - stream_start

			# See _AUDIO_ERROR_THRESHOLD's comment above -- swap in a fresh
			# ffmpeg in place rather than tearing down this whole run() (which
			# would mean re-fetching screens/radar from scratch). Once a
			# second is plenty; this isn't the kind of thing that needs to be
			# caught within a frame.
			if t0 - last_watchdog_check >= 1:
				last_watchdog_check = t0
				while error_times and t0 - error_times[0] > _AUDIO_ERROR_WINDOW_SECONDS:
					error_times.popleft()
				segment_age = _latest_segment_age(hls_dir)
				stale = segment_age is not None and segment_age > _STALE_SEGMENT_SECONDS
				if len(error_times) > _AUDIO_ERROR_THRESHOLD or stale:
					reason = (
						f"{len(error_times)} audio decode errors in the last "
						f"{_AUDIO_ERROR_WINDOW_SECONDS}s" if not stale else
						f"no new HLS segment in {segment_age:.1f}s"
					)
					log.warning(f"{city['slug']}: restarting ffmpeg -- {reason}")
					# Found live 2026-08-22: this used to call _stop_ffmpeg
					# directly (synchronously) right here in the async loop.
					# A stale-segment restart means ffmpeg itself may be
					# genuinely hung (not just slow), and _stop_ffmpeg's
					# ffmpeg.stdin.close() -- called from THIS thread while
					# the writer thread could be mid-blocking-write on that
					# same stdin -- could then hang too. Since this whole
					# renderer is one shared process/event loop across every
					# city, that hang froze EVERY channel for 8 hours
					# straight, not just the one that triggered it -- the
					# exact opposite of what a watchdog is for. Now runs on
					# its own thread so a hang there can never block the
					# event loop, with a hard timeout so even a truly stuck
					# cleanup can't stall this city's OWN recovery forever
					# either (the old process is abandoned as a harmless
					# zombie in that case -- getting a fresh working encoder
					# up matters more than a clean old one going away).
					try:
						await asyncio.wait_for(
							asyncio.to_thread(_stop_ffmpeg, ffmpeg, frame_queue), timeout=20,
						)
					except asyncio.TimeoutError:
						log.error(f"{city['slug']}: _stop_ffmpeg didn't finish within 20s -- abandoning it, starting fresh anyway")
					ffmpeg, error_times, frame_queue = _start_ffmpeg(hls_dir, hls_list_size, hls_time_seconds)
					stream_start = time.time()
					# Must reset alongside stream_start -- the frame-pacing
					# schedule below is stream_start + frame_count *
					# FRAME_INTERVAL_SECONDS; leaving a large accumulated
					# frame_count against a freshly-reset stream_start would
					# target a schedule far in the future, stalling frame
					# production for a long time after every watchdog restart.
					frame_count = 0
					continue
			# Radar gets its own rotation slot, appended after the static
			# screens -- within that slot it cycles through recent radar
			# sweeps instead of holding one frame, a real animated loop.
			# Only added when radar is actually enabled for this city AND has
			# fetched successfully at least once (state.radar_frames is a
			# non-empty list, not the initial None or the []-when-disabled
			# sentinel -- see _refresh_loop).
			has_radar_slot = bool(state.radar_frames)
			total_slots = len(state.screens) + (1 if has_radar_slot else 0)
			slot = int(elapsed // SCREEN_HOLD_SECONDS) % max(1, total_slots)
			if slot < len(state.screens):
				base_img = state.screens[slot]
				skip_clock = state.screen_names[slot] in NO_CLOCK_SCREENS
			else:
				frames = state.radar_frames
				elapsed_in_slot = elapsed % SCREEN_HOLD_SECONDS
				sub_idx = int(elapsed_in_slot / SCREEN_HOLD_SECONDS * len(frames)) % len(frames)
				base_img = frames[sub_idx]
				skip_clock = False

			# Offloaded to a worker thread -- found live 2026-08-23 running
			# two channels concurrently: image.copy()/draw_clock/draw_ticker/
			# PNG-encode are all CPU-bound and were running directly in this
			# shared async loop, so one city's render work could genuinely
			# stall every OTHER concurrently-running city's frame timing
			# (Python's GIL means only one can execute Python bytecode at a
			# time). Matched a real symptom: a second concurrent channel
			# caused an otherwise-healthy one to briefly show no audio and
			# long delays between the clock/frame changing -- CPU starvation
			# of its OWN render loop, not an encoder problem. to_thread lets
			# Pillow's underlying C-level image/PNG work actually run
			# alongside other cities' Python-level work instead of
			# serializing everything through one thread.
			png_bytes = await asyncio.to_thread(_render_frame, base_img, skip_clock, tz, state.alert, elapsed)
			try:
				frame_queue.put_nowait(png_bytes)
			except queue.Full:
				# Writer's behind -- drop this frame rather than block the
				# render loop's own timing (see _start_ffmpeg's comment).
				pass
			frame_count += 1

			if frame_count % (FPS * 30) == 0:
				log.info(f"{city['slug']}: {frame_count} frames streamed")

			# Anchored to the ABSOLUTE stream_start-based schedule, not each
			# frame's own render cost -- found live 2026-08-24, root cause of
			# an unbounded, deterministic (reproduced identically even with
			# CPU dedicated in edm-dev -- not a scheduling/contention issue)
			# audio drift. The old `sleep(max(0, FRAME_INTERVAL_SECONDS -
			# render_cost))` budgeted each frame independently: any single
			# frame whose render work (PIL compositing/clock-ticker draw/PNG
			# encode -- entirely plausible on a radar frame, regardless of
			# available CPU, since it's single-threaded per-frame work) ever
			# exceeded FRAME_INTERVAL_SECONDS clamped straight to zero sleep,
			# and that lost time was gone forever -- never recovered by a
			# later fast frame. frame_count still incremented once per
			# iteration either way, and ffmpeg's declared -framerate assumes
			# every fed frame is exactly FRAME_INTERVAL_SECONDS of video
			# time -- so after enough frames, the video's own synthetic PTS
			# clock (frame_count * FRAME_INTERVAL_SECONDS) silently fell
			# behind real elapsed time, while the audio input (paced by -re
			# against the real system clock) kept tracking real time exactly.
			# That's audio "outrunning" a video clock quietly running slow --
			# neither a bigger read-ahead buffer nor an audio resample-drift
			# filter could touch it, because the audio side was never the
			# one wrong. Anchoring to an absolute target (stream_start +
			# frame_count * FRAME_INTERVAL_SECONDS) lets an occasional slow
			# frame get absorbed by a shorter/zero sleep on the NEXT one
			# instead of permanently lost -- self-correcting rather than
			# accumulating. If genuinely sustained slow frames ever outpace
			# what catch-up can absorb, sleep just stays at 0 (queue.Full
			# drops the excess rather than let the render loop's own timing
			# block) -- an honest degradation, not a silent lie to ffmpeg.
			next_frame_at = stream_start + (frame_count) * FRAME_INTERVAL_SECONDS
			await asyncio.sleep(max(0, next_frame_at - time.time()))
	finally:
		# Same reasoning as the watchdog restart path above -- offload to a
		# thread with a hard timeout so a hung ffmpeg can't block the
		# shared event loop during normal shutdown/cancellation either.
		try:
			await asyncio.wait_for(asyncio.to_thread(_stop_ffmpeg, ffmpeg, frame_queue), timeout=20)
		except asyncio.TimeoutError:
			log.error(f"{city['slug']}: _stop_ffmpeg didn't finish within 20s during shutdown -- abandoning it")
