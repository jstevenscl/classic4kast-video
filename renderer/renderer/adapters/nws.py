"""
NWS (api.weather.gov, US-only) adapter. Icon mapping ported directly from
netbymatt/ws4kp's own largeIcon() switch (server/resources/shared.min.js,
grep for 'current-conditions/') -- not a hand-guessed subset, the real
production mapping covering every NWS condition code with day/night
variants and the >50% probability branch for Heavy-Snow vs Light-Snow.

Unit gotcha found and fixed while prototyping this: NWS observation
windSpeed is reported in km/h (wmoUnit:km_h-1), not m/s -- using the m/s
factor inflated wind speed ~3.6x.
"""
import asyncio
import re
from datetime import datetime, timedelta

import httpx

from renderer.adapters import environment_canada

# ── Marine Forecast ──────────────────────────────────────────────────────────
# NWS's modern structured API explicitly doesn't support marine zones yet --
# confirmed live: GET /zones/forecast/{marineZoneId}/forecast returns 404
# "MarineForecastNotSupported...not yet supported by this API". The data
# itself is real and current though, still published as the classic Coastal
# Waters Forecast (CWF) text bulletin via the legacy text-product system
# (also served through api.weather.gov, just not as structured JSON) -- this
# parses that bulletin instead. Zone lookup by point isn't supported either
# (GET /zones?type=marine&point=... returns an empty FeatureCollection, at
# least for the areas tested) -- falls back to loading the ~700-zone list
# once and nearest-matching by polygon centroid, same approach as radar.py's
# MAJOR_CITIES nearest-match.
_MARINE_ZONES_URL = 'https://api.weather.gov/zones/marine'
_marine_zones_cache = None


def _polygon_centroid(geometry):
	"""Simple vertex-average centroid (not area-weighted) -- adequate for
	nearest-zone matching against zones sized like ours (tens of miles), not
	precise enough for anything requiring a true geometric centroid."""
	coords = geometry['coordinates']
	rings = coords[0] if geometry['type'] == 'Polygon' else coords[0][0]
	xs = [c[0] for c in rings]
	ys = [c[1] for c in rings]
	return sum(xs) / len(xs), sum(ys) / len(ys)


_MARINE_ZONE_FETCH_CONCURRENCY = 20


async def _fetch_zone_centroid(client, sem, zone_id, name):
	"""The bulk /zones/marine list returns geometry: null for every feature
	(confirmed live) -- only each zone's own individual detail endpoint
	actually carries its polygon. Fetched once per zone, concurrently
	(capped by sem) since this only runs the first time this process needs a
	marine forecast, then stays cached for the process lifetime."""
	async with sem:
		try:
			r = await client.get(f'https://api.weather.gov/zones/marine/{zone_id}', headers=UA, timeout=15)
			r.raise_for_status()
			geom = r.json().get('geometry')
			if not geom:
				return None
			clon, clat = _polygon_centroid(geom)
			return {'id': zone_id, 'name': name, 'lat': clat, 'lon': clon}
		except (httpx.HTTPError, KeyError, IndexError, ZeroDivisionError):
			return None


async def _load_marine_zones(client):
	global _marine_zones_cache
	if _marine_zones_cache is not None:
		return _marine_zones_cache
	r = await client.get(_MARINE_ZONES_URL, headers=UA, timeout=20)
	r.raise_for_status()
	listed = [
		(f['properties']['id'], f['properties'].get('name', ''))
		for f in r.json().get('features', [])
	]
	sem = asyncio.Semaphore(_MARINE_ZONE_FETCH_CONCURRENCY)
	results = await asyncio.gather(*(_fetch_zone_centroid(client, sem, zid, name) for zid, name in listed))
	zones = [z for z in results if z is not None]
	_marine_zones_cache = zones
	return zones


async def _nearest_marine_zone(client, lat, lon):
	zones = await _load_marine_zones(client)
	if not zones:
		return None
	return min(zones, key=lambda z: (z['lat'] - lat) ** 2 + (z['lon'] - lon) ** 2)


# Non-greedy body capture runs until the next '.PERIOD...' line or the end
# of the section -- an earlier `(.+)$` (MULTILINE, no DOTALL) matched only
# the period's own first physical line, silently truncating every period's
# forecast text at its first hard line-wrap (found live: real bulletin text
# wraps every ~70 chars).
_PERIOD_RE = re.compile(r'^\.([A-Z][A-Z /]+)\.\.\.(.*?)(?=^\.[A-Z]|\Z)', re.MULTILINE | re.DOTALL)


def _expand_ugc_zones(header_line):
	"""UGC header lines combine adjacent zones sharing one forecast text under
	a single header, e.g. 'AMZ450-452-454-210915-' names AMZ450, AMZ452 AND
	AMZ454 (confirmed live against a real JAX CWF bulletin) -- only the first
	token carries the full state/type prefix, later ones are bare numeric
	suffixes that inherit it. Final token is always the UGC expiration
	code (DDHHmm), not a zone."""
	parts = [p for p in header_line.strip().rstrip('-').split('-') if p]
	if len(parts) < 2:
		return []
	parts = parts[:-1]  # drop the trailing DDHHmm expiration code
	zones, prefix = [], ''
	for token in parts:
		if not token.isdigit():
			prefix = token[:3]
			zones.append(token)
		else:
			zones.append(prefix + token)
	return zones


def _parse_cwf_section(product_text, zone_id):
	"""CWF bulletins are one text blob covering every zone an office issues
	for, sections separated by '$$', each starting with a UGC header line
	naming the zone(s) it applies to. Returns the zone_section_text for the
	FIRST section whose header references zone_id, or None if not found
	(e.g. the office's product doesn't cover this particular zone)."""
	for section in product_text.split('$$'):
		first_line = section.strip().split('\n', 1)[0] if section.strip() else ''
		if zone_id in _expand_ugc_zones(first_line):
			return section
	return None


async def fetch_marine_forecast(lat, lon):
	async with httpx.AsyncClient(follow_redirects=True) as client:
		zone = await _nearest_marine_zone(client, lat, lon)
		if zone is None:
			return {'zone_name': '', 'period_name': '', 'text': 'Marine forecast unavailable'}

		zone_resp = await client.get(f'https://api.weather.gov/zones/marine/{zone["id"]}', headers=UA, timeout=10)
		office = zone_resp.json()['properties']['gridIdentifier']

		products_resp = await client.get(
			f'https://api.weather.gov/products/types/CWF/locations/{office}', headers=UA, timeout=10,
		)
		items = products_resp.json().get('@graph', [])
		if not items:
			return {'zone_name': zone['name'], 'period_name': '', 'text': 'Marine forecast unavailable'}

		product_resp = await client.get(items[0]['@id'], headers=UA, timeout=10)
		product_text = product_resp.json().get('productText', '')

	section = _parse_cwf_section(product_text, zone['id'])
	if not section:
		return {'zone_name': zone['name'], 'period_name': '', 'text': 'Marine forecast unavailable'}

	periods = _PERIOD_RE.findall(section)
	if not periods:
		return {'zone_name': zone['name'], 'period_name': '', 'text': 'Marine forecast unavailable'}
	name, text = periods[0]
	return {
		'zone_name': zone['name'],
		'period_name': name.strip().title(),
		'text': ' '.join(text.split()),  # collapse the bulletin's hard line-wraps into one paragraph
	}

UA ={'User-Agent': 'classic4kast (self-hosted weather renderer, personal use)'}

_CONDITION_ICON = {
	'skc': 'Sunny', 'hot': 'Sunny', 'haze': 'Sunny', 'cold': 'Sunny',
	'skc-n': 'Clear', 'haze-n': 'Clear', 'cold-n': 'Clear',
	'dust': 'Smoke', 'dust-n': 'Smoke', 'smoke': 'Smoke', 'smoke-n': 'Smoke',
	'few': 'Partly-Cloudy', 'sct': 'Partly-Cloudy', 'bkn': 'Partly-Cloudy',
	'few-n': 'Mostly-Clear', 'sct-n': 'Mostly-Clear', 'bkn-n': 'Mostly-Clear',
	'ovc': 'Cloudy', 'ovc-n': 'Cloudy',
	'fog': 'Fog', 'fog-n': 'Fog',
	'rain_sleet': 'Rain-Sleet', 'rain_sleet-n': 'Rain-Sleet',
	'sleet': 'Sleet', 'sleet-n': 'Sleet',
	'rain_showers': 'Shower', 'rain_showers_hi': 'Shower', 'rain_showers_high': 'Shower',
	'rain_showers-n': 'Shower', 'rain_showers_hi-n': 'Shower', 'rain_showers_high-n': 'Shower',
	'rain': 'Rain', 'rain-n': 'Rain',
	'rain_snow': 'Rain-Snow', 'rain_snow-n': 'Rain-Snow',
	'snow_fzra': 'Freezing-Rain-Snow', 'snow_fzra-n': 'Freezing-Rain-Snow',
	'winter_mix': 'Freezing-Rain-Snow', 'winter_mix-n': 'Freezing-Rain-Snow',
	'fzra': 'Freezing-Rain', 'fzra-n': 'Freezing-Rain', 'rain_fzra': 'Freezing-Rain', 'rain_fzra-n': 'Freezing-Rain',
	'snow_sleet': 'Snow-Sleet', 'snow_sleet-n': 'Snow-Sleet',
	'tsra_sct': 'Scattered-Thunderstorms-Day', 'tsra': 'Scattered-Thunderstorms-Day',
	'tsra_sct-n': 'Scattered-Thunderstorms-Night', 'tsra-n': 'Scattered-Thunderstorms-Night',
	'tsra_hi': 'Thunderstorm', 'tsra_hi-n': 'Thunderstorm', 'tornado': 'Thunderstorm', 'tornado-n': 'Thunderstorm',
	'hurricane': 'Thunderstorm', 'hurricane-n': 'Thunderstorm', 'tropical_storm': 'Thunderstorm', 'tropical_storm-n': 'Thunderstorm',
	'wind_skc': 'Windy', 'wind_': 'Windy', 'wind_-n': 'Windy', 'wind_skc-n': 'Windy',
	'wind_few': 'Windy', 'wind_few-n': 'Windy', 'wind_sct': 'Windy', 'wind_sct-n': 'Windy',
	'wind_bkn': 'Windy', 'wind_bkn-n': 'Windy', 'wind_ovc': 'Windy', 'wind_ovc-n': 'Windy',
	'blizzard': 'Blowing-Snow', 'blizzard-n': 'Blowing-Snow',
}

# Separate mapping for the 'regional-maps' icon set (used by Travel
# Forecast, matching real WS4KP -- confirmed live via DOM inspection, e.g.
# 'Scattered-Showers-1994.gif', 'Hot.gif') -- a visually distinct icon set
# from 'current-conditions' with different filenames/art style, not a subset.
# No official code->filename table was found in WS4KP's own bundle for this
# set (unlike the current-conditions largeIcon() switch), so this is our own
# reasonable mapping from the same NWS icon codes onto the regional-maps
# files we have vendored -- best-effort, not a byte-for-byte port.
_REGIONAL_ICON = {
	'skc': 'Sunny', 'skc-n': 'Clear-1992', 'hot': 'Hot', 'cold': 'Cold',
	'haze': 'Haze', 'haze-n': 'Haze', 'dust': 'Smoke', 'dust-n': 'Smoke', 'smoke': 'Smoke', 'smoke-n': 'Smoke',
	'few': 'Partly-Cloudy', 'sct': 'Partly-Cloudy', 'few-n': 'Partly-Cloudy-Night', 'sct-n': 'Partly-Cloudy-Night',
	'bkn': 'Mostly-Cloudy-1994', 'bkn-n': 'Mostly-Cloudy-1994',
	'ovc': 'Cloudy', 'ovc-n': 'Cloudy',
	'fog': 'Fog', 'fog-n': 'Fog',
	'wind_skc': 'Sunny-Wind-1994', 'wind_skc-n': 'Clear-Wind-1994', 'wind_few': 'Sunny-Wind-1994', 'wind_sct': 'Sunny-Wind-1994',
	'wind_bkn': 'Cloudy-Wind', 'wind_ovc': 'Cloudy-Wind', 'wind_': 'Wind', 'wind_-n': 'Wind',
	'rain': 'Rain-1992', 'rain-n': 'Rain-1992',
	'rain_showers': 'Scattered-Showers-1994', 'rain_showers_hi': 'Scattered-Showers-1994', 'rain_showers_high': 'Scattered-Showers-1994',
	'rain_showers-n': 'Scattered-Showers-Night-1994', 'rain_showers_hi-n': 'Scattered-Showers-Night-1994', 'rain_showers_high-n': 'Scattered-Showers-Night-1994',
	'tsra_sct': 'Scattered-Tstorms-1994', 'tsra': 'Scattered-Tstorms-1994',
	'tsra_sct-n': 'Scattered-Tstorms-Night-1994', 'tsra-n': 'Scattered-Tstorms-Night-1994',
	'tsra_hi': 'Thunderstorm', 'tsra_hi-n': 'Thunderstorm', 'tornado': 'Thunderstorm', 'tornado-n': 'Thunderstorm',
	'hurricane': 'Thunderstorm', 'hurricane-n': 'Thunderstorm', 'tropical_storm': 'Thunderstorm', 'tropical_storm-n': 'Thunderstorm',
	'rain_snow': 'Rain-Snow-1992', 'rain_snow-n': 'Rain-Snow-1992',
	'snow_fzra': 'Freezing-Rain-Snow-1994', 'snow_fzra-n': 'Freezing-Rain-Snow-1994',
	'winter_mix': 'Freezing-Rain-Snow-1994', 'winter_mix-n': 'Freezing-Rain-Snow-1994',
	'fzra': 'Freezing-Rain-1992', 'fzra-n': 'Freezing-Rain-1992', 'rain_fzra': 'Freezing-Rain-1992', 'rain_fzra-n': 'Freezing-Rain-1992',
	'snow_sleet': 'Snow-Sleet', 'snow_sleet-n': 'Snow-Sleet',
	'rain_sleet': 'Rain-Sleet', 'rain_sleet-n': 'Rain-Sleet',
	'sleet': 'Sleet', 'sleet-n': 'Sleet',
	'blizzard': 'Blowing-Snow', 'blizzard-n': 'Blowing-Snow',
}


def icon_from_nws_url_regional(icon_url):
	if not icon_url:
		return 'Sunny'
	code, probability, is_night = _parse_icon_url(icon_url)
	if code == 'snow':
		return 'Heavy-Snow-1994' if probability > 50 else 'Light-Snow'
	key = code + ('-n' if is_night else '')
	return _REGIONAL_ICON.get(key, 'Sunny')


CLEAR_CLOUD_CODES = {'CLR', 'SKC', 'FEW', 'SCT'}  # BKN/OVC are real ceilings, the rest read as "Unlimited"


def c_to_f(c):
	return round(c * 9 / 5 + 32) if c is not None else None


def kmh_to_mph(kmh):
	return round(kmh * 0.621371) if kmh is not None else None


def pa_to_inhg(pa):
	return round(pa / 3386.39, 2) if pa is not None else None


def m_to_mi(m):
	return round(m / 1609.34) if m is not None else None


def deg_to_compass(deg):
	if deg is None:
		return 'VAR'
	dirs = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
	return dirs[round(deg / 22.5) % 16]


def heat_index_f(temp_f, rh_pct):
	"""NWS Rothfusz regression, only meaningful (and only applied by
	fetch_hourly_forecast) at temp_f >= 80 -- matches real WS4KP's own
	.like.heat-index threshold, confirmed live via its CSS (color #e00)."""
	t, rh = temp_f, rh_pct
	simple = 0.5 * (t + 61 + (t - 68) * 1.2 + rh * 0.094)
	if (simple + t) / 2 < 80:
		return simple
	hi = (
		-42.379 + 2.04901523 * t + 10.14333127 * rh - 0.22475541 * t * rh - 0.00683783 * t * t
		- 0.05481717 * rh * rh + 0.00122874 * t * t * rh + 0.00085282 * t * rh * rh - 0.00000199 * t * t * rh * rh
	)
	return hi


def wind_chill_f(temp_f, wind_mph):
	"""NWS wind chill formula, only meaningful (and only applied by
	fetch_hourly_forecast) at temp_f <= 50 and wind_mph >= 3 -- matches real
	WS4KP's own .like.wind-chill threshold, confirmed live via its CSS
	(color #8080ff)."""
	v = wind_mph ** 0.16
	return 35.74 + 0.6215 * temp_f - 35.75 * v + 0.4275 * temp_f * v


def feels_like(temp_f, rh_pct, wind_mph):
	"""Returns (value_int, kind) where kind is 'heat-index', 'wind-chill', or
	None (plain temp -- neither threshold applies). Real per-hour feels-like
	data isn't in NWS's hourly periods endpoint at all (only actual temp),
	so this computes it from real temp/humidity/wind using the same
	standard NWS formulas WS4KP's own server presumably does, rather than
	just echoing the actual temp as a placeholder (the previous, cruder
	behavior here)."""
	if temp_f >= 80 and rh_pct is not None:
		return round(heat_index_f(temp_f, rh_pct)), 'heat-index'
	if temp_f <= 50 and wind_mph >= 3:
		return round(wind_chill_f(temp_f, wind_mph)), 'wind-chill'
	return temp_f, None


def format_wind(compass, speed):
	"""Fixed-width compass field so the speed number lines up in a column
	across table rows regardless of whether the compass abbreviation is 1
	char ('S') or 3 ('SSE') -- found live: without padding, Regional
	Observations' wind column visibly zig-zagged row to row."""
	return f'{compass:<3} {speed:>2}'


def _parse_icon_url(icon_url):
	# https://api.weather.gov/icons/land/day/skc?size=medium -- NWS can
	# return a compound URL with two conditions (rare); we always use the
	# first, same as WS4KP.
	path = icon_url.split('?')[0].rstrip('/')
	parts = path.split('/')
	tod, cond = parts[-2], parts[-1]
	if '/' in cond:
		cond = cond.split('/')[0]
	code, _, prob = cond.partition(',')
	probability = int(prob) if prob.isdigit() else 100
	return code, probability, tod == 'night'


def icon_from_nws_url(icon_url):
	if not icon_url:
		return 'No-Data'
	code, probability, is_night = _parse_icon_url(icon_url)
	if code == 'snow':
		return 'Heavy-Snow' if probability > 50 else 'Light-Snow'
	key = code + ('-n' if is_night else '')
	return _CONDITION_ICON.get(key, 'No-Data')


def ceiling_from_layers(layers):
	if not layers:
		return 'Unlimited'
	if all(layer.get('amount') in CLEAR_CLOUD_CODES for layer in layers):
		return 'Unlimited'
	return 'Scattered'


async def _points(client, lat, lon):
	r = await client.get(f'https://api.weather.gov/points/{lat},{lon}', headers=UA, timeout=10)
	r.raise_for_status()
	return r.json()['properties']


_CONDITION_ABBREV = {
	'partly cloudy': 'P Cloudy', 'mostly cloudy': 'M Cloudy', 'mostly clear': 'M Clear',
	'mostly sunny': 'M Sunny', 'partly sunny': 'P Sunny', 'scattered clouds': 'Scattered',
	'overcast': 'Ovrcst', 'thunderstorm': 'T-Storm', 'light rain': 'Lt Rain',
	'heavy rain': 'Hvy Rain', 'light snow': 'Lt Snow',
}


def _abbrev_condition(text):
	"""No abbreviation table was found in WS4KP's own bundle (grepped
	displays.min.js/shared.min.js for one) -- this is our own reasonable
	shortening of common NWS textDescription values to fit the Latest
	Observations table's narrow column, not a byte-for-byte port like the
	icon mapping. Falls back to the first ~9 chars of whatever NWS returns
	for anything not in the table."""
	if not text:
		return '--'
	key = text.strip().lower()
	return _CONDITION_ABBREV.get(key, text[:9])


_AIRPORT_SUFFIX_RE = None


def _clean_station_name(name):
	"""NWS station names are full official names ('Austin-Bergstrom
	International Airport', 'Georgetown, Georgetown Municipal Airport') --
	WS4KP shows short city-only names ('Austin', 'Georgetown'). No mapping
	table was found in WS4KP's own bundle, so this is a heuristic cleanup
	(comma-split, then strip common airport-name suffixes / hyphenated
	airport-name second half), not a byte-for-byte port -- good enough for a
	14-char table column, not guaranteed to match WS4KP's exact text."""
	global _AIRPORT_SUFFIX_RE
	if _AIRPORT_SUFFIX_RE is None:
		_AIRPORT_SUFFIX_RE = re.compile(
			r'\s*[-,].*$|\s+(International|Municipal|Regional|Executive|County)?\s*(Airport|Airpark|Field)\b.*$',
			re.IGNORECASE,
		)
	cleaned = _AIRPORT_SUFFIX_RE.sub('', name).strip()
	return cleaned or name


def _observation_is_usable(obs):
	"""The nearest station's *latest* record is sometimes a stale/incomplete
	stub (temperature present but wind/textDescription null, quality-control
	flagged 'Z' for suspect) -- found live comparing our output against the
	real WS4KP page for the same coordinates, which silently skips such
	stations and uses the next one with real data. Treat a station as usable
	only if the fields we actually display are populated."""
	return (
		obs.get('temperature', {}).get('value') is not None
		and obs.get('windSpeed', {}).get('value') is not None
		and (obs.get('textDescription') or '').strip() != ''
	)


async def fetch_current_conditions(lat, lon):
	async with httpx.AsyncClient(follow_redirects=True) as client:
		props = await _points(client, lat, lon)
		city = props['relativeLocation']['properties']['city']
		state = props['relativeLocation']['properties']['state']

		stations = await client.get(props['observationStations'], headers=UA, timeout=10)
		station_ids = [f['id'] for f in stations.json()['features']]

		obs = None
		for station_url in station_ids[:5]:  # real WS4KP behavior: try nearest few, not the whole list
			obs_resp = await client.get(f'{station_url}/observations/latest', headers=UA, timeout=10)
			if obs_resp.status_code != 200:
				continue
			candidate = obs_resp.json()['properties']
			if _observation_is_usable(candidate):
				obs = candidate
				break
		if obs is None:
			obs = candidate  # every nearby station was incomplete -- use the last one rather than fail outright

	temp_f = c_to_f(obs['temperature']['value'])
	condition = (obs.get('textDescription') or '').strip()
	icon_name = icon_from_nws_url(obs.get('icon'))

	return {
		# Real WS4KP's own 20-char limit for this field (confirmed live
		# against currentweather.mjs's `locationLimit`), not a guessed value.
		'location': f'{city} {state}'[:20],
		'temp': f"{temp_f}°" if temp_f is not None else '--',
		'condition': condition or 'Unknown',
		'icon': icon_name,
		'humidity': f"{round(obs['relativeHumidity']['value'])}%" if obs['relativeHumidity']['value'] is not None else '--',
		'dewpoint': f"{c_to_f(obs['dewpoint']['value'])}°" if obs['dewpoint']['value'] is not None else '--',
		'ceiling': ceiling_from_layers(obs.get('cloudLayers')),
		'visibility': f"{m_to_mi(obs['visibility']['value'])} mi." if obs['visibility']['value'] is not None else '--',
		'pressure': f"{pa_to_inhg(obs['barometricPressure']['value'])}" if obs['barometricPressure']['value'] is not None else '--',
		# Real WS4KP's Current Conditions wind is a single value, not a table
		# column, so it's just "S  8" (2 spaces) -- confirmed live -- not the
		# fixed-width table padding (format_wind) that Latest
		# Observations/Hourly Forecast need for row-to-row alignment.
		'wind': f"{deg_to_compass(obs['windDirection']['value'])}  {kmh_to_mph(obs['windSpeed']['value']) or 0}",
		'heatindex': f"{c_to_f(obs['heatIndex']['value'])}°" if obs.get('heatIndex', {}).get('value') is not None else (f"{temp_f}°" if temp_f is not None else '--'),
	}


async def fetch_hourly_forecast(lat, lon, hours=5):
	"""Returns up to `hours` upcoming periods: hour label, temp, feels-like
	(computed via feels_like() from real temp/humidity/wind -- NWS's hourly
	endpoint has no separate apparent-temp field), wind, icon."""
	async with httpx.AsyncClient(follow_redirects=True) as client:
		props = await _points(client, lat, lon)
		r = await client.get(props['forecastHourly'], headers=UA, timeout=10)
		periods = r.json()['properties']['periods'][:hours]

	out = []
	for p in periods:
		wind_parts = (p.get('windSpeed') or '0 mph').split()
		wind_mph = float(wind_parts[0]) if wind_parts[0].replace('.', '', 1).isdigit() else 0
		rh = p.get('relativeHumidity', {}).get('value')
		like_value, like_kind = feels_like(p['temperature'], rh, wind_mph)
		out.append({
			'hour': p['name'] if p['name'] in ('Now', 'Today', 'Tonight') else _format_hour(p['startTime']),
			'temp': str(p['temperature']),
			'like': str(like_value),
			'like_kind': like_kind,  # 'heat-index' | 'wind-chill' | None -- see screens/hourly_forecast.py for coloring
			'wind': format_wind(p.get('windDirection') or 'VAR', wind_parts[0]),
			'icon': icon_from_nws_url(p.get('icon')),
		})
	return out


def _format_hour(iso_time):
	dt = datetime.fromisoformat(iso_time)
	return dt.strftime('%a %-I %p') if hasattr(dt, 'strftime') else iso_time


def _weekday_abbrev(iso_time):
	return datetime.fromisoformat(iso_time).strftime('%a')


async def fetch_active_alerts(lat, lon):
	"""Real active NWS alerts for this point -- same /alerts/active endpoint
	already used by Ticker (ticker_weather_service.py). Returns {'event':,
	'description':} for the highest-severity alert, or None if nothing
	active -- matches WS4KP's own .scroll.hazard structure (a short event
	name header + the full alert description body), confirmed live against
	the real element. Drawn fresh every render cycle (see main.py), never
	baked into a template."""
	async with httpx.AsyncClient(follow_redirects=True) as client:
		r = await client.get('https://api.weather.gov/alerts/active', params={'point': f'{lat},{lon}'}, headers=UA, timeout=10)
		r.raise_for_status()
		features = r.json().get('features', [])
	if not features:
		return None
	sev_order = {'Extreme': 4, 'Severe': 3, 'Moderate': 2, 'Minor': 1, 'Unknown': 0}
	features.sort(key=lambda f: sev_order.get(f['properties'].get('severity'), 0), reverse=True)
	top = features[0]['properties']
	return {
		'event': top.get('event') or 'Weather Advisory',
		'description': (top.get('description') or top.get('headline') or '').strip(),
	}


# Same curated set of major cities WS4KP ships in data/travelcities.json --
# using just the ones shown in its default (unscrolled) view rather than
# vendoring the full ~100-city file, same simplification precedent as
# Extended Forecast showing 3 of 7 days.
TRAVEL_CITIES = [
	# Expanded from the original 4 to 12 real major US travel-hub cities
	# (found from direct user feedback: "nothing... more slides" -- real
	# WS4KP-style Travel Forecast screens rotate through several pages, not
	# just one) -- see live_stream.py's travel_forecast/_2/_3 wiring, same
	# 3-slides-of-4 pattern already used for extended_forecast/_2.
	{'name': 'Atlanta', 'lat': 33.749, 'lon': -84.388},
	{'name': 'Boston', 'lat': 42.3584, 'lon': -71.0598},
	{'name': 'Chicago', 'lat': 41.9796, 'lon': -87.9045},
	{'name': 'Cleveland', 'lat': 41.4995, 'lon': -81.6954},
	{'name': 'Dallas', 'lat': 32.7767, 'lon': -96.7970},
	{'name': 'Denver', 'lat': 39.7392, 'lon': -104.9903},
	{'name': 'Detroit', 'lat': 42.3314, 'lon': -83.0458},
	{'name': 'Houston', 'lat': 29.7604, 'lon': -95.3698},
	{'name': 'Los Angeles', 'lat': 34.0522, 'lon': -118.2437},
	{'name': 'Miami', 'lat': 25.7617, 'lon': -80.1918},
	{'name': 'New York', 'lat': 40.7128, 'lon': -74.0060},
	{'name': 'Seattle', 'lat': 47.6062, 'lon': -122.3321},
]


async def fetch_travel_forecast(cities=TRAVEL_CITIES):
	"""Tomorrow's (first full day-period's) low/high + icon for each curated
	travel city, matching WS4KP's Travel Forecast screen. Uses the
	'regional-maps' icon set (icon_from_nws_url_regional), not
	'current-conditions' -- a real, visually distinct set WS4KP itself uses
	for exactly this screen."""
	rows = []
	async with httpx.AsyncClient(follow_redirects=True) as client:
		for city in cities:
			try:
				props = await _points(client, city['lat'], city['lon'])
				r = await client.get(props['forecast'], headers=UA, timeout=10)
				periods = r.json()['properties']['periods']
			except (httpx.HTTPError, KeyError, IndexError):
				continue
			day_period = next((p for p in periods if p['isDaytime']), None)
			night_period = next((p for p in periods if not p['isDaytime']), None)
			if not day_period:
				continue
			rows.append({
				'city': city['name'],
				'icon': icon_from_nws_url_regional(day_period.get('icon')),
				'low': str(night_period['temperature']) if night_period else '--',
				'high': str(day_period['temperature']),
			})
	return rows


def _parse_gridpoint_series(values):
	"""NWS raw gridpoint time-series values (e.g. skyCover) encode each
	entry's span as an ISO8601 interval: 'validTime': '<start>/PT<N>H'.
	Returns [(start_dt, end_dt, value), ...] for lookup by hour."""
	out = []
	for v in values:
		start_str, duration = v['validTime'].split('/')
		start = datetime.fromisoformat(start_str)
		hours = int(duration[2:-1]) if duration.startswith('PT') and duration.endswith('H') else 1
		out.append((start, start + timedelta(hours=hours), v['value']))
	return out


def _sample_series(series, dt):
	for start, end, value in series:
		if start <= dt < end:
			return value
	return None


async def fetch_hourly_graph(lat, lon, hours=36):
	"""Temperature/dewpoint/precip-probability (from the periods forecast)
	and cloud-cover (from the raw gridpoint skyCover time series -- not
	present in the periods forecast at all) for the next `hours` hours,
	matching WS4KP's Hourly Graph screen's 4 plotted series."""
	async with httpx.AsyncClient(follow_redirects=True) as client:
		points = await _points(client, lat, lon)
		grid_id, grid_x, grid_y = points['gridId'], points['gridX'], points['gridY']
		hourly_resp = await client.get(points['forecastHourly'], headers=UA, timeout=10)
		periods = hourly_resp.json()['properties']['periods'][:hours]
		grid_resp = await client.get(f'https://api.weather.gov/gridpoints/{grid_id}/{grid_x},{grid_y}', headers=UA, timeout=10)
		sky_cover_series = _parse_gridpoint_series(grid_resp.json()['properties']['skyCover']['values'])

	points_out = []
	for p in periods:
		start = datetime.fromisoformat(p['startTime'])
		cloud = _sample_series(sky_cover_series, start)
		points_out.append({
			'time': start,
			'hour_label': f"{start.strftime('%-I')}{start.strftime('%p')[0]}",  # '9P', '6A' -- matches WS4KP's compact style
			'is_day_boundary': start.hour == 0,
			'day_label': start.strftime('%a'),
			'temp': p['temperature'],
			'dewpoint': c_to_f(p['dewpoint']['value']),
			'precip': p.get('probabilityOfPrecipitation', {}).get('value') or 0,
			'cloud': cloud if cloud is not None else 0,
		})
	return points_out


# Real per-marker on-screen footprint (name label above + temp/icon row
# below the true point), close to what regional_map.render_markers actually
# draws. Confirmed against netbymatt/ws4kp's OWN real algorithm (server/
# scripts/modules/regionalforecast.mjs: makeCityBox uses a 105x50px box in
# ITS 640x282 map) -- not a guessed value, scaled down to our smaller
# 492x280 box by the same ratio (492/640 ~= 0.77).
_MARKER_BOX_W, _MARKER_BOX_H = 80, 50


def _nearby_major_cities(lat, lon, box_size, span_degrees, countries=None):
	"""Every MAJOR_CITIES entry (radar.py's real ~7,000-city US+Canada
	dataset -- crosses country/state lines freely, e.g. Toronto qualifies
	near Buffalo NY, Savannah GA/Jacksonville FL both qualify near St.
	Augustine) that falls within the map's own display box, big-city-tier
	first then nearest-within-tier (radar.tier_rank -- prefers recognizable
	cities, only reaches into smaller-population towns for real gaps bigger
	cities don't fill). Real geographic spacing is enforced later, at
	pixel-box-overlap selection time (see _select_spaced_cities) -- this is
	just the raw candidate pool in that priority order. Returns
	(name, lat, lon, country) tuples -- population only affects ordering
	here, never leaves this function.

	Real bug found from direct user feedback (Buffalo, NY showing only 2
	cities with lots of blank map space): this used to filter candidates
	with the SAME degree half-span on both axes -- a square in degree-
	space -- but box_size is a wide rectangle (~492x280, not square), so
	the map's actual DISPLAYED longitude span is meaningfully wider than
	its latitude span (see radar.lon_span_for_box, already used everywhere
	else for exactly this reason). The old square filter silently excluded
	real candidates sitting well within the visible map area (e.g. Akron,
	OH near Buffalo: only 1.8 degrees of latitude away but 2.64 degrees of
	longitude away, just over the old 2.5-degree threshold on the tight
	axis -- even though the map's real longitude half-span at this box
	size is ~4.4 degrees). Widening the longitude side to match what's
	actually rendered doesn't touch the separate overlap-exclusion step
	below that prevents stacking -- it only stops throwing away real
	candidates before that step ever sees them.

	countries: optional set restricting candidates to specific countries
	(e.g. {'US'}) -- fetch_regional_map_forecast* pass this since Environment
	Canada only has a real current-conditions source wired up so far (see
	environment_canada.py), not forecast data; fetch_regional_map (current
	conditions) passes None (both) now that it does."""
	from renderer.adapters.radar import MAJOR_CITIES, lon_span_for_box, tier_rank  # local import: radar imports nws, avoid a cycle

	half_lat = span_degrees / 2
	half_lon = lon_span_for_box(span_degrees, box_size) / 2
	nearby = [
		(name, city_lat, city_lon, population, country) for name, city_lat, city_lon, population, country in MAJOR_CITIES
		if (countries is None or country in countries)
		and abs(city_lat - lat) < half_lat and abs(city_lon - lon) < half_lon
	]
	nearby.sort(key=lambda c: (tier_rank(c[3]), (c[1] - lat) ** 2 + (c[2] - lon) ** 2))
	return [(name, city_lat, city_lon, country) for name, city_lat, city_lon, _population, country in nearby]


def _project_px(lat, lon, city_lat, city_lon, box_size, span_degrees):
	"""Same lat/lon -> box-pixel projection regional_map.render_markers
	actually draws with (kept in sync manually -- both need the real
	aspect-corrected longitude span, see radar.lon_span_for_box)."""
	from renderer.adapters import radar  # local import: radar imports nws, avoid a cycle

	lon_span = radar.lon_span_for_box(span_degrees, box_size)
	half_lat, half_lon = span_degrees / 2, lon_span / 2
	lon_min, lat_max = lon - half_lon, lat + half_lat
	x = (city_lon - lon_min) / lon_span * box_size[0]
	y = (lat_max - city_lat) / span_degrees * box_size[1]
	return x, y


def _box_for(lat, lon, city_lat, city_lon, box_size, span_degrees):
	x, y = _project_px(lat, lon, city_lat, city_lon, box_size, span_degrees)
	return (x - _MARKER_BOX_W / 2, y - _MARKER_BOX_H / 2, x + _MARKER_BOX_W / 2, y + _MARKER_BOX_H / 2)


def _boxes_overlap(a, b):
	return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def _select_spaced_cities(lat, lon, box_size, span_degrees, seed_boxes=(), countries=None):
	"""Real WS4KP's own city-selection algorithm (confirmed live against
	netbymatt/ws4kp's regionalforecast.mjs), not a guessed "minimum miles"
	rule: candidates are walked NEAREST-FIRST and each one's real on-screen
	pixel bounding box is tested against every already-accepted city's box;
	a city is skipped outright (never even fetched) if its box overlaps.
	Since the box is a fixed PIXEL size but candidates are ranked by real
	distance, this behaves like a variable mile-radius exclusion that gets
	tighter as you zoom in and looser as you zoom out -- exactly the effect
	real WS4KP has, and the reason nearest-first alone (no exclusion, our
	original bug) or a naive fixed-octant spread (an earlier, wrong attempt
	at this same fix) both still let close pairs like Ocala/Daytona Beach
	(~65 miles apart) land on top of each other on screen.

	seed_boxes: pre-accepted boxes (e.g. the target city's own marker, see
	fetch_regional_map) that count toward the overlap test but were never
	themselves candidates from MAJOR_CITIES. countries: see
	_nearby_major_cities.

	Returns ALL non-overlapping (name, lat, lon, country) candidates found
	(not capped to `count`) -- the caller fetches them in this order and
	keeps going past a dead/incomplete station, so a fetch failure never
	re-admits a city that was already excluded for overlapping a DIFFERENT,
	still-good neighbor."""
	accepted = list(seed_boxes)
	result = []
	for name, city_lat, city_lon, country in _nearby_major_cities(lat, lon, box_size, span_degrees, countries=countries):
		box = _box_for(lat, lon, city_lat, city_lon, box_size, span_degrees)
		if any(_boxes_overlap(box, other) for other in accepted):
			continue
		accepted.append(box)
		result.append((name, city_lat, city_lon, country))
	return result


async def _fetch_target_marker(client, lat, lon, target_name, daytime=None):
	"""The channel's OWN city, as a marker -- real WS4KP's curated city
	databases (even the current, larger 367-city netbymatt/ws4kp list;
	checked directly) don't guarantee the target city itself is in them
	either, e.g. St. Augustine FL is in neither list. Rather than leave a
	regional map showing everywhere EXCEPT the place the channel is actually
	for (found from direct user feedback), always fetch and include the
	target's own point directly, same data shape as a MAJOR_CITIES entry so
	it merges into the same rows list. Returns None (skip, not fake) if this
	point's own observation/forecast isn't usable -- daytime=None means
	current conditions, True/False means the day/night forecast period."""
	try:
		points = await _points(client, lat, lon)
		if daytime is None:
			stations_resp = await client.get(points['observationStations'], headers=UA, timeout=10)
			station_url = stations_resp.json()['features'][0]['id']
			obs_resp = await client.get(f'{station_url}/observations/latest', headers=UA, timeout=10)
			obs = obs_resp.json()['properties']
			if not _observation_is_usable(obs):
				return None
			return {'name': target_name, 'lat': lat, 'lon': lon,
					'temp': c_to_f(obs['temperature']['value']),
					'icon': icon_from_nws_url_regional(obs.get('icon'))}
		r = await client.get(points['forecast'], headers=UA, timeout=10)
		periods = r.json()['properties']['periods']
		period = next((p for p in periods if p['isDaytime'] == daytime), None)
		if not period:
			return None
		return {'name': target_name, 'lat': lat, 'lon': lon,
				'temp': period['temperature'],
				'icon': icon_from_nws_url_regional(period.get('icon'))}
	except (httpx.HTTPError, KeyError, IndexError):
		return None


async def fetch_regional_map(lat, lon, box_size, span_degrees=5.0, count=8, target_name=None):
	"""Nearby MAJOR cities' current conditions WITH real lat/lon, for the
	Regional Observations map screen (WS4KP's #regional-forecast-html --
	yes, the checkbox is misleadingly named 'regional-forecast', the
	on-screen title is 'Regional Observations'; confirmed live, it also
	sub-cycles into a next-day 'Forecast for <Day>' page -- see
	fetch_regional_map_forecast). Uses radar.MAJOR_CITIES (the same curated
	list already built for Radar's city labels), spaced apart via
	_select_spaced_cities (real WS4KP's own pixel-box-overlap algorithm),
	not literally-nearest NWS weather stations -- those cluster tightly
	around any given point (all within a few miles of each other), which is
	why an earlier version of this using nearest-stations looked cramped/
	overlapping on a map this small. target_name, if given, always includes
	the channel's own city as the first marker (see _fetch_target_marker).

	The target's own map SLOT is always reserved (seed_boxes below), even
	if target_name is unset or its own data fetch fails -- found from
	direct user feedback that the current/day-forecast/night-forecast map
	screens were showing visibly DIFFERENT sets of curated cities, and the
	target city itself would sometimes vanish entirely. Root cause: each of
	the 3 screens fetches the target's data independently, and a transient
	failure on just ONE of them used to also un-reserve its map position,
	letting a DIFFERENT curated city fill that slot -- so a single flaky
	fetch for the target changed which OTHER cities got picked too, on
	just that one screen. Reserving the slot unconditionally (target has a
	real lat/lon regardless of whether its data loaded) keeps the curated
	city set identical across all 3 screens; only the target's own marker
	is what disappears on a bad fetch, same as it always could before."""
	rows = []
	seed_boxes = [_box_for(lat, lon, lat, lon, box_size, span_degrees)] if target_name else []
	async with httpx.AsyncClient(follow_redirects=True) as client:
		if target_name:
			target = await _fetch_target_marker(client, lat, lon, target_name)
			if target is not None:
				rows.append(target)

		for name, city_lat, city_lon, country in _select_spaced_cities(lat, lon, box_size, span_degrees, seed_boxes):
			if len(rows) >= count:
				break
			if country == 'CA':
				# Real second data source (see environment_canada.py) --
				# NWS has zero Canada coverage, so this candidate would
				# otherwise always silently fail below and waste its map
				# slot (that was this function's OWN bug before Environment
				# Canada support existed). Same row shape as the US branch;
				# render_markers doesn't need to know which source it came
				# from.
				obs = await environment_canada.fetch_current_conditions(client, city_lat, city_lon)
				if obs is None:
					continue
				rows.append({'name': name, 'lat': city_lat, 'lon': city_lon, 'temp': obs['temp'], 'icon': obs['icon']})
				continue
			try:
				points = await _points(client, city_lat, city_lon)
				stations_resp = await client.get(points['observationStations'], headers=UA, timeout=10)
				candidate_stations = stations_resp.json()['features'][:3]
			except (httpx.HTTPError, KeyError, IndexError):
				continue
			# Try a few candidate stations, not just the single nearest one --
			# found live: this only ever tried features[0], so a city whose
			# nearest station's *latest* reading happened to be stale/
			# incomplete (see _observation_is_usable) got dropped from this
			# screen entirely, even though a second-nearest station a few
			# miles away had perfectly good current data. The day/night
			# forecast map variants don't have this problem since forecast
			# grid-point data doesn't depend on any one station's live
			# reading -- this is why "current conditions" map consistently
			# showed fewer cities than "the following" (day/night) maps.
			obs = None
			for station in candidate_stations:
				try:
					station_url = station['id']
					obs_resp = await client.get(f'{station_url}/observations/latest', headers=UA, timeout=10)
					candidate_obs = obs_resp.json()['properties']
				except (httpx.HTTPError, KeyError, IndexError):
					continue
				if _observation_is_usable(candidate_obs):
					obs = candidate_obs
					break
			if obs is None:
				continue
			rows.append({
				'name': name,
				'lat': city_lat,
				'lon': city_lon,
				'temp': c_to_f(obs['temperature']['value']),
				'icon': icon_from_nws_url_regional(obs.get('icon')),
			})
	return rows


async def _fetch_regional_map_forecast_periods(lat, lon, box_size, span_degrees, count, daytime, target_name=None):
	"""The target's map slot is reserved unconditionally (seed_boxes), same
	reasoning as fetch_regional_map's own docstring -- keeps the curated
	city set identical across the current/day/night map screens even when
	the target's own data fetch fails on just one of them.

	Both countries now (see environment_canada.fetch_forecast_period) --
	Environment Canada's citypageweather-realtime collection has a real
	multi-day forecast, not just current conditions, so a Canadian
	candidate here is genuinely fetchable now, same as fetch_regional_map."""
	rows = []
	seed_boxes = [_box_for(lat, lon, lat, lon, box_size, span_degrees)] if target_name else []
	async with httpx.AsyncClient(follow_redirects=True) as client:
		if target_name:
			target = await _fetch_target_marker(client, lat, lon, target_name, daytime=daytime)
			if target is not None:
				rows.append(target)

		for name, city_lat, city_lon, country in _select_spaced_cities(lat, lon, box_size, span_degrees, seed_boxes):
			if len(rows) >= count:
				break
			if country == 'CA':
				obs = await environment_canada.fetch_forecast_period(client, city_lat, city_lon, daytime)
				if obs is None:
					continue
				rows.append({'name': name, 'lat': city_lat, 'lon': city_lon, 'temp': obs['temp'], 'icon': obs['icon']})
				continue
			try:
				points = await _points(client, city_lat, city_lon)
				r = await client.get(points['forecast'], headers=UA, timeout=10)
				periods = r.json()['properties']['periods']
			except (httpx.HTTPError, KeyError, IndexError):
				continue
			period = next((p for p in periods if p['isDaytime'] == daytime), None)
			if not period:
				continue
			rows.append({
				'name': name,
				'lat': city_lat,
				'lon': city_lon,
				'temp': period['temperature'],
				'icon': icon_from_nws_url_regional(period.get('icon')),
			})
	return rows


async def fetch_regional_map_forecast(lat, lon, box_size, span_degrees=5.0, count=8, target_name=None):
	"""Tomorrow's day forecast (high temp + icon) for the same spaced-city
	set fetch_regional_map uses -- matches WS4KP+'s real 'Forecast for
	<Day>' sub-page of the same Regional Observations screen."""
	return await _fetch_regional_map_forecast_periods(lat, lon, box_size, span_degrees, count, daytime=True, target_name=target_name)


async def fetch_regional_map_forecast_night(lat, lon, box_size, span_degrees=5.0, count=8, target_name=None):
	"""Tomorrow NIGHT's forecast (low temp + icon) -- the companion 'Forecast
	for <Day> Night' sub-page real WeatherStar 4000+ shows right after the
	day version (confirmed live against vbguyny/ws4kp's ShowRegionalMap:
	it renders a TomorrowForecast1 (day) AND a separate TomorrowForecast2
	(night) map, not just one). We only ever built the day half."""
	return await _fetch_regional_map_forecast_periods(lat, lon, box_size, span_degrees, count, daytime=False, target_name=target_name)


async def fetch_regional_observations(lat, lon, count=7):
	"""Nearest `count` stations' current conditions, matching WS4KP's Latest
	Observations table (location name, temp, heat-index/wind-chill "like"
	value, abbreviated condition, wind). Skips stations with incomplete
	data (same reasoning as _observation_is_usable in
	fetch_current_conditions) rather than showing blank/garbage rows."""
	async with httpx.AsyncClient(follow_redirects=True) as client:
		props = await _points(client, lat, lon)
		stations_resp = await client.get(props['observationStations'], headers=UA, timeout=10)
		features = stations_resp.json()['features'][:count * 2]  # over-fetch to skip incomplete ones

		rows = []
		seen_names = set()
		for feature in features:
			if len(rows) >= count:
				break
			station_url = feature['id']
			name = feature['properties'].get('name', 'Unknown')
			cleaned_name = _clean_station_name(name)[:14]
			if cleaned_name in seen_names:
				# _clean_station_name strips everything after a comma/hyphen
				# plus airport suffixes -- multiple distinct real stations
				# near the same metro (e.g. "Austin-Bergstrom International
				# Airport" and "Austin, Austin Executive Airport") can both
				# clean down to the identical display name. Found live: this
				# showed as an outright duplicate row on-screen. Since
				# `features` is already nearest-first, the first station for
				# a given cleaned name wins and later ones for the same name
				# are skipped -- same effect as picking the nearest, just
				# without needing a second distance comparison here.
				continue
			obs_resp = await client.get(f'{station_url}/observations/latest', headers=UA, timeout=10)
			if obs_resp.status_code != 200:
				continue
			obs = obs_resp.json()['properties']
			if not _observation_is_usable(obs):
				continue
			temp_f = c_to_f(obs['temperature']['value'])
			heat_index = obs.get('heatIndex', {}).get('value')
			wind_chill = obs.get('windChill', {}).get('value')
			like = f'{c_to_f(heat_index)}°' if heat_index is not None else (f'{c_to_f(wind_chill)}°' if wind_chill is not None else '')
			seen_names.add(cleaned_name)
			rows.append({
				# Matches real WS4KP's own 14-char location limit for this
				# screen (confirmed live against latestobservations.mjs).
				'location': cleaned_name,
				'temp': f'{temp_f}°' if temp_f is not None else '--',
				'like': like,
				'weather': _abbrev_condition(obs.get('textDescription')),
				'wind': format_wind(deg_to_compass(obs['windDirection']['value']), kmh_to_mph(obs['windSpeed']['value']) or 0),
			})
	return rows


async def fetch_local_forecast(lat, lon):
	"""Real WS4KP's Local Forecast screen vertically auto-scrolls through
	EVERY period's full detailedForecast text (confirmed live: each `.forecast`
	div is its own period, animated via a translated `.forecasts` container).
	Our architecture holds one static image per top-level screen instead of
	sub-scrolling within it (same tradeoff as Extended Forecast showing 3 of 7
	days) -- shows the nearest/current period, which is also the one a viewer
	glancing at the channel cares about most."""
	async with httpx.AsyncClient(follow_redirects=True) as client:
		props = await _points(client, lat, lon)
		r = await client.get(props['forecast'], headers=UA, timeout=10)
		periods = r.json()['properties']['periods']
	first = periods[0]
	return {'period_name': first['name'], 'text': first.get('detailedForecast', '')}


async def fetch_extended_forecast(lat, lon, days=3):
	"""Returns `days` day/night pairs collapsed into single day entries
	(lo from the night period, hi from the day period) -- matches WS4KP's
	own Extended Forecast column shape."""
	async with httpx.AsyncClient(follow_redirects=True) as client:
		props = await _points(client, lat, lon)
		r = await client.get(props['forecast'], headers=UA, timeout=10)
		periods = r.json()['properties']['periods']

	out = []
	i = 0
	while i < len(periods) and len(out) < days:
		day_period = periods[i] if periods[i]['isDaytime'] else None
		night_period = periods[i + 1] if i + 1 < len(periods) and not periods[i + 1]['isDaytime'] else None
		if day_period is None and periods[i]['isDaytime'] is False:
			# forecast starts with a night period (e.g. late-day fetch) -- pair
			# it with the following day period instead
			night_period = periods[i]
			day_period = periods[i + 1] if i + 1 < len(periods) else None
			i += 1
		# NWS's first period is often named "Today"/"This Afternoon" rather
		# than a weekday -- name[:3] truncated that to "Thi", not a real
		# day abbreviation. Compute the weekday from startTime instead, which
		# is reliable regardless of how NWS labels the period.
		ref_period = day_period or night_period
		day_label = _weekday_abbrev(ref_period['startTime']) if ref_period else '--'
		out.append({
			'date': day_label,
			'icon': icon_from_nws_url((day_period or night_period).get('icon')),
			# No char-truncation here -- screens/extended_forecast.py wraps
			# this across up to 3 lines now instead of drawing one line and
			# clipping it (found from direct user feedback: single-line text
			# was visibly cut off mid-word for longer real forecasts like
			# "Chance Showers And Thunderstorms").
			'condition': (day_period or night_period).get('shortForecast', ''),
			'lo': str(night_period['temperature']) if night_period else '--',
			'hi': str(day_period['temperature']) if day_period else '--',
		})
		i += 2
	return out
