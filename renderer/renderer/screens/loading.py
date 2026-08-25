"""
Full-canvas "please wait" screen shown by the on-demand launcher while a
cold channel's real render pipeline spins up (data fetch + first frame +
first HLS segments, a few real seconds) -- so a viewer sees the same
WeatherStar look immediately instead of a blank/broken player. Reuses
regional_map_blank's real chrome (gradient + header band, no baked title)
rather than a from-scratch background, so it's visually consistent with
every other screen.
"""
from renderer import assets

CANVAS_W, CANVAS_H = 854, 480


def render(city_name=None):
	img = assets.load_template('regional_map_blank').copy()
	draw = assets.new_draw(img)

	f_title = assets.font('Star4000-Extended', 46)
	f_sub = assets.font('Star4000', 26)

	assets.draw_text(
		draw, 'WEATHER', {'x': 0, 'y': 190, 'w': CANVAS_W, 'h': 56}, f_title, assets.YELLOW, 'center',
	)
	assets.draw_text(
		draw, 'LOADING', {'x': 0, 'y': 250, 'w': CANVAS_W, 'h': 56}, f_title, assets.YELLOW, 'center',
	)
	if city_name:
		assets.draw_text(
			draw, city_name, {'x': 0, 'y': 320, 'w': CANVAS_W, 'h': 32}, f_sub, assets.WHITE, 'center',
		)

	return img
