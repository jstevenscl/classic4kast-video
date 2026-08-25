from renderer import assets
from renderer.layout import HOURLY_FORECAST as L

# Real WS4KP colors, confirmed live via its own CSS (ws.min.css):
# .like.heat-index{color:#e00} .like.wind-chill{color:#8080ff}
LIKE_COLOR = {'heat-index': (238, 0, 0), 'wind-chill': (128, 128, 255)}


def render(rows):
	"""rows: list of dicts from adapters.*.fetch_hourly_forecast (hour, temp,
	like, wind, icon). Renders a static view of the next `visible_rows`
	hours -- WS4KP itself scrolls through all 24 in the live browser, but a
	single frozen frame can only show one screenful; showing the very next
	few hours (rather than a random mid-scroll position) is the useful,
	honest static equivalent."""
	img = assets.load_template('hourly_forecast').copy()
	draw = assets.new_draw(img)
	f = assets.font('Star4000-Large', 20)

	for i, row in enumerate(rows[:L['visible_rows']]):
		y = L['first_row_y'] + i * L['row_height']
		row_h = L['row_height']

		def box(field, y=y, row_h=row_h):
			g = L[field]
			return {'x': g['x'], 'y': y, 'w': g['w'], 'h': row_h if field != 'hour' else g['h']}

		assets.draw_text(draw, row['hour'], {**box('hour'), 'y': y + (row_h - L['hour']['h']) // 2}, f, assets.WHITE, 'left')
		assets.draw_text(draw, row['temp'], box('temp'), f, assets.WHITE, 'center')
		like_color = LIKE_COLOR.get(row.get('like_kind'), assets.WHITE)
		assets.draw_text(draw, row['like'], box('like'), f, like_color, 'center')
		assets.draw_text(draw, row['wind'], box('wind'), f, assets.WHITE, 'right')

		# WS4KP uses a SEPARATE, differently-named icon set here
		# (images/icons/regional-maps/, e.g. "Clear-1992.gif") -- our
		# icon-name mapping (adapters/nws.py, adapters/ec.py) covers the
		# current-conditions set only, so this deliberately reuses that set
		# at a smaller size rather than building a second, incomplete
		# mapping table. Visually consistent, not pixel-identical to
		# WS4KP's alternate small-icon art style.
		icon_box = L['icon']
		assets.paste_icon(img, 'current-conditions', row['icon'], {
			'x': icon_box['x'], 'y': y + (row_h - icon_box['h']) // 2, 'w': icon_box['w'], 'h': icon_box['h'],
		})

	return img
