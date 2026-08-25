from renderer import assets
from renderer.layout import TIDE_INFO as L


def render(data):
	"""data: {'station_name', 'tides': [{'type', 'time', 'height_ft'}, ...]}
	from adapters.tides.fetch_tide_info. Reuses regional_map_blank's chrome
	(no baked title, see screens/loading.py for the same technique) --
	real WS4KP+ titles this 'Almanac' / 'Tides' (confirmed live against its
	own twc3.js DrawTitleText call)."""
	img = assets.load_template('regional_map_blank').copy()
	draw = assets.new_draw(img)
	f_title = assets.font('Star4000', 30)
	f_station = assets.font('Star4000-Small', 20)
	f_row = assets.font('Star4000', 24)

	assets.draw_text(draw, 'Almanac', L['title_top'], f_title, assets.YELLOW, 'left')
	assets.draw_text(draw, 'Tides', L['title_bottom'], f_title, assets.YELLOW, 'left')

	box = L['box']

	def box_at(y_off, h):
		return {'x': box['x'], 'y': box['y'] + y_off, 'w': box['w'], 'h': h}

	station_box = box_at(L['station_name']['y_off'], L['station_name']['h'])
	assets.draw_text(draw, data['station_name'][:40], station_box, f_station, assets.WHITE, 'center')

	row_h = L['row_height']
	for i, tide in enumerate(data['tides'][:4]):
		row_box = box_at(L['first_row_y_off'] + i * row_h, row_h)
		label_box = {'x': row_box['x'] + 30, 'y': row_box['y'], 'w': 160, 'h': row_h}
		time_box = {'x': row_box['x'] + 200, 'y': row_box['y'], 'w': 140, 'h': row_h}
		height_box = {'x': row_box['x'] + 340, 'y': row_box['y'], 'w': 120, 'h': row_h}
		color = assets.YELLOW if tide['type'] == 'High' else assets.WHITE
		assets.draw_text(draw, tide['type'], label_box, f_row, color, 'left')
		assets.draw_text(draw, tide['time'], time_box, f_row, assets.WHITE, 'left')
		assets.draw_text(draw, f"{tide['height_ft']} ft", height_box, f_row, assets.WHITE, 'left')

	return img
