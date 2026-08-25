"""
Entrypoint for the continuous live-stream renderer (see live_stream.py).
Multi-city: polls the control plane for the active channel list and runs
one live_stream.run() task per city concurrently, starting/stopping tasks
as channels are added/removed. With CONTROL_PLANE_URL unset, falls back to
a single static city (Austin) so this still runs standalone without a
control plane.
"""
import asyncio
import logging
import os

from renderer import control_plane_client
from renderer.live_stream import run

logging.basicConfig(level=logging.INFO, format='[live-main %(asctime)s] %(message)s')
log = logging.getLogger(__name__)

DATA_ROOT = os.environ.get('DATA_ROOT', '/data')
CONFIG_POLL_SECONDS = int(os.environ.get('CONFIG_POLL_SECONDS', '30'))

STATIC_CITY = {
	'slug': os.environ.get('CITY_SLUG', 'austin-tx'),
	'name': os.environ.get('CITY_QUERY', 'Austin, TX'),
	'lat': float(os.environ.get('CITY_LAT', '30.2711286')),
	'lon': float(os.environ.get('CITY_LON', '-97.7436995')),
	'tz': os.environ.get('CITY_TZ', 'America/Chicago'),
	'screens': None,  # None -> every screen defaults to enabled, see live_stream._screen_enabled
	'render_mode': os.environ.get('CITY_RENDER_MODE', 'on_demand'),
	'country': os.environ.get('CITY_COUNTRY', 'US'),
	'ec_city_id': os.environ.get('CITY_EC_ID'),
	'data_root': DATA_ROOT,
}


async def _run_city_forever(city):
	"""live_stream.run() only returns on a crash -- wrap it in a restart
	loop (same "let the orchestrator recover it" philosophy as
	entrypoint.sh's `wait -n` for the Chromium pipeline) so one city's
	transient failure doesn't need the whole container to restart."""
	while True:
		try:
			await run(city)
		except Exception as exc:  # noqa: BLE001
			log.error(f"{city['slug']}: live_stream.run crashed, restarting in 10s: {type(exc).__name__}: {exc}")
			await asyncio.sleep(10)


async def _standalone():
	log.info(f"CONTROL_PLANE_URL not set -- standalone mode, single static city {STATIC_CITY['slug']}")
	await _run_city_forever(STATIC_CITY)


async def _multi_city():
	log.info('CONTROL_PLANE_URL set -- polling for active channels')
	tasks = {}  # slug -> asyncio.Task
	while True:
		try:
			channels = await control_plane_client.fetch_active_channels()
			active_slugs = {c['slug'] for c in channels}

			for slug in list(tasks):
				if slug not in active_slugs:
					log.info(f'{slug}: channel no longer active, stopping')
					tasks.pop(slug).cancel()

			for channel in channels:
				if channel['slug'] in tasks:
					continue
				city = control_plane_client.channel_to_city(channel, DATA_ROOT)
				log.info(f"{city['slug']}: new active channel, starting stream")
				tasks[city['slug']] = asyncio.create_task(_run_city_forever(city))
		except Exception as exc:  # noqa: BLE001 -- one bad poll must not kill every already-running city
			log.error(f'channel poll ERROR: {type(exc).__name__}: {exc}')
		await asyncio.sleep(CONFIG_POLL_SECONDS)


async def main():
	if control_plane_client.is_configured():
		await _multi_city()
	else:
		await _standalone()


if __name__ == '__main__':
	asyncio.run(main())
