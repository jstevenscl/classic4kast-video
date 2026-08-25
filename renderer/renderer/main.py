"""
Native (Pillow-based) renderer -- produces the same baked.mp4 the
Chromium-based renderer (weatherstar/src/renderer.js) does, at the same
/data/{slug}/baked.mp4 path, so the existing streamer.js can loop it
unchanged. This is the side-by-side prototype: same output contract,
completely different (and ~1000x cheaper) render path.

City config here is a minimal standalone version for the comparison demo --
production wiring (control-plane API polling, per-city screen selection)
follows the same pattern already built for the Chromium renderer, once
this is proven out.
"""
import asyncio
import logging
import sys
import time
from zoneinfo import ZoneInfo

from renderer import assets
from renderer.adapters import astro, nws, radar, regional_map, spc
from renderer.compositor import bake_clip
from renderer.layout import ADVISORY_BANNER, RADAR, REGIONAL_MAP, SPC_OUTLOOK
from renderer.screens import (
	almanac,
	current_conditions,
	extended_forecast,
	hourly_forecast,
	hourly_graph,
	local_forecast,
	regional_observations,
	travel_forecast,
)
from renderer.screens import radar as radar_screen
from renderer.screens import regional_map as regional_map_screen
from renderer.screens import regional_map_forecast as regional_map_forecast_screen
from renderer.screens import spc_outlook

RADAR_BOX = (RADAR['box']['w'], RADAR['box']['h'])
SPC_BOX = (SPC_OUTLOOK['box']['w'], SPC_OUTLOOK['box']['h'])
REGIONAL_MAP_BOX = (REGIONAL_MAP['box']['w'], REGIONAL_MAP['box']['h'])
REGIONAL_MAP_SPAN = 5.0  # matches Radar's own zoom level exactly (adapters/radar.py's fetch_radar_frames default) -- user confirmed Radar's zoom is correct, wanted Regional Observations to match it

logging.basicConfig(level=logging.INFO, format='[native-renderer %(asctime)s] %(message)s')
log = logging.getLogger(__name__)

CITY = {'slug': 'austin-tx-native', 'name': 'Austin, TX', 'lat': 30.2711286, 'lon': -97.7436995, 'data_root': '/data', 'tz': 'America/Chicago'}


async def render_city(city):
	t0 = time.time()
	cc = await nws.fetch_current_conditions(city['lat'], city['lon'])
	hourly = await nws.fetch_hourly_forecast(city['lat'], city['lon'])
	extended = await nws.fetch_extended_forecast(city['lat'], city['lon'])
	alert = await nws.fetch_active_alerts(city['lat'], city['lon'])
	almanac_data = astro.fetch_almanac(city['lat'], city['lon'], ZoneInfo(city['tz']))
	local = await nws.fetch_local_forecast(city['lat'], city['lon'])
	regional = await nws.fetch_regional_observations(city['lat'], city['lon'])
	travel = await nws.fetch_travel_forecast()
	graph_points = await nws.fetch_hourly_graph(city['lat'], city['lon'])
	outlook_img = await spc.fetch_outlook(SPC_BOX)
	regmap_base, regmap_stations = await regional_map.fetch_map(city['lat'], city['lon'], REGIONAL_MAP_BOX, REGIONAL_MAP_SPAN)
	regmap_fc_base, regmap_fc_stations = await regional_map.fetch_map_forecast(city['lat'], city['lon'], REGIONAL_MAP_BOX, REGIONAL_MAP_SPAN)
	# This bake-once-and-loop pipeline can't animate the way live_stream.py's
	# radar slot does (see that module) -- shows the single latest sweep,
	# same static-frame treatment as every other screen here. A known,
	# documented limitation of this older pipeline, not an oversight.
	radar_frames = await radar.fetch_radar_frames(city['lat'], city['lon'], RADAR_BOX, count=1)
	fetch_ms = (time.time() - t0) * 1000

	t1 = time.time()
	images = [
		current_conditions.render(cc),
		hourly_forecast.render(hourly),
		extended_forecast.render(extended),
		almanac.render(almanac_data),
		local_forecast.render(local),
		regional_observations.render(regional),
		travel_forecast.render(travel, ZoneInfo(city['tz'])),
		hourly_graph.render(graph_points),
		spc_outlook.render(outlook_img),
		regional_map_screen.render(regmap_base, regmap_stations, city['lat'], city['lon'], REGIONAL_MAP_SPAN),
		regional_map_forecast_screen.render(
			regmap_fc_base, regmap_fc_stations, city['lat'], city['lon'], REGIONAL_MAP_SPAN, ZoneInfo(city['tz']),
		),
	]
	if radar_frames:
		images.append(radar_screen.render(radar_frames[-1], city.get('name')))
	# Drawn fresh here, every cycle, from real alert data -- never baked
	# into a template, so it can't go stale the way the old frozen banner
	# did (see layout.ADVISORY_BANNER's docstring).
	for img in images:
		assets.draw_advisory_banner(img, alert, ADVISORY_BANNER)
	render_ms = (time.time() - t1) * 1000

	t2 = time.time()
	data_dir = f"{city['data_root']}/{city['slug']}"
	tmp_dir = f'{data_dir}/tmp'
	output_path = f'{data_dir}/baked.mp4'
	size = await bake_clip(images, tmp_dir, output_path)
	bake_ms = (time.time() - t2) * 1000

	log.info(
		f"{city['slug']}: done -- fetch={fetch_ms:.0f}ms render={render_ms:.0f}ms "
		f'bake={bake_ms:.0f}ms total={(fetch_ms + render_ms + bake_ms):.0f}ms {size} bytes '
		f"alert={'yes: ' + alert['event'] if alert else 'none'}",
	)


async def main():
	# The whole point of this architecture: rendering is now ~200ms instead
	# of 55-75s per city, so there's no longer a real reason to hold this at
	# 300s (the old Chromium-cost-driven interval). 60s means the displayed
	# clock is never more than a minute stale, and NWS station observations
	# themselves only update every ~20-60 min anyway, so this comfortably
	# catches new data promptly without polling far faster than the
	# underlying data ever changes.
	interval = int(sys.argv[1]) if len(sys.argv) > 1 else 60
	log.info(f'starting -- native renderer, interval={interval}s, city={CITY["slug"]}')
	for _ in range(1_000_000):
		try:
			await render_city(CITY)
		except Exception as exc:  # noqa: BLE001 -- never let one bad cycle kill the loop, same as renderer.js
			log.error(f'render cycle ERROR: {type(exc).__name__}: {exc}')
		await asyncio.sleep(interval)


if __name__ == '__main__':
	asyncio.run(main())
