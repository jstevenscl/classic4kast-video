from renderer import assets
from renderer.layout import OUTLOOK_30DAY as L


def render(data):
	"""data: {'valid_period', 'temperature', 'temperature_prob',
	'precipitation', 'precipitation_prob'} from
	adapters.outlook_30day.fetch_30day_outlook. Reuses regional_map_blank's
	chrome (no baked title -- see screens/loading.py); real WS4KP+ titles
	this "Almanac" / "Outlook"."""
	img = assets.load_template('regional_map_blank').copy()
	draw = assets.new_draw(img)
	f_title = assets.font('Star4000', 30)
	f_period = assets.font('Star4000-Small', 22)
	f_label = assets.font('Star4000', 26)

	assets.draw_text(draw, 'Almanac', L['title_top'], f_title, assets.YELLOW, 'left')
	assets.draw_text(draw, 'Outlook', L['title_bottom'], f_title, assets.YELLOW, 'left')

	box = L['box']

	def box_at(field):
		g = L[field]
		return {'x': box['x'] + g['x_off'], 'y': box['y'] + g['y_off'], 'w': g['w'], 'h': g['h']}

	assets.draw_text(draw, data['valid_period'], box_at('period'), f_period, assets.WHITE, 'center')

	temp_text = (
		f"Temperature: {data['temperature']} ({data['temperature_prob']}%)"
		if data.get('temperature') else 'Temperature: No data'
	)
	assets.draw_text(draw, temp_text, box_at('temperature_label'), f_label, assets.YELLOW, 'left')

	precip_text = (
		f"Precipitation: {data['precipitation']} ({data['precipitation_prob']}%)"
		if data.get('precipitation') else 'Precipitation: No data'
	)
	assets.draw_text(draw, precip_text, box_at('precipitation_label'), f_label, assets.WHITE, 'left')

	return img
