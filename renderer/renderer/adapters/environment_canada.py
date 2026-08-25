"""Environment Canada (MSC GeoMet, api.weather.gc.ca) adapter -- the
Canada-side counterpart to nws.py, used ONLY for regional-map markers whose
candidate city is in Canada (see nws._nearby_major_cities' country param
and this module's callers in nws.fetch_regional_map /
_fetch_regional_map_forecast_periods). NWS (api.weather.gov) has zero
coverage of Canada (confirmed live: any Canadian lat/lon 404s there) --
this is a real, tested second data source, called in addition to NWS (not
instead of it), which is what makes real Canadian weather markers on those
screens possible instead of just radar labels.

Confirmed live: the 'citypageweather-realtime' OGC API Features collection
supports a plain bbox spatial query (no need to hand-curate Canadian
station/site codes the way real WS4KP's city databases do for the US) --
https://api.weather.gc.ca/collections/citypageweather-realtime/items?bbox=...
returns BOTH real-time current conditions AND a multi-day forecast (a
`forecasts` array: today-day, today-night, tomorrow-day, tomorrow-night,
...) for the nearest citypage station, including a real English condition
summary per period (e.g. "A mix of sun and cloud") -- a genuinely
comparable source to NWS's own points->stations->observations/forecast
flow, not a lesser substitute.

Icon selection is keyword-matched against that real condition text rather
than trusting weather.gc.ca's own numeric iconCode -- confirmed live the
numeric code alone doesn't reliably distinguish day/night or forecast
intensity without a separately-sourced legend, whereas the actual English
text ("A mix of sun and cloud", "Chance of flurries", ...) is unambiguous
and directly matches phrasing this module can grep for. Not exhaustive --
falls back to a neutral Sunny/Clear default for phrasing it doesn't
recognize -- but covers the common real cases (checked against several
live Ontario cities' actual forecast text while building this)."""
import httpx

_BASE_URL = 'https://api.weather.gc.ca/collections/citypageweather-realtime/items'
# Generous enough to reliably catch a nearby real citypage station without
# pulling in one from a genuinely different city.
_BBOX_DEGREES = 0.5


def _icon_from_summary(text, is_night):
	t = (text or '').lower()

	def pick(day_icon, night_icon=None):
		return (night_icon or day_icon) if is_night else day_icon

	if 'thunderstorm' in t:
		return pick('Thunderstorm')
	if 'freezing rain' in t:
		return 'Freezing-Rain-1992'
	if 'ice pellet' in t or 'sleet' in t:
		return 'Sleet'
	if 'heavy snow' in t or 'snowfall' in t:
		return 'Heavy-Snow-1994'
	if 'rain or snow' in t or 'snow or rain' in t or 'rain and snow' in t or 'wet flurries' in t:
		return 'Rain-Snow-1992'
	if 'flurries' in t or 'snow' in t:
		return 'Light-Snow'
	if 'shower' in t:
		return pick('Scattered-Showers-1994', 'Scattered-Showers-Night-1994')
	if 'rain' in t or 'drizzle' in t:
		return 'Rain-1992'
	if 'fog' in t:
		return 'Fog'
	if 'haze' in t or 'smoke' in t:
		return 'Haze'
	if 'blowing snow' in t or 'blizzard' in t:
		return 'Blowing-Snow'
	if 'overcast' in t or ('cloudy' in t and 'partly' not in t and 'mostly' not in t and 'periods' not in t):
		return 'Cloudy'
	if 'mostly cloudy' in t or 'increasing cloud' in t or 'cloudy periods' in t:
		return 'Mostly-Cloudy-1994'
	if 'partly' in t or 'mix of sun' in t or 'sunny periods' in t or 'mainly sunny' in t or 'mainly clear' in t or 'a few clouds' in t:
		return pick('Partly-Cloudy', 'Partly-Cloudy-Night')
	return pick('Sunny', 'Clear-1992')


async def _fetch_citypage(client, lat, lon):
	half = _BBOX_DEGREES
	bbox = f'{lon - half},{lat - half},{lon + half},{lat + half}'
	try:
		r = await client.get(_BASE_URL, params={'bbox': bbox, 'limit': 1, 'f': 'json'}, timeout=10)
		r.raise_for_status()
		features = r.json().get('features', [])
		return features[0]['properties'] if features else None
	except (httpx.HTTPError, ValueError, KeyError, IndexError):
		return None


async def fetch_current_conditions(client, lat, lon):
	"""Returns {'temp': F, 'icon': name} from the nearest citypage
	station's real-time current conditions, or None if unreachable/
	unusable. Always renders with DAY-variant icons -- unlike the forecast
	fetch below, current conditions has no `daytime` signal passed in from
	the caller (nws.fetch_regional_map doesn't have one either, matching
	its own target-marker/current-conditions calls), so this is a known,
	deliberate simplification, not an oversight."""
	props = await _fetch_citypage(client, lat, lon)
	if not props:
		return None
	try:
		temp_c = props['currentConditions']['temperature']['value']['en']
		condition_text = props['currentConditions'].get('condition', {}).get('en', '')
	except (KeyError, TypeError):
		return None
	if temp_c is None:
		return None
	return {'temp': round(temp_c * 9 / 5 + 32), 'icon': _icon_from_summary(condition_text, is_night=False)}


async def fetch_forecast_period(client, lat, lon, daytime):
	"""Returns {'temp': F, 'icon': name} for TOMORROW's day (daytime=True)
	or night (daytime=False) period, matching nws._fetch_regional_map_
	forecast_periods' own "tomorrow" semantics. The forecasts array is
	chronological starting from the current today/tonight period
	(index 0/1), so tomorrow's matching period is normally index 2 (day)
	or 3 (night) -- guarded by a name-based skip-today search instead of a
	hardcoded index, since a query made very late at night can return a
	list that already starts at "Tonight" (index 0) with no "Today" ahead
	of it, which would shift everything else by one."""
	props = await _fetch_citypage(client, lat, lon)
	if not props:
		return None
	try:
		forecasts = props['forecastGroup']['forecasts']
	except (KeyError, TypeError):
		return None

	seen_today = False
	for period in forecasts:
		name = (period.get('period', {}).get('textForecastName', {}).get('en') or '').lower()
		is_today_period = name in ('today', 'tonight')
		if is_today_period:
			seen_today = True
			continue
		if not seen_today:
			# Query happened to start mid-list (e.g. no "Today" ahead) --
			# treat the very first period we see as "today" too so the
			# NEXT one is genuinely tomorrow, matching normal behavior.
			seen_today = True
			continue
		is_night = 'night' in name
		if is_night != (not daytime):
			continue
		try:
			temp_c = period['temperatures']['temperature'][0]['value']['en']
			condition_text = period['abbreviatedForecast']['textSummary']['en']
		except (KeyError, IndexError, TypeError):
			return None
		return {'temp': round(temp_c * 9 / 5 + 32), 'icon': _icon_from_summary(condition_text, is_night=is_night)}
	return None
