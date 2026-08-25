"""
Tide Info adapter -- NOAA CO-OPS (Tides & Currents, api.tidesandcurrents.noaa.gov),
a completely separate NOAA system from api.weather.gov. Real WeatherStar
4000+ (vbguyny/ws4kp, confirmed live against its own twc3.js) has an
"Almanac / Tides" sub-page showing sunrise/sunset plus the nearest tide
station's today high/low predictions -- we only build the tide-prediction
half here since sunrise/sunset is already its own Almanac screen
(screens/almanac.py backed by adapters/astro.py), so duplicating it on this
screen too would just repeat the same numbers.
"""
from datetime import datetime

import httpx

UA = {'User-Agent': 'classic4kast (self-hosted weather renderer, personal use)'}

STATIONS_URL = 'https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json?type=tidepredictions'
PREDICTIONS_URL = 'https://api.tidesandcurrents.noaa.gov/api/prod/datagetter'

# Real US coastal tide stations only exist near real coastlines -- the
# station list itself has no distance cap, so an inland city would
# otherwise silently get "tide" data for a station hundreds of miles away.
# ~1 degree is roughly 60-70 miles at US latitudes, comfortably wider than
# any real inlet/bay a coastal channel might sit on, tight enough to reject
# genuinely inland locations.
MAX_STATION_DISTANCE_DEGREES = 1.0

_stations_cache = None


async def _load_stations(client):
	global _stations_cache
	if _stations_cache is not None:
		return _stations_cache
	r = await client.get(STATIONS_URL, headers=UA, timeout=20)
	r.raise_for_status()
	_stations_cache = r.json()['stations']
	return _stations_cache


def _fmt_time(t):
	"""NOAA returns 'YYYY-MM-DD HH:MM' in 24h local time -- reformat to
	WS4KP's own '2:35 AM' style (see real DrawText calls in twc3.js)."""
	dt = datetime.strptime(t, '%Y-%m-%d %H:%M')
	return dt.strftime('%I:%M %p').lstrip('0')


async def fetch_tide_info(lat, lon):
	"""Nearest NOAA CO-OPS tide-prediction station's today high/low tides.
	Returns None if no real station is within MAX_STATION_DISTANCE_DEGREES
	-- this screen should only ever be enabled for genuinely coastal
	channels (same "don't fake data for a bad match" reasoning as
	nws.fetch_marine_forecast's nearest-zone match)."""
	async with httpx.AsyncClient(follow_redirects=True) as client:
		stations = await _load_stations(client)
		station = min(stations, key=lambda s: (s['lat'] - lat) ** 2 + (s['lng'] - lon) ** 2)
		dist_deg = ((station['lat'] - lat) ** 2 + (station['lng'] - lon) ** 2) ** 0.5
		if dist_deg > MAX_STATION_DISTANCE_DEGREES:
			return None

		r = await client.get(PREDICTIONS_URL, headers=UA, timeout=15, params={
			'product': 'predictions', 'datum': 'MLLW', 'station': station['id'],
			'time_zone': 'lst_ldt', 'units': 'english', 'interval': 'hilo',
			'format': 'json', 'date': 'today',
		})
		data = r.json()

	predictions = data.get('predictions', [])
	tides = [{
		'type': 'High' if p['type'] == 'H' else 'Low',
		'time': _fmt_time(p['t']),
		'height_ft': round(float(p['v']), 1),
	} for p in predictions]
	return {'station_name': station['name'], 'tides': tides}
