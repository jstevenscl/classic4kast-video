"""
Regional Observations map adapter. Confusingly, WS4KP's real checkbox for
this is named 'regional-forecast-checkbox' but the on-screen title reads
"Regional Observations" (confirmed live) -- current conditions at nearby
stations plotted on a map, not a forecast. Real WS4KP also sub-cycles this
same screen into a next-day "Forecast for <Day>" page using its own basemap
image + absolute-pixel marker positions from an internal projection we
don't have access to; rather than fake that, this reuses the SAME real
lat/lon state-boundary map already built and validated for the Radar
screen (adapters/radar.py) and plots real nearby-station markers on it --
one static page (current conditions), not the multi-page sub-cycle.
"""
import json

import httpx
from PIL import Image

from renderer import assets
from renderer.adapters import radar
from renderer.adapters.nws import fetch_regional_map as fetch_stations
from renderer.adapters.nws import fetch_regional_map_forecast as fetch_stations_forecast
from renderer.adapters.nws import fetch_regional_map_forecast_night as fetch_stations_forecast_night

UA = radar.UA

MAP_BG = (150, 150, 140)  # neutral gray land -- no real land/water fill data available (see module docstring), just boundary lines over a flat tone


async def fetch_map(lat, lon, box_size, span_degrees=5.0, count=8, target_name=None):
	"""Returns (basemap_image, stations) -- stations is
	adapters.nws.fetch_regional_map's real output, basemap_image already has
	state boundaries baked in at this box's exact projection. target_name,
	if given, always includes the channel's own city on the map (real
	curated city databases -- ours AND real WS4KP's own -- don't guarantee
	a given target city is in them; see nws._fetch_target_marker)."""
	async with httpx.AsyncClient(headers=UA) as client:
		states = await radar._get_states_geojson(client)
	states_json_str = json.dumps(states)
	basemap = radar._build_basemap_layer(states_json_str, box_size, lat, lon, span_degrees)
	base = Image.new('RGB', box_size, MAP_BG)
	base.paste(basemap, (0, 0), basemap)
	stations = await fetch_stations(lat, lon, box_size, span_degrees, count, target_name=target_name)
	return base, stations


async def fetch_map_forecast(lat, lon, box_size, span_degrees=5.0, count=8, target_name=None):
	"""Same as fetch_map but with tomorrow's forecast data instead of
	current observations -- see nws.fetch_regional_map_forecast."""
	async with httpx.AsyncClient(headers=UA) as client:
		states = await radar._get_states_geojson(client)
	states_json_str = json.dumps(states)
	basemap = radar._build_basemap_layer(states_json_str, box_size, lat, lon, span_degrees)
	base = Image.new('RGB', box_size, MAP_BG)
	base.paste(basemap, (0, 0), basemap)
	stations = await fetch_stations_forecast(lat, lon, box_size, span_degrees, count, target_name=target_name)
	return base, stations


async def fetch_map_forecast_night(lat, lon, box_size, span_degrees=5.0, count=8, target_name=None):
	"""Same as fetch_map_forecast but tomorrow NIGHT's low temp/icon --
	the real WS4KP+ 'Forecast for <Day> Night' sub-page (see
	nws.fetch_regional_map_forecast_night)."""
	async with httpx.AsyncClient(headers=UA) as client:
		states = await radar._get_states_geojson(client)
	states_json_str = json.dumps(states)
	basemap = radar._build_basemap_layer(states_json_str, box_size, lat, lon, span_degrees)
	base = Image.new('RGB', box_size, MAP_BG)
	base.paste(basemap, (0, 0), basemap)
	stations = await fetch_stations_forecast_night(lat, lon, box_size, span_degrees, count, target_name=target_name)
	return base, stations


_LABEL_W, _LABEL_H = 90, 16
# Tried in order for each station's name label -- default position (above
# the marker) first, then progressively farther alternatives, before giving
# up and letting it overlap. The octant-spread candidate ordering
# (nws._nearby_major_cities) fixes which DIRECTIONS get picked, but two
# genuinely close cities (e.g. Ocala/Daytona Beach, ~65 miles apart) can
# still land close enough on screen that the fixed-position labels touch --
# found from direct user feedback ("bunched together... spacing").
_LABEL_OFFSET_STEPS = [-28, -46, -10, 8, -64, 26]


def _rects_overlap(a, b):
	return not (
		a['x'] + a['w'] <= b['x'] or b['x'] + b['w'] <= a['x']
		or a['y'] + a['h'] <= b['y'] or b['y'] + b['h'] <= a['y']
	)


def _fit_label(draw, text, font_obj, max_width):
	"""Real bug found from direct user feedback ("StateColleg" / "State
	Colleg" instead of "State College"): this used to be a blind
	`name[:12]` character-count slice, sized for the OLD ~200-entry
	hand-curated city list, which happened to mostly fit in 12 characters.
	MAJOR_CITIES is now a real ~7,000-entry dataset (see radar.py) with
	plenty of longer names ("State College" is 13 chars, "Colorado
	Springs" is 17) that got silently chopped mid-word with no indication
	anything was cut -- e.g. "State College" losing its trailing "e"
	reads as a typo, not a truncation. Measures the REAL rendered width
	(font metrics, not character count) and only truncates -- with a
	visible ellipsis -- names that actually don't fit the label box;
	most real city names now render in full.

	ASCII '...' specifically, not the single-char Unicode '…' -- found
	live rendering this: Star4000-Small.ttf (this project's retro bitmap-
	style font) has no glyph for U+2026, so it silently drew as nothing,
	which looked identical to the original bug ("STATE COLLE" with no
	visible indication anything was cut). Confirmed live: '.' renders
	fine in this font, '…' doesn't."""
	if draw.textlength(text, font=font_obj) <= max_width:
		return text
	truncated = text
	while truncated and draw.textlength(truncated + '...', font=font_obj) > max_width:
		truncated = truncated[:-1]
	return f'{truncated}...' if truncated else text[:1]


def render_markers(img, box, stations, center_lat, center_lon, span_degrees):
	"""Draws each station's icon/name/temp at its real lat/lon position
	within box -- same yellow-bold-temp/white-name/icon style confirmed live
	against the real Regional Observations screen. Marker dots (icon+temp)
	stay at their true geographic position -- only the name LABEL'S vertical
	offset is nudged to dodge already-placed labels, so real geography never
	gets faked, just decluttered."""
	draw = assets.new_draw(img)
	f_city = assets.font('Star4000-Small', 14)
	f_temp = assets.font('Star4000-Large', 18)
	# Same aspect-ratio fix as adapters/radar.py -- span_degrees is the
	# LATITUDE span; the longitude span must be derived from the box's own
	# (non-square) aspect ratio or markers land in the wrong spot relative
	# to the (correctly aspect-corrected) basemap under them.
	lon_span = radar.lon_span_for_box(span_degrees, (box['w'], box['h']))
	half_lat, half_lon = span_degrees / 2, lon_span / 2
	lon_min, lat_max = center_lon - half_lon, center_lat + half_lat

	# Two passes: first compute every station's true position + its FIXED
	# temp/icon rects (these never move, they're the real marker), then place
	# each name label dodging both the fixed marker rects AND every other
	# already-placed label. A first attempt that only checked labels against
	# OTHER labels still let a label land squarely on a neighboring station's
	# temperature digits (found visually after the first version of this fix
	# -- Gainesville's name landed on top of Jacksonville's "77").
	positioned = []
	obstacles = []
	for s in stations:
		x = round(box['x'] + (s['lon'] - lon_min) / lon_span * box['w'])
		y = round(box['y'] + (lat_max - s['lat']) / span_degrees * box['h'])
		temp_rect = {'x': x - 38, 'y': y - 10, 'w': 40, 'h': 22}
		icon_rect = {'x': x + 4, 'y': y - 8, 'w': 20, 'h': 20}
		positioned.append((s, x, y, temp_rect))
		obstacles.append(temp_rect)
		obstacles.append(icon_rect)

	placed_labels = []
	for s, x, y, temp_rect in positioned:
		label_rect = None
		for dy in _LABEL_OFFSET_STEPS:
			candidate = {'x': x - _LABEL_W / 2, 'y': y + dy, 'w': _LABEL_W, 'h': _LABEL_H}
			if not any(_rects_overlap(candidate, other) for other in (*obstacles, *placed_labels)):
				label_rect = candidate
				break
		if label_rect is None:  # every offset collided -- fall back to the default rather than drop the label
			label_rect = {'x': x - _LABEL_W / 2, 'y': y + _LABEL_OFFSET_STEPS[0], 'w': _LABEL_W, 'h': _LABEL_H}
		placed_labels.append(label_rect)

		label_text = _fit_label(draw, s['name'], f_city, _LABEL_W - 4)
		assets.draw_text(draw, label_text, label_rect, f_city, assets.WHITE, 'center')
		temp_text = f"{s['temp']}" if s['temp'] is not None else '--'
		assets.draw_text(draw, temp_text, temp_rect, f_temp, assets.YELLOW, 'left')
		assets.paste_icon(img, 'regional-maps', s['icon'], {'x': x + 4, 'y': y - 8, 'w': 20, 'h': 20})
