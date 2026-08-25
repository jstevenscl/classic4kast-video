"""
Field coordinates extracted live from netbymatt/ws4kp (see templates/*.png,
captured with each screen's dynamic elements set to visibility:hidden so
layout never reflows -- see git history / session notes for the reflow bug
that broke the first extraction attempt). Re-extract if WS4KP's own layout
changes (a version bump, etc.) -- these are pinned coordinates, not computed
from the live page at render time.
"""

CURRENT_CONDITIONS = {
	'temp': {'x': 171, 'y': 110, 'w': 255, 'h': 37},
	'condition': {'x': 171, 'y': 147, 'w': 255, 'h': 37},
	'humidity': {'x': 637, 'y': 148, 'w': 36, 'h': 24},
	'dewpoint': {'x': 637, 'y': 184, 'w': 36, 'h': 24},
	'ceiling': {'x': 565, 'y': 220, 'w': 108, 'h': 24},
	'visibility': {'x': 601, 'y': 256, 'w': 72, 'h': 24},
	# Real coordinate re-confirmed live (2026-08-20): WS4KP's .wind-container
	# -- both the "Wind:" label and the value -- sits at y=250, not y=292.
	# The old y=292 was a stale/incorrect value from earlier session
	# debugging that left the drawn value on a different line than the
	# template's baked "Wind:" label (found from direct user feedback).
	'wind': {'x': 316, 'y': 250, 'w': 110, 'h': 37},
	'heatindex': {'x': 637, 'y': 328, 'w': 36, 'h': 24},
	'location': {'x': 428, 'y': 110, 'w': 255, 'h': 28},
	'pressure': {'x': 613, 'y': 292, 'w': 60, 'h': 24},
	# Height capped at 66px (icon top y=184, wind row now y=250 -- see
	# 'wind' above) so even the tallest real icon (Sunny.gif, ~108px
	# natively) never reaches down into the wind row after contain-fit
	# scaling. Real WS4KP's icon area isn't a fixed box at all (auto-sizes
	# to whatever icon is showing, reflowing the wind row below it) -- our
	# static-template layout can't replicate that per-icon reflow, so this
	# is the safe fixed size that works for every icon.
	'icon': {'x': 243, 'y': 184, 'w': 112, 'h': 66},
}

# Bottom advisory banner -- WS4KP's own .scroll.hazard element, shown
# site-wide (every screen) whenever a real NWS alert is active for the
# location, collapsed to nothing otherwise. Templates are captured with
# this region cropped out entirely (see templates/*.png); drawn fresh here
# from real alert data every render cycle instead of ever being baked in,
# since a frozen alert banner is worse than no banner at all.
# Exact values confirmed live against the real WS4KP .scroll.hazard element
# (not derived/guessed). Its header text (y=393) sits 10px above the fill
# box's own top edge (y=403) -- that's real WS4KP behavior (the header
# pokes up onto the divider line), not something to "fix".
ADVISORY_BANNER = {'x': 0, 'y': 403, 'w': 854, 'h': 77, 'bg': (112, 35, 35)}

# Real WS4KP clock position/font, confirmed live via getBoundingClientRect +
# getComputedStyle against .date-time.time/.date-time.date (not guessed).
# Templates are captured with these hidden (visibility:hidden) so the live
# per-second overlay renderer draws the only clock that ever appears.
CLOCK_TIME = {'x': 522, 'y': 30, 'w': 170, 'h': 37}
CLOCK_DATE = {'x': 522, 'y': 30, 'w': 170, 'h': 59}
CLOCK_FONT = ('Star4000-Small', 32)
CLOCK_COLOR = (255, 255, 255)

HOURLY_FORECAST = {
	# Re-verified live (2026-08-20): real WS4KP's scroll area is y:90-400
	# and it fits 4 rows at 72px each (the 4th just ~8px clipped in its own
	# scrolling view) -- 3 enlarged rows was a wrong earlier assumption,
	# corrected from direct user feedback after watching the real page.
	# 70px here (vs WS4KP's 72px) fits all 4 with zero clipping in our
	# static (non-scrolling) render.
	'row_height': 70,
	'first_row_y': 120,
	'visible_rows': 4,
	'hour': {'x': 132, 'w': 154, 'h': 37},
	'temp': {'x': 462, 'w': 58, 'h': 37},
	'like': {'x': 532, 'w': 58, 'h': 37},
	'wind': {'x': 612, 'w': 100, 'h': 37},
	'icon': {'x': 367, 'w': 60, 'h': 56},
}

# Real coordinates extracted live from WS4KP's #almanac-html (widescreen
# layout only shows 2 sun/sunset columns at our 854px width -- the DOM has a
# 3rd 'wide-enhanced' column that WS4KP itself hides below its own
# ultra-wide breakpoint, confirmed live, not a capture bug).
ALMANAC = {
	'day_header': {'x': [359, 585], 'y': 93, 'w': 137, 'h': 30},
	'rise': {'x': [359, 585], 'y': 123, 'w': 137, 'h': 30},
	'set': {'x': [359, 585], 'y': 153, 'w': 137, 'h': 30},
	'moon_type': {'x': 163, 'y': 231, 'w': 132, 'h': 36, 'col_spacing': 132},
	'moon_icon': {'x': 184, 'y': 267, 'w': 100, 'h': 94, 'col_spacing': 132},
	'moon_date': {'x': 163, 'y': 358, 'w': 132, 'h': 36, 'col_spacing': 132},
	'moon_cols': 4,
}

# Real box extracted live from WS4KP's #local-forecast-html .container.
LOCAL_FORECAST = {'box': {'x': 181, 'y': 105, 'w': 492, 'h': 280}}

# Our own design, same reasoning as RADAR/SPC_OUTLOOK below -- no real WS4KP
# screenshot to extract from (marine forecast doesn't exist in upstream
# ws4kp), reuses the generic full-content-box shape with a programmatically
# drawn title (see screens/marine_forecast.py, templates/regional_map_blank.png).
MARINE_FORECAST = {
	'box': {'x': 181, 'y': 105, 'w': 492, 'h': 280},
	'title_top': {'x': 270, 'y': 30, 'w': 220, 'h': 32},
	'title_bottom': {'x': 270, 'y': 60, 'w': 250, 'h': 32},
}

# Same generic box as MARINE_FORECAST/RADAR/SPC_OUTLOOK -- real WS4KP+'s
# "Almanac / Tides" sub-page (see adapters/tides.py's module docstring),
# no netbymatt/ws4kp screenshot exists for this since that lineage never
# built it, hence our own design reusing the shared chrome.
TIDE_INFO = {
	'box': {'x': 181, 'y': 105, 'w': 492, 'h': 280},
	'title_top': {'x': 270, 'y': 30, 'w': 220, 'h': 32},
	'title_bottom': {'x': 270, 'y': 60, 'w': 250, 'h': 32},
	'station_name': {'x_off': 10, 'y_off': 10, 'w': 472, 'h': 30},
	'row_height': 44,
	'first_row_y_off': 60,
}

# Same generic box/title layout as TIDE_INFO/MARINE_FORECAST -- our own
# design (see adapters/air_quality.py's module docstring).
AIR_QUALITY = {
	'box': {'x': 181, 'y': 105, 'w': 492, 'h': 280},
	'title_top': {'x': 270, 'y': 30, 'w': 220, 'h': 32},
	'title_bottom': {'x': 270, 'y': 60, 'w': 250, 'h': 32},
	'aqi_value': {'x_off': 0, 'y_off': 70, 'w': 492, 'h': 90},
	'category': {'x_off': 0, 'y_off': 165, 'w': 492, 'h': 40},
	'driver': {'x_off': 0, 'y_off': 215, 'w': 492, 'h': 36},
}

# Same generic box/title layout -- real WS4KP+ titles this "Almanac" /
# "Outlook" (see adapters/outlook_30day.py's module docstring).
OUTLOOK_30DAY = {
	'box': {'x': 181, 'y': 105, 'w': 492, 'h': 280},
	'title_top': {'x': 270, 'y': 30, 'w': 220, 'h': 32},
	'title_bottom': {'x': 270, 'y': 60, 'w': 250, 'h': 32},
	'period': {'x_off': 0, 'y_off': 15, 'w': 492, 'h': 30},
	'temperature_label': {'x_off': 20, 'y_off': 90, 'w': 452, 'h': 34},
	'precipitation_label': {'x_off': 20, 'y_off': 170, 'w': 452, 'h': 34},
}

# Real coordinates extracted live from WS4KP's #latest-observations-html.
REGIONAL_OBSERVATIONS = {
	'row_height': 40,
	'first_row_y': 100,
	'visible_rows': 7,
	# 167px, 14-char truncation (see nws.fetch_regional_observations) --
	# matches real WS4KP's own latestobservations.mjs locationLimit exactly
	# (confirmed live against its source). An earlier attempt at "names are
	# getting cut off" widened this box and shrunk the font to fit instead
	# -- reverted, since real WS4KP truncates at a FIXED font size too, and
	# per-row font shrinking just looked inconsistent (found from direct
	# user feedback).
	'location': {'x': 171, 'w': 167, 'h': 37},
	'temp': {'x': 401, 'w': 46, 'h': 37},
	'weather': {'x': 451, 'w': 122, 'h': 37},
	'wind': {'x': 601, 'w': 76, 'h': 37},
}

# Radar and SPC Outlook are our own design (see adapters/radar.py,
# adapters/spc.py docstrings for why) -- box reuses the same generic
# full-content-box shape as Local Forecast's real extracted coordinates,
# just with a custom "Local Radar"/"SPC Outlook" title patched in during
# template capture.
RADAR = {'box': {'x': 181, 'y': 105, 'w': 492, 'h': 280}}
SPC_OUTLOOK = {'box': {'x': 181, 'y': 105, 'w': 492, 'h': 280}}
REGIONAL_MAP = {
	'box': {'x': 181, 'y': 105, 'w': 492, 'h': 280},
	# Dual-title top/bottom lines -- drawn fresh (not baked into the
	# template) since this same screen shows "Regional"/"Observations" for
	# current conditions and "Forecast"/"for <Day>" for the next-day page
	# (both real WS4KP states, confirmed live -- it sub-cycles between them).
	'title_top': {'x': 270, 'y': 30, 'w': 220, 'h': 32},
	'title_bottom': {'x': 270, 'y': 60, 'w': 250, 'h': 32},
}

# Real chart-area box extracted live from WS4KP's #chart-area img
# (widescreen layout: temp/dewpoint/cloud%/precip% all plotted on one
# shared chart, confirmed live -- the portrait-only second cloud/precip
# chart is hidden at this resolution, same wide-enhanced-column pattern
# seen elsewhere in this project).
HOURLY_GRAPH = {
	'chart': {'x': 157, 'y': 90, 'w': 532, 'h': 285},
	'y_axis_label_x': 100,
	'x_axis_label_y': 378,
}

# Real coordinates extracted live from WS4KP's #travel-html. Re-verified
# live (2026-08-20): the real scroll area spans y:90-400 and rows really
# are 72px each -- 4 fit (the 4th is only ~8px clipped at the very bottom
# in WS4KP's own scrolling view) -- so 4 real cities at close to the real
# row height is the accurate target, not 3 artificially enlarged rows
# (an earlier, wrong assumption corrected from direct user feedback after
# watching the real page side by side).
TRAVEL_FORECAST = {
	'title': {'x': 277, 'y': 56, 'w': 182, 'h': 37},  # 'For <Weekday>' -- dynamic, drawn fresh (see nws.fetch_travel_forecast)
	'row_height': 70,
	'first_row_y': 120,
	'visible_rows': 4,
	'city': {'x': 187, 'w': 135, 'h': 37},
	'icon': {'x': 440, 'w': 50, 'h': 52, 'y_offset': -2},
	# Widened from the original real-extracted x:562/x:617 (only 55px
	# apart, template's baked "LOW"/"HIGH" headers sat right on top of each
	# other) -- both headers and values are now drawn fresh, centered over
	# these same wider columns (found from direct user feedback).
	'low': {'x': 540, 'w': 70, 'h': 46},
	'high': {'x': 630, 'w': 70, 'h': 46},
	'header_y': 99,
}

EXTENDED_FORECAST = {
	'col_width': 195,
	'first_col_x': 149,
	'col_y': 106,
	'visible_cols': 3,
	'date': {'x_off': 5, 'y_off': 5, 'w': 155, 'h': 37},
	'icon': {'x_off': 44, 'y_off': 42, 'w': 78, 'h': 75},
	'condition': {'x_off': 5, 'y_off': 122, 'w': 155, 'h': 74},
	# Real WS4KP stacks a "Lo"/"Hi" label directly above each value within
	# its own temperature-block column (views/partials/extended-forecast.ejs)
	# -- confirmed via its real markup/SCSS, we were only ever drawing the
	# bare numbers. Same x-position/width as the value box below it, just
	# above in the existing gap between condition and the temps.
	'lo_label': {'x_off': 5, 'y_off': 208, 'w': 68, 'h': 22},
	'hi_label': {'x_off': 73, 'y_off': 208, 'w': 68, 'h': 22},
	'lo': {'x_off': 5, 'y_off': 237, 'w': 68, 'h': 37},
	'hi': {'x_off': 73, 'y_off': 237, 'w': 68, 'h': 37},
}
