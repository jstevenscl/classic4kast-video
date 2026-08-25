from renderer import assets
from renderer.layout import REGIONAL_OBSERVATIONS as L


def render(rows):
	"""rows: list of dicts from adapters.nws.fetch_regional_observations
	(location, temp, weather, wind -- 'like' is dropped, matching WS4KP's own
	widescreen layout, which hides that column at this resolution)."""
	img = assets.load_template('regional_observations').copy()
	draw = assets.new_draw(img)
	f = assets.font('Star4000', 26)

	for i, row in enumerate(rows[:L['visible_rows']]):
		y = L['first_row_y'] + i * L['row_height']
		assets.draw_text(draw, row['location'], {**L['location'], 'y': y}, f, assets.WHITE, 'left')
		assets.draw_text(draw, row['temp'], {**L['temp'], 'y': y}, f, assets.WHITE, 'left')
		assets.draw_text(draw, row['weather'], {**L['weather'], 'y': y}, f, assets.WHITE, 'left')
		assets.draw_text(draw, row['wind'], {**L['wind'], 'y': y}, f, assets.WHITE, 'left')

	return img
