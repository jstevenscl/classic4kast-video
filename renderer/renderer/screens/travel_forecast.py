from datetime import datetime, timedelta

from renderer import assets
from renderer.layout import TRAVEL_FORECAST as L


def render(rows, tz):
	"""rows: list of dicts from adapters.nws.fetch_travel_forecast (city,
	icon, low, high). tz: for computing tomorrow's weekday name (matches
	WS4KP's dynamic 'For <Weekday>' title, not baked into the template --
	see layout.TRAVEL_FORECAST's docstring)."""
	img = assets.load_template('travel_forecast').copy()
	draw = assets.new_draw(img)
	f_title = assets.font('Star4000', 24)
	f_city = assets.font('Star4000-Large', 22)
	f_temp = assets.font('Star4000-Large', 22)

	tomorrow = datetime.now(tz) + timedelta(days=1)
	assets.draw_text(draw, f'For {tomorrow.strftime("%A")}', L['title'], f_title, assets.YELLOW, 'left')

	# Explicit small height (not L['low']'s 46px row height) so the larger
	# font stays vertically centered tight against header_y instead of
	# expanding downward into the first data row below it (found from
	# direct user feedback: "LOW HIGH" was cutting into the temps).
	f_header = assets.font('Star4000-Large', 18)
	header_box_low = {'x': L['low']['x'], 'y': L['header_y'], 'w': L['low']['w'], 'h': 20}
	header_box_high = {'x': L['high']['x'], 'y': L['header_y'], 'w': L['high']['w'], 'h': 20}
	assets.draw_text(draw, 'LOW', header_box_low, f_header, assets.YELLOW, 'center')
	assets.draw_text(draw, 'HIGH', header_box_high, f_header, assets.YELLOW, 'center')

	for i, row in enumerate(rows[:L['visible_rows']]):
		y = L['first_row_y'] + i * L['row_height']
		assets.draw_text(draw, row['city'], {**L['city'], 'y': y}, f_city, assets.YELLOW, 'left')
		assets.draw_text(draw, row['low'], {**L['low'], 'y': y}, f_temp, assets.WHITE, 'center')
		assets.draw_text(draw, row['high'], {**L['high'], 'y': y}, f_temp, assets.WHITE, 'center')
		icon_g = L['icon']
		assets.paste_icon(img, 'regional-maps', row['icon'], {
			'x': icon_g['x'], 'y': y + icon_g['y_offset'], 'w': icon_g['w'], 'h': icon_g['h'],
		})

	return img
