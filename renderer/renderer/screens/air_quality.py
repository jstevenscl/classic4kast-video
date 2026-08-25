from renderer import assets
from renderer.layout import AIR_QUALITY as L


def render(data):
	"""data: {'aqi', 'category', 'color', 'driver'} from
	adapters.air_quality.fetch_air_quality. Reuses regional_map_blank's
	chrome (no baked title -- see screens/loading.py), same pattern as
	tide_info.py/marine_forecast.py for a screen with no real WS4KP
	screenshot to extract from."""
	img = assets.load_template('regional_map_blank').copy()
	draw = assets.new_draw(img)
	f_title = assets.font('Star4000', 30)
	f_aqi = assets.font('Star4000-Large', 64)
	f_category = assets.font('Star4000', 28)
	f_driver = assets.font('Star4000-Small', 20)

	assets.draw_text(draw, 'Air', L['title_top'], f_title, assets.YELLOW, 'left')
	assets.draw_text(draw, 'Quality', L['title_bottom'], f_title, assets.YELLOW, 'left')

	box = L['box']

	def box_at(field):
		g = L[field]
		return {'x': box['x'] + g['x_off'], 'y': box['y'] + g['y_off'], 'w': g['w'], 'h': g['h']}

	assets.draw_text(draw, str(data['aqi']), box_at('aqi_value'), f_aqi, data['color'], 'center')
	assets.draw_text(draw, data['category'], box_at('category'), f_category, assets.WHITE, 'center')
	if data.get('driver'):
		assets.draw_text(draw, f"Primary pollutant: {data['driver']}", box_at('driver'), f_driver, assets.WHITE, 'center')

	return img
