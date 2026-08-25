"""
Local radar adapter. Uses the same national NEXRAD reflectivity composite
(IEM's 'uscomp/n0r' mosaic) WS4KP itself fetches -- confirmed live via
network-request inspection of the real WS4KP page. We crop+scale it
ourselves instead of using WS4KP's own map-tile/Leaflet compositing (that
screen requires a manual tap to load in real WS4KP and isn't part of its
own auto-rotation -- see project notes), so this is our own design, not a
port of WS4KP's exact radar screen.

Real, documented georeferencing (not guessed or reverse-engineered): IEM
publishes a companion .wld world file for this exact image --
pixel size 0.01 degrees/pixel, top-left corner at (lon=-126.0, lat=50.0).
Confirmed live by fetching
https://mesonet.agron.iastate.edu/data/gis/images/4326/USCOMP/n0r_0.wld
"""
import csv
import json
import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from io import BytesIO

import httpx
from PIL import Image, ImageChops, ImageDraw

from renderer import assets

UA = {'User-Agent': 'classic4kast (self-hosted weather renderer, personal use)'}

# Real, public-domain US state boundary polygons (lon/lat coordinates) --
# not a raster basemap image (none exists at this composite's exact
# projection, confirmed by checking IEM directly), so we draw the real
# boundaries ourselves from vector data instead of faking a background.
STATES_GEOJSON_URL = 'https://raw.githubusercontent.com/PublicaMundi/MappingAPI/master/data/geojson/us-states.json'
_states_cache = None

# From the real n0r_0.wld world file (see module docstring).
ORIGIN_LON, ORIGIN_LAT = -126.0, 50.0
DEG_PER_PX = 0.01
COMPOSITE_SIZE = (6000, 2600)

NO_ECHO_THRESHOLD = 24  # near-black pixels (all channels below this) are "no echo" background, made transparent

# Real US+Canada city dataset (name, lat, lon, population), replacing the
# old ~200-entry hand-curated list -- that list only ever grew when someone
# happened to report a specific gap (St. Augustine FL was the most recent),
# so map density for any as-yet-unreported area depended entirely on luck.
# See renderer/data/NOTICE.md for the real source/license (SimpleMaps' free
# US+Canada Cities databases, CC-BY 4.0, merged/filtered to population >=
# 5,000 -- 7,253 real cities). Includes Canada specifically so US border
# channels (e.g. buffalo-ny) can show real nearby Canadian cities instead of
# only ever drawing from a US-only pool -- found from direct user feedback.
POPULATION_TIERS = [500_000, 250_000, 100_000, 50_000, 25_000, 10_000]


def tier_rank(population):
	"""Index of the first (largest) population tier a city qualifies for --
	lower is bigger/more prominent. Used by _select_spaced_cities-style
	candidate ordering (nws._nearby_major_cities, _draw_city_labels below) to
	prefer big, recognizable cities first and only fall back to smaller
	towns to fill map space bigger cities didn't already claim -- never
	changes the actual non-overlap selection logic itself, only candidate
	order."""
	for i, threshold in enumerate(POPULATION_TIERS):
		if population >= threshold:
			return i
	return len(POPULATION_TIERS)  # below every named tier, still >= the dataset's 5,000 floor


def _load_major_cities():
	path = os.path.join(assets.DATA_DIR, 'major_cities.csv')
	with open(path, encoding='utf-8') as f:
		return [
			(row['name'], float(row['lat']), float(row['lon']), int(row['population']), row['country'])
			for row in csv.DictReader(f)
		]


MAJOR_CITIES = _load_major_cities()


def _lonlat_to_px(lon, lat):
	x = round((lon - ORIGIN_LON) / DEG_PER_PX)
	y = round((ORIGIN_LAT - lat) / DEG_PER_PX)
	return x, y


def lon_span_for_box(lat_span_degrees, box_size):
	"""Real bug found from direct user feedback ("skewed and not straight"):
	every lon/lat-to-pixel conversion here used the SAME span_degrees for
	both width and height regardless of box_size's actual aspect ratio
	(492x280, not square) -- that stretches real geography to fit a
	mismatched box. `span_degrees` is the LATITUDE (vertical) span; this
	derives the matching LONGITUDE (horizontal) span from the box's own
	aspect ratio, so cropping/plotting into box_size never distorts shape
	regardless of what span_degrees is chosen for zoom level."""
	w, h = box_size
	return lat_span_degrees * (w / h)


async def _get_states_geojson(client):
	global _states_cache
	if _states_cache is None:
		r = await client.get(STATES_GEOJSON_URL, timeout=20)
		r.raise_for_status()
		_states_cache = json.loads(r.content)
	return _states_cache


@lru_cache(maxsize=32)
def _build_basemap_layer(states_json_str, box_size, center_lat, center_lon, span_degrees):
	"""Draws real US state boundary lines (from _get_states_geojson) into
	the crop's own pixel space, cached per (city, span, box size) since the
	boundaries themselves never change -- computed once per city, not once
	per radar frame (8x/refresh-cycle would be wasteful for identical
	output)."""
	states = json.loads(states_json_str)
	w, h = box_size
	lon_span = lon_span_for_box(span_degrees, box_size)
	half_lat, half_lon = span_degrees / 2, lon_span / 2
	lon_min, lon_max = center_lon - half_lon, center_lon + half_lon
	lat_min, lat_max = center_lat - half_lat, center_lat + half_lat

	layer = Image.new('RGBA', box_size, (0, 0, 0, 0))
	draw = ImageDraw.Draw(layer)

	def to_px(lon, lat):
		return ((lon - lon_min) / lon_span * w, (lat_max - lat) / span_degrees * h)

	for feature in states['features']:
		geom = feature['geometry']
		polygons = geom['coordinates'] if geom['type'] == 'MultiPolygon' else [geom['coordinates']]
		for polygon in polygons:
			for ring in polygon:
				lons = [pt[0] for pt in ring]
				lats = [pt[1] for pt in ring]
				if max(lons) < lon_min or min(lons) > lon_max or max(lats) < lat_min or min(lats) > lat_max:
					continue  # ring's bounding box doesn't intersect our view at all
				pts = [to_px(lon, lat) for lon, lat in ring]
				draw.line(pts, fill=(210, 210, 220, 235), width=2)
	return layer


async def _fetch_composite_at(client, dt):
	"""Composites are published every 5 minutes; try the requested slot and
	step backward a few times in case the very latest hasn't posted yet."""
	rounded = dt - timedelta(minutes=dt.minute % 5, seconds=dt.second, microseconds=dt.microsecond)
	for _ in range(4):
		url = rounded.strftime('https://mesonet.agron.iastate.edu/archive/data/%Y/%m/%d/GIS/uscomp/n0r_%Y%m%d%H%M.png')
		r = await client.get(url, timeout=15)
		if r.status_code == 200 and len(r.content) > 10_000:
			return Image.open(BytesIO(r.content)).convert('RGB'), rounded
		rounded -= timedelta(minutes=5)
	return None, None


def _crop_and_composite(national_img, lat, lon, box_size, states_json_str, span_degrees=5.0, bg=(20, 30, 70)):
	"""Crops a span_degrees x span_degrees box centered on (lat, lon),
	treats near-black (no-echo) pixels as transparent so our own background
	shows through instead of a black square, resizes to box_size. Real state
	boundary lines are drawn UNDER the radar echoes so they stay visible
	everywhere there's no active precipitation and get naturally covered
	where there is (matches how real radar apps layer this)."""
	lon_span = lon_span_for_box(span_degrees, box_size)
	half_px_x = round((lon_span / 2) / DEG_PER_PX)
	half_px_y = round((span_degrees / 2) / DEG_PER_PX)
	cx, cy = _lonlat_to_px(lon, lat)
	crop = national_img.crop((cx - half_px_x, cy - half_px_y, cx + half_px_x, cy + half_px_y)).convert('RGB')

	# Vectorized (C-level) transparency mask instead of a per-pixel Python
	# loop -- a 500x500 crop's worth of pure-Python pixel access would block
	# the event loop for a second-plus per frame, stuttering the live stream.
	r, g, b = crop.split()
	brightest = ImageChops.lighter(ImageChops.lighter(r, g), b)
	alpha = brightest.point(lambda p: 255 if p >= NO_ECHO_THRESHOLD else 0)
	crop_rgba = crop.convert('RGBA')
	crop_rgba.putalpha(alpha)

	out = Image.new('RGBA', box_size, bg + (255,))
	basemap = _build_basemap_layer(states_json_str, box_size, lat, lon, span_degrees)
	out.alpha_composite(basemap)
	resized = crop_rgba.resize(box_size, Image.LANCZOS)
	out.alpha_composite(resized)
	final = out.convert('RGB')
	_draw_geo_reference(final, lat, lon, span_degrees)
	_draw_city_labels(final, lat, lon, span_degrees)
	return final


def _draw_city_labels(img, center_lat, center_lon, span_degrees, exclude_radius_degrees=0.15):
	"""Labels nearby MAJOR_CITIES cities within the current crop, big-city-
	first with real pixel-box overlap avoidance (same greedy tier-then-
	nearest approach as nws._select_spaced_cities). Needed now that
	MAJOR_CITIES is a real ~7,000-entry dataset instead of the old ~200-entry
	curated list -- drawing every in-range match unconditionally (the old
	behavior, fine at 200 entries) would visibly clutter dense metro areas.
	Skips anything within exclude_radius_degrees of the target city itself
	since that one already gets its own label + crosshair (see
	screens/radar.py)."""
	w, h = img.size
	lon_span = lon_span_for_box(span_degrees, (w, h))
	half_lat, half_lon = span_degrees / 2, lon_span / 2
	edge_lon_min, edge_lat_max = center_lon - half_lon, center_lat + half_lat
	# A small inset margin so a label never gets half-clipped right at the
	# crop edge -- found from direct user feedback ("H" for Houston cut off
	# at the right border, another label clipped at the bottom). Only
	# affects which cities are considered "in view", not the pixel mapping.
	margin_lat, margin_lon = span_degrees * 0.08, lon_span * 0.08
	lon_min, lon_max = edge_lon_min + margin_lon, center_lon + half_lon - margin_lon
	lat_min, lat_max = center_lat - half_lat + margin_lat, edge_lat_max - margin_lat
	draw = ImageDraw.Draw(img)
	f = assets.font('Star4000-Small', 16)

	candidates = [
		(name, lat, lon, population) for name, lat, lon, population, _country in MAJOR_CITIES
		if lon_min <= lon <= lon_max and lat_min <= lat <= lat_max
		and not (abs(lat - center_lat) < exclude_radius_degrees and abs(lon - center_lon) < exclude_radius_degrees)
	]
	# Big/recognizable cities first; smaller towns only ever fill space
	# bigger ones didn't already claim (a candidate whose box overlaps an
	# already-accepted one is skipped outright below, regardless of tier).
	candidates.sort(key=lambda c: (tier_rank(c[3]), (c[1] - center_lat) ** 2 + (c[2] - center_lon) ** 2))

	# Real bug found from direct user feedback ("so many city names close
	# together, not the same spacing as the regional maps"): the overlap box
	# below used to be only 15px tall (y-10 to y+r+2) with no horizontal
	# padding past the text's own measured width -- barely more than the
	# 16px font's own glyph height, so adjacent labels' overlap test passed
	# even when their text visually touched or nearly touched. Padding both
	# axes gives real breathing room between accepted labels, closer to how
	# roomy adapters/regional_map.py's own (much taller, 90x16) label boxes
	# read -- this thins out max city count a little in dense areas, which
	# is the correct tradeoff over labels crowding together illegibly.
	r = 3
	pad_x, pad_y = 4, 6
	accepted_boxes = []
	for name, lat, lon, _population in candidates:
		x = (lon - edge_lon_min) / lon_span * w
		y = (edge_lat_max - lat) / span_degrees * h
		text_w = draw.textlength(name, font=f)
		box = (x - r - pad_x, y - 10 - pad_y, x + 6 + text_w + pad_x, y + r + 2 + pad_y)
		if any(not (box[2] < o[0] or box[0] > o[2] or box[3] < o[1] or box[1] > o[3]) for o in accepted_boxes):
			continue
		accepted_boxes.append(box)
		draw.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255), outline=(0, 0, 0))
		draw.text((x + 6, y - 8), name, font=f, fill=(255, 255, 255), stroke_width=1, stroke_fill=(0, 0, 0))


def _draw_geo_reference(img, center_lat, center_lon, span_degrees):
	"""No basemap/state-boundary layer exists for this exact composite (IEM
	doesn't publish one at this projection, confirmed by checking) -- rather
	than fabricate state lines that could end up subtly wrong, this draws a
	real, honest 1-degree lat/lon graticule with labels so a viewer can tell
	orientation/scale, plus the city name (found missing entirely from direct
	user feedback: 'nothing is visible as far as showing where on the map')."""
	w, h = img.size
	lon_span = lon_span_for_box(span_degrees, (w, h))
	half_lat, half_lon = span_degrees / 2, lon_span / 2
	draw = ImageDraw.Draw(img, 'RGBA')
	f = assets.font('Star4000-Small', 14)
	grid_color = (255, 255, 255, 70)

	lon_start = int(center_lon - half_lon) - 1
	for lon_line in range(lon_start, lon_start + int(lon_span) + 3):
		if not (center_lon - half_lon <= lon_line <= center_lon + half_lon):
			continue
		x = round((lon_line - (center_lon - half_lon)) / lon_span * w)
		draw.line([(x, 0), (x, h)], fill=grid_color, width=1)
		draw.text((x + 3, 3), f'{lon_line}°', font=f, fill=(255, 255, 255, 160))

	lat_start = int(center_lat - half_lat) - 1
	for lat_line in range(lat_start, lat_start + int(span_degrees) + 3):
		if not (center_lat - half_lat <= lat_line <= center_lat + half_lat):
			continue
		y = round((center_lat + half_lat - lat_line) / span_degrees * h)
		draw.line([(0, y), (w, y)], fill=grid_color, width=1)
		draw.text((3, y + 2), f'{lat_line}°', font=f, fill=(255, 255, 255, 160))


async def fetch_radar_frames(lat, lon, box_size, count=8, interval_minutes=5, span_degrees=5.0):
	"""Returns up to `count` composited radar frames, oldest first, at
	`interval_minutes` spacing -- meant to be played back in sequence for a
	real animated loop (see live_stream.py), not a single static image."""
	now = datetime.now(timezone.utc)
	frames = []
	async with httpx.AsyncClient(headers=UA) as client:
		states = await _get_states_geojson(client)
		states_json_str = json.dumps(states)
		for i in range(count - 1, -1, -1):
			national, actual_time = await _fetch_composite_at(client, now - timedelta(minutes=i * interval_minutes))
			if national is None:
				continue
			# Deliberately inline/synchronous, not asyncio.to_thread --
			# reverted 2026-08-24 (see live_stream.py's _refresh_loop
			# comment): offloading this made stutter WORSE, not better --
			# Pillow's C extensions release the GIL, so 8 offloaded
			# crop/resize calls run in genuine cross-core parallel with
			# ffmpeg's own encode/decode threads instead of just getting
			# off the event loop, and that real CPU-core contention showed
			# up as more frequent stutter during each refresh burst.
			frames.append(_crop_and_composite(national, lat, lon, box_size, states_json_str, span_degrees))
	return frames
