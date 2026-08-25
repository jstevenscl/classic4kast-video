from renderer import assets
from renderer.layout import LOCAL_FORECAST as L

LINE_HEIGHT = 40


def render(data):
	"""data: {'period_name', 'text'} from adapters.nws.fetch_local_forecast."""
	img = assets.load_template('local_forecast').copy()
	draw = assets.new_draw(img)
	font_obj = assets.font('Star4000', 28)

	box = L['box']
	text = f"{data['period_name']}...{data['text']}" if data.get('text') else data.get('period_name', '')
	lines = assets.wrap_text(draw, text, font_obj, box['w'] - 20)
	max_lines = box['h'] // LINE_HEIGHT
	for i, line in enumerate(lines[:max_lines]):
		draw.text((box['x'] + 10, box['y'] + 10 + i * LINE_HEIGHT), line, font=font_obj, fill=assets.WHITE)

	return img
