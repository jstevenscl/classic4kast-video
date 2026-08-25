"""
Open-Meteo adapter (api.open-meteo.com, global coverage, free, no API key) --
the "everywhere else" tier for countries with no dedicated adapter (see
nws.py for US, ec.py for Canada). Same design as netbymatt/ws4kp's own
international fork (mwood77/ws4kp-international), which replaced NWS with
Open-Meteo to get worldwide coverage.

Deliberately narrower than nws.py: Open-Meteo has no equivalent to NWS's
Hazards/Regional Observations/Travel Forecast/Regional Map products (those
are real NWS-specific constructs, not just US-flavored data -- there's
nothing to port), and no radar of its own. Only the three screens with a
real data match are implemented here; live_stream.py's country dispatch
must not call anything else for an INTL channel. Almanac needs no adapter
at all (astro.py is pure astral sun/moon math, works for any lat/lon).

Same output shape as ec.py (deliberately -- screens/current_conditions.py,
screens/hourly_forecast.py, screens/extended_forecast.py consume either
without caring which adapter produced it). Respects the channel's own
units setting directly via Open-Meteo's own unit params (imperial ->
fahrenheit/mph, metric -> celsius/kmh) -- simpler than ec.py's manual
conversion since Open-Meteo's API does the conversion server-side.
"""
from datetime import datetime

import httpx

FORECAST_URL = 'https://api.open-meteo.com/v1/forecast'

# WMO weather interpretation codes (the standard Open-Meteo, and most other
# providers, report) -- https://open-meteo.com/en/docs (weather_code field).
_WMO_ICON = {
	0: 'Sunny', 1: 'Mostly-Clear', 2: 'Partly-Cloudy', 3: 'Cloudy',
	45: 'Fog', 48: 'Fog',
	51: 'Rain', 53: 'Rain', 55: 'Rain', 56: 'Freezing-Rain', 57: 'Freezing-Rain',
	61: 'Rain', 63: 'Rain', 65: 'Rain', 66: 'Freezing-Rain', 67: 'Freezing-Rain',
	71: 'Light-Snow', 73: 'Light-Snow', 75: 'Heavy-Snow', 77: 'Light-Snow',
	80: 'Shower', 81: 'Shower', 82: 'Shower',
	85: 'Light-Snow', 86: 'Heavy-Snow',
	95: 'Thunderstorm', 96: 'Thunderstorm', 99: 'Thunderstorm',
}
_NIGHT_ICON = {'Sunny': 'Clear', 'Mostly-Clear': 'Mostly-Clear', 'Partly-Cloudy': 'Partly-Cloudy'}
_WMO_CONDITION_TEXT = {
	0: 'Clear', 1: 'Mostly Clear', 2: 'Partly Cloudy', 3: 'Cloudy',
	45: 'Fog', 48: 'Fog',
	51: 'Light Drizzle', 53: 'Drizzle', 55: 'Heavy Drizzle', 56: 'Freezing Drizzle', 57: 'Freezing Drizzle',
	61: 'Light Rain', 63: 'Rain', 65: 'Heavy Rain', 66: 'Freezing Rain', 67: 'Freezing Rain',
	71: 'Light Snow', 73: 'Snow', 75: 'Heavy Snow', 77: 'Snow Grains',
	80: 'Rain Showers', 81: 'Rain Showers', 82: 'Heavy Rain Showers',
	85: 'Snow Showers', 86: 'Heavy Snow Showers',
	95: 'Thunderstorm', 96: 'Thunderstorm', 99: 'Severe Thunderstorm',
}
_COMPASS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']


def _compass(degrees):
	if degrees is None:
		return 'VAR'
	return _COMPASS[round(degrees / 22.5) % 16]


def _icon(code, is_day):
	base = _WMO_ICON.get(code, 'No-Data')
	if base != 'No-Data' and is_day == 0:
		return _NIGHT_ICON.get(base, base)
	return base


def _hpa_to_inhg(hpa):
	return round(hpa * 0.02953, 2) if hpa is not None else None


async def _fetch(lat, lon, units='imperial', **params):
	async with httpx.AsyncClient() as client:
		r = await client.get(FORECAST_URL, params={
			'latitude': lat, 'longitude': lon,
			'temperature_unit': 'fahrenheit' if units == 'imperial' else 'celsius',
			'wind_speed_unit': 'mph' if units == 'imperial' else 'kmh',
			'timezone': 'auto', **params,
		}, timeout=15)
		r.raise_for_status()
		return r.json()


async def fetch_current_conditions(lat, lon, city_name=None, units='imperial'):
	data = await _fetch(
		lat, lon, units=units,
		current='temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,'
		        'pressure_msl,wind_speed_10m,wind_direction_10m,dew_point_2m,is_day',
	)
	cur = data['current']
	temp = cur.get('temperature_2m')
	code = cur.get('weather_code')
	pressure = f"{_hpa_to_inhg(cur.get('pressure_msl'))}" if units == 'imperial' \
		else (f"{round(cur['pressure_msl'])} hPa" if cur.get('pressure_msl') is not None else '--')

	return {
		'location': (city_name or f"{lat:.2f}, {lon:.2f}")[:20],  # matches real WS4KP's 20-char location limit
		'temp': f"{round(temp)}°" if temp is not None else '--',
		'condition': _WMO_CONDITION_TEXT.get(code, 'Unknown'),
		'icon': _icon(code, cur.get('is_day', 1)),
		'humidity': f"{cur['relative_humidity_2m']}%" if cur.get('relative_humidity_2m') is not None else '--',
		'dewpoint': f"{round(cur['dew_point_2m'])}°" if cur.get('dew_point_2m') is not None else '--',
		'ceiling': 'Unlimited',  # not present in this endpoint
		'visibility': '10 mi.' if units == 'imperial' else '16 km',  # not present in this endpoint -- placeholder, matches ec.py's own gap
		'pressure': pressure if cur.get('pressure_msl') is not None else '--',
		'wind': f"{_compass(cur.get('wind_direction_10m'))}  {round(cur['wind_speed_10m']) if cur.get('wind_speed_10m') is not None else 0}",
		'heatindex': f"{round(cur['apparent_temperature'])}°" if cur.get('apparent_temperature') is not None else '--',
	}


async def fetch_hourly_forecast(lat, lon, hours=5, units='imperial'):
	data = await _fetch(
		lat, lon, units=units,
		hourly='temperature_2m,weather_code,wind_speed_10m,wind_direction_10m,is_day',
		forecast_hours=hours,
	)
	hourly = data['hourly']
	out = []
	for i in range(min(hours, len(hourly['time']))):
		temp = hourly['temperature_2m'][i]
		out.append({
			'hour': _format_hour(hourly['time'][i]),
			'temp': str(round(temp)) if temp is not None else '--',
			'like': str(round(temp)) if temp is not None else '--',
			'wind': f"{_compass(hourly['wind_direction_10m'][i])}  {round(hourly['wind_speed_10m'][i]) if hourly['wind_speed_10m'][i] is not None else 0}",
			'icon': _icon(hourly['weather_code'][i], hourly.get('is_day', [1] * len(hourly['time']))[i]),
		})
	return out


def _format_hour(iso_time):
	return datetime.fromisoformat(iso_time).strftime('%a %-I %p')


async def fetch_extended_forecast(lat, lon, days=3, units='imperial'):
	data = await _fetch(
		lat, lon, units=units,
		daily='weather_code,temperature_2m_max,temperature_2m_min',
		forecast_days=days,
	)
	daily = data['daily']
	out = []
	for i in range(min(days, len(daily['time']))):
		code = daily['weather_code'][i]
		hi, lo = daily['temperature_2m_max'][i], daily['temperature_2m_min'][i]
		date = datetime.fromisoformat(daily['time'][i])
		out.append({
			'date': date.strftime('%a')[:3],
			'icon': _icon(code, 1),  # daily summary icon -- always the daytime variant
			'condition': _WMO_CONDITION_TEXT.get(code, ''),  # screens/extended_forecast.py wraps this now, no need to truncate
			'lo': str(round(lo)) if lo is not None else '--',
			'hi': str(round(hi)) if hi is not None else '--',
		})
	return out
