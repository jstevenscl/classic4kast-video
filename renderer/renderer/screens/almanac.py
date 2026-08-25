from renderer import assets
from renderer.layout import ALMANAC as L


def render(data):
	"""data: {'days': [{'day_name', 'sunrise', 'sunset'}, ...] (2 entries,
	today + tomorrow -- matches WS4KP's widescreen 2-column layout),
	'moon_events': [{'type', 'date', 'icon'}, ...] (4 entries) } from
	adapters.astro."""
	img = assets.load_template('almanac').copy()
	draw = assets.new_draw(img)
	f_header = assets.font('Star4000', 24)
	f_time = assets.font('Star4000', 24)
	f_moon_type = assets.font('Star4000', 24)
	f_moon_date = assets.font('Star4000', 24)

	for i, day in enumerate(data['days'][:2]):
		header_box = {'x': L['day_header']['x'][i], 'y': L['day_header']['y'], 'w': L['day_header']['w'], 'h': L['day_header']['h']}
		rise_box = {'x': L['rise']['x'][i], 'y': L['rise']['y'], 'w': L['rise']['w'], 'h': L['rise']['h']}
		set_box = {'x': L['set']['x'][i], 'y': L['set']['y'], 'w': L['set']['w'], 'h': L['set']['h']}
		assets.draw_text(draw, day['day_name'], header_box, f_header, assets.YELLOW, 'center')
		assets.draw_text(draw, day['sunrise'], rise_box, f_time, assets.WHITE, 'center')
		assets.draw_text(draw, day['sunset'], set_box, f_time, assets.WHITE, 'center')

	for i, event in enumerate(data['moon_events'][:L['moon_cols']]):
		spacing = i * L['moon_type']['col_spacing']
		type_box = {'x': L['moon_type']['x'] + spacing, 'y': L['moon_type']['y'], 'w': L['moon_type']['w'], 'h': L['moon_type']['h']}
		date_box = {'x': L['moon_date']['x'] + spacing, 'y': L['moon_date']['y'], 'w': L['moon_date']['w'], 'h': L['moon_date']['h']}
		icon_box = {
			'x': L['moon_icon']['x'] + spacing, 'y': L['moon_icon']['y'],
			'w': L['moon_icon']['w'], 'h': L['moon_icon']['h'],
		}
		assets.draw_text(draw, event['type'], type_box, f_moon_type, assets.WHITE, 'center')
		assets.draw_text(draw, event['date'], date_box, f_moon_date, assets.WHITE, 'center')
		assets.paste_icon(img, 'moon-phases', event['icon'], icon_box)

	return img
