"""
Environment Canada adapter (api.weather.gc.ca, citypageweather-realtime
collection). Reuses the same endpoint EDM's Ticker feature already uses for
Canadian weather alerts (backend/app/services/ticker_weather_service.py) --
confirmed live it also returns current conditions, hourly forecast, and
daily forecast in ONE response (cheaper than NWS's 3-endpoint chain).

Also reuses Ticker's existing 844-city ca_city_names.json for city ID
lookup (backend/app/data/ca_city_names.json) rather than a new geocoding
step -- see build_city_id_lookup().

Icon selection: matches on EC's own English condition text rather than its
numeric iconCode -- no independently-verifiable public legend for that
scheme was found. Day/night determined via a real sun-elevation
calculation (astral), not a guessed code parity. Known v1 gap: EC's
condition-text vocabulary is large and this list isn't exhaustive; unmatched
conditions fall back to 'No-Data' rather than guessing.
"""
import json
import os
from datetime import datetime, timezone

import httpx
from astral import LocationInfo
from astral.sun import sun

EC_BASE = 'https://api.weather.gc.ca/collections/citypageweather-realtime/items'
HEADERS = {'Accept': 'application/json'}

_CA_CITY_NAMES_PATH = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'backend', 'app', 'data', 'ca_city_names.json')

_CONDITION_ICON = {
	'sunny': 'Sunny', 'clear': 'Sunny', 'mainly sunny': 'Sunny', 'mainly clear': 'Sunny',
	'a few clouds': 'Mostly-Clear', 'partly cloudy': 'Partly-Cloudy', 'mostly cloudy': 'Cloudy', 'cloudy': 'Cloudy',
	'overcast': 'Cloudy', 'increasing cloudiness': 'Cloudy', 'decreasing cloudiness': 'Partly-Cloudy',
	'fog': 'Fog', 'fog patches': 'Fog', 'haze': 'Fog', 'smoke': 'Smoke',
	'rain': 'Rain', 'light rain': 'Rain', 'heavy rain': 'Rain', 'rain showers': 'Shower', 'showers': 'Shower',
	'chance of showers': 'Shower', 'drizzle': 'Rain', 'freezing rain': 'Freezing-Rain', 'freezing drizzle': 'Freezing-Rain',
	'snow': 'Light-Snow', 'light snow': 'Light-Snow', 'heavy snow': 'Heavy-Snow', 'snow showers': 'Light-Snow',
	'flurries': 'Light-Snow', 'blowing snow': 'Blowing-Snow', 'blizzard': 'Blowing-Snow',
	'ice pellets': 'Sleet', 'rain and snow': 'Rain-Snow', 'rain or snow': 'Rain-Snow',
	'thunderstorms': 'Thunderstorm', 'thunderstorm': 'Thunderstorm', 'severe thunderstorm': 'Thunderstorm',
	'risk of thunderstorms': 'Scattered-Thunderstorms-Day', 'windy': 'Windy', 'wind': 'Windy',
}
_NIGHT_ICON = {'Sunny': 'Clear', 'Mostly-Clear': 'Mostly-Clear', 'Partly-Cloudy': 'Partly-Cloudy'}

_city_name_cache = None


def build_city_id_lookup():
	"""Loads Ticker's existing ca_city_names.json once. Returns {city_id: {'en':.., 'fr':..}}."""
	global _city_name_cache
	if _city_name_cache is None:
		try:
			with open(_CA_CITY_NAMES_PATH, encoding='utf-8') as f:
				_city_name_cache = json.load(f)
		except FileNotFoundError:
			_city_name_cache = {}
	return _city_name_cache


def kpa_to_inhg(kpa):
	return round(kpa * 0.2953, 2) if kpa is not None else None


def km_to_mi(km):
	return round(km * 0.621371) if km is not None else None


def is_night(lat, lon):
	loc = LocationInfo(latitude=lat, longitude=lon)
	now = datetime.now(timezone.utc)
	s = sun(loc.observer, date=now.date(), tzinfo=timezone.utc)
	return not (s['sunrise'] <= now <= s['sunset'])


def icon_from_condition(condition_text, lat, lon):
	base = _CONDITION_ICON.get(condition_text.strip().lower(), 'No-Data')
	if base != 'No-Data' and is_night(lat, lon):
		return _NIGHT_ICON.get(base, base)
	return base


async def _fetch(city_id):
	async with httpx.AsyncClient(follow_redirects=True) as client:
		r = await client.get(f'{EC_BASE}/{city_id}', headers=HEADERS, timeout=15)
		r.raise_for_status()
		return r.json()['properties']


def _fmt_temp(temp_c, units):
	if temp_c is None:
		return '--'
	return f"{round(temp_c * 9 / 5 + 32)}°" if units == 'imperial' else f"{round(temp_c)}°"


def _fmt_wind(dir_text, speed_kmh, units):
	speed = (km_to_mi(speed_kmh) if units == 'imperial' else round(speed_kmh)) if speed_kmh is not None else 0
	return f"{dir_text or 'VAR'}  {speed}"


async def fetch_current_conditions(city_id, lat, lon, units='imperial'):
	props = await _fetch(city_id)
	cc = props['currentConditions']

	temp_c = cc.get('temperature', {}).get('value', {}).get('en')
	condition = cc.get('condition', {}).get('en', '') or ''
	humidity = cc.get('relativeHumidity', {}).get('value', {}).get('en')
	dewpoint_c = cc.get('dewpoint', {}).get('value', {}).get('en')
	pressure_kpa = cc.get('pressure', {}).get('value', {}).get('en')
	wind_speed_kmh = cc.get('wind', {}).get('speed', {}).get('value', {}).get('en')
	wind_dir = cc.get('wind', {}).get('direction', {}).get('value', {}).get('en')
	pressure = f"{kpa_to_inhg(pressure_kpa)}" if units == 'imperial' \
		else (f"{round(pressure_kpa * 10)} hPa" if pressure_kpa is not None else '--')

	return {
		'location': props['name']['en'][:20],  # matches real WS4KP's 20-char location limit
		'temp': _fmt_temp(temp_c, units),
		'condition': condition or 'Unknown',
		'icon': icon_from_condition(condition, lat, lon),
		'humidity': f"{humidity}%" if humidity is not None else '--',
		'dewpoint': _fmt_temp(dewpoint_c, units),
		'ceiling': 'Unlimited',  # not present in this endpoint
		'visibility': '10 mi.' if units == 'imperial' else '16 km',  # not present in this endpoint -- placeholder, needs a separate source if this matters
		'pressure': pressure if pressure_kpa is not None else '--',
		'wind': _fmt_wind(wind_dir, wind_speed_kmh, units),
		'heatindex': _fmt_temp(temp_c, units),
	}


async def fetch_hourly_forecast(city_id, lat, lon, hours=5, units='imperial'):
	props = await _fetch(city_id)
	entries = props.get('hourlyForecastGroup', {}).get('hourlyForecasts', [])[:hours]

	out = []
	for e in entries:
		temp_c = e.get('temperature', {}).get('value', {}).get('en')
		condition = e.get('condition', {}).get('en', '') or ''
		wind_kmh = e.get('wind', {}).get('speed', {}).get('value', {}).get('en')
		wind_dir = e.get('wind', {}).get('direction', {}).get('value', {}).get('en')
		ts = e.get('timestamp')
		hour_label = _format_hour(ts) if ts else '--'
		temp_str = _fmt_temp(temp_c, units).rstrip('°')
		out.append({
			'hour': hour_label,
			'temp': temp_str,
			'like': temp_str,
			'wind': _fmt_wind(wind_dir, wind_kmh, units),
			'icon': icon_from_condition(condition, lat, lon),
		})
	return out


def _format_hour(iso_time):
	dt = datetime.fromisoformat(iso_time.replace('Z', '+00:00'))
	return dt.strftime('%a %-I %p')


async def fetch_extended_forecast(city_id, lat, lon, days=3, units='imperial'):
	props = await _fetch(city_id)
	forecasts = props.get('forecastGroup', {}).get('forecasts', [])

	out = []
	for f in forecasts:
		if len(out) >= days:
			break
		name = f.get('period', {}).get('textForecastName', {}).get('en', '')
		if 'night' in name.lower():
			continue  # daily columns only need the daytime entries; night low is folded in below
		temps = f.get('temperatures', {}).get('temperature', [])
		hi = next((t['value']['en'] for t in temps if t.get('class', {}).get('en') == 'high'), None)
		condition = f.get('abbreviatedForecast', {}).get('textSummary', {}).get('en') \
			or f.get('textSummary', '') or ''
		icon_val = f.get('abbreviatedForecast', {}).get('iconCode', {}).get('value')
		out.append({
			'date': name[:3] if name else '--',
			'icon': icon_from_condition(condition or 'partly cloudy', lat, lon) if condition else 'No-Data',
			'condition': condition or '',  # screens/extended_forecast.py wraps this now, no need to truncate
			'lo': '--',  # filled from the paired night entry below
			'hi': _fmt_temp(hi, units).rstrip('°'),
			'_icon_code': icon_val,
		})

	# Second pass: pull the "low" temperature from each period's own night
	# pairing where present (EC lists night periods separately with class "low")
	night_lows = [
		next((t['value']['en'] for t in f.get('temperatures', {}).get('temperature', []) if t.get('class', {}).get('en') == 'low'), None)
		for f in forecasts if 'night' in f.get('period', {}).get('textForecastName', {}).get('en', '').lower()
	]
	for i, lo in enumerate(night_lows[:len(out)]):
		if lo is not None:
			out[i]['lo'] = _fmt_temp(lo, units).rstrip('°')

	for d in out:
		d.pop('_icon_code', None)
	return out


if __name__ == '__main__':
	import asyncio
	print(json.dumps(asyncio.run(fetch_current_conditions('on-143', 43.6532, -79.3832)), indent=2))
