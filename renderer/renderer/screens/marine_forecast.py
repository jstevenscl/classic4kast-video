from renderer import assets
from renderer.layout import MARINE_FORECAST as L

LINE_HEIGHT = 40


def render(data):
	"""data: {'zone_name', 'period_name', 'text'} from adapters.nws.fetch_marine_forecast.

	Uses regional_map_blank's chrome (no baked title, see screens/loading.py
	for the same technique) since marine forecast doesn't exist in upstream
	WS4KP -- no real screenshot to extract a title-baked template from.
	"""
	img = assets.load_template('regional_map_blank').copy()
	draw = assets.new_draw(img)
	f_title = assets.font('Star4000', 30)
	f_body = assets.font('Star4000', 28)

	assets.draw_text(draw, 'Marine', L['title_top'], f_title, assets.YELLOW, 'left')
	assets.draw_text(draw, 'Forecast', L['title_bottom'], f_title, assets.YELLOW, 'left')

	box = L['box']
	period = data.get('period_name')
	body = data.get('text', '')
	text = f"{period}...{body}" if period and body else body
	lines = assets.wrap_text(draw, text, f_body, box['w'] - 20)
	max_lines = box['h'] // LINE_HEIGHT
	for i, line in enumerate(lines[:max_lines]):
		draw.text((box['x'] + 10, box['y'] + 10 + i * LINE_HEIGHT), line, font=f_body, fill=assets.WHITE)

	return img
