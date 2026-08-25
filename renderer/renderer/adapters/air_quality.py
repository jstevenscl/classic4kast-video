"""
Air Quality adapter -- Open-Meteo's free, keyless Air Quality API
(air-quality-api.open-meteo.com), same choice already made for
adapters/open_meteo.py's international weather coverage: no API key,
works for any lat/lon worldwide (unlike AirNow, the "official" US source,
which requires a registered key). Returns the real US EPA AQI scale
regardless of country, since that's the scale WS4KP+'s own Air Quality
screen displays.
"""
import httpx

UA = {'User-Agent': 'classic4kast (self-hosted weather renderer, personal use)'}

AIR_QUALITY_URL = 'https://air-quality-api.open-meteo.com/v1/air-quality'

# Real EPA US AQI breakpoints/categories/colors -- not guessed, matches
# https://www.airnow.gov/aqi/aqi-basics/ exactly.
_CATEGORIES = [
	(50, 'Good', (0, 228, 0)),
	(100, 'Moderate', (255, 255, 0)),
	(150, 'Unhealthy for Sensitive Groups', (255, 126, 0)),
	(200, 'Unhealthy', (255, 0, 0)),
	(300, 'Very Unhealthy', (143, 63, 151)),
	(float('inf'), 'Hazardous', (126, 0, 35)),
]


def _category(aqi):
	for threshold, name, color in _CATEGORIES:
		if aqi <= threshold:
			return name, color
	return _CATEGORIES[-1][1], _CATEGORIES[-1][2]


async def fetch_air_quality(lat, lon):
	"""Current US AQI (overall + the pollutant driving it) for lat/lon."""
	async with httpx.AsyncClient(follow_redirects=True) as client:
		r = await client.get(AIR_QUALITY_URL, headers=UA, timeout=15, params={
			'latitude': lat, 'longitude': lon,
			'current': 'us_aqi,us_aqi_pm2_5,us_aqi_pm10,us_aqi_ozone',
		})
		r.raise_for_status()
		current = r.json()['current']

	aqi = current.get('us_aqi')
	if aqi is None:
		return None

	pollutants = {
		'PM2.5': current.get('us_aqi_pm2_5'),
		'PM10': current.get('us_aqi_pm10'),
		'Ozone': current.get('us_aqi_ozone'),
	}
	driver = max((p for p in pollutants.items() if p[1] is not None), key=lambda p: p[1], default=(None, None))
	name, color = _category(aqi)
	return {'aqi': round(aqi), 'category': name, 'color': color, 'driver': driver[0]}
