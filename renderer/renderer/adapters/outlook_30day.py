"""
30-Day Outlook adapter -- NOAA CPC's real Monthly Temperature/Precipitation
Outlook, US-only (Climate Prediction Center only issues US outlooks).
CPC itself only publishes this as GIS polygon data (shapefile/KMZ), no
simple point-lookup JSON API -- but NOAA's own ArcGIS REST hosting
(mapservices.weather.noaa.gov) serves the same real polygons through a
standard Esri FeatureServer query endpoint that supports server-side
point-in-polygon queries directly, so no shapefile parsing or client-side
geometry work is needed here. Verified live against a real point (St.
Augustine, FL): returned "Above, 40%" for Sept 2026 temperature.

Real WS4KP+ ('WeatherStar 4000+', vbguyny/ws4kp) titles this screen
"Almanac" / "Outlook" (confirmed live against its own twc3.js
PopulateOutlook function) -- not to be confused with our own SPC Outlook
screen (adapters/spc.py), which is a completely different NOAA product
(severe-weather convective outlook, days not months).
"""
import httpx

UA = {'User-Agent': 'classic4kast (self-hosted weather renderer, personal use)'}

_TEMP_URL = 'https://mapservices.weather.noaa.gov/vector/rest/services/outlooks/cpc_mthly_temp_outlk/MapServer/0/query'
_PRECIP_URL = 'https://mapservices.weather.noaa.gov/vector/rest/services/outlooks/cpc_mthly_precip_outlk/MapServer/0/query'

_CAT_LABELS = {'Above': 'Above Normal', 'Below': 'Below Normal', 'Normal': 'Near Normal', 'EC': 'Equal Chances'}


async def _query(client, url, lat, lon):
	r = await client.get(url, headers=UA, timeout=15, params={
		'geometry': f'{{"x":{lon},"y":{lat},"spatialReference":{{"wkid":4326}}}}',
		'geometryType': 'esriGeometryPoint',
		'inSR': '4326',
		'spatialRel': 'esriSpatialRelIntersects',
		'outFields': 'cat,prob,valid_seas',
		'returnGeometry': 'false',
		'f': 'json',
	})
	r.raise_for_status()
	features = r.json().get('features', [])
	if not features:
		return None
	return features[0]['attributes']


async def fetch_30day_outlook(lat, lon):
	"""Returns {'valid_period', 'temperature', 'temperature_prob',
	'precipitation', 'precipitation_prob'} or None if this point falls
	outside CPC's US-only coverage (e.g. a non-US channel -- gated by
	country at the call site same as every other NWS-only screen, but this
	is a real belt-and-suspenders check since the service itself will
	legitimately return no feature for a point outside CONUS/AK/HI)."""
	async with httpx.AsyncClient(follow_redirects=True) as client:
		temp_attrs = await _query(client, _TEMP_URL, lat, lon)
		precip_attrs = await _query(client, _PRECIP_URL, lat, lon)

	if not temp_attrs and not precip_attrs:
		return None

	result = {'valid_period': (temp_attrs or precip_attrs)['valid_seas']}
	if temp_attrs:
		result['temperature'] = _CAT_LABELS.get(temp_attrs['cat'], temp_attrs['cat'])
		result['temperature_prob'] = round(temp_attrs['prob'])
	else:
		result['temperature'] = None
		result['temperature_prob'] = None
	if precip_attrs:
		result['precipitation'] = _CAT_LABELS.get(precip_attrs['cat'], precip_attrs['cat'])
		result['precipitation_prob'] = round(precip_attrs['prob'])
	else:
		result['precipitation'] = None
		result['precipitation_prob'] = None
	return result
