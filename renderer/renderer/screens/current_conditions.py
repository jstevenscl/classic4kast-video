from renderer import assets
from renderer.layout import CURRENT_CONDITIONS as L


def render(data):
	"""data: dict from adapters.nws.fetch_current_conditions or
	adapters.ec.fetch_current_conditions (same field shape)."""
	img = assets.load_template('current_conditions').copy()
	draw = assets.new_draw(img)

	f_large = assets.font('Star4000-Large', 32)
	f_ext = assets.font('Star4000-Extended', 32)
	f_small = assets.font('Star4000-Large', 20)

	# Icon drawn first so any text below it (esp. wind) always paints on
	# top and stays legible even where their boxes come close -- found from
	# direct user feedback that the icon was covering the wind value.
	assets.paste_icon(img, 'current-conditions', data['icon'], L['icon'])

	assets.draw_text(draw, data['temp'], L['temp'], f_large, assets.WHITE, 'center')
	assets.draw_text(draw, data['condition'], L['condition'], f_ext, assets.WHITE, 'center')
	assets.draw_text(draw, data['humidity'], L['humidity'], f_small, assets.WHITE, 'right')
	assets.draw_text(draw, data['dewpoint'], L['dewpoint'], f_small, assets.WHITE, 'right')
	assets.draw_text(draw, data['ceiling'], L['ceiling'], f_small, assets.WHITE, 'right')
	assets.draw_text(draw, data['visibility'], L['visibility'], f_small, assets.WHITE, 'right')
	assets.draw_text(draw, data['pressure'], L['pressure'], f_small, assets.WHITE, 'right')
	assets.draw_text(draw, data['wind'], L['wind'], f_ext, assets.WHITE, 'right')
	assets.draw_text(draw, data['heatindex'], L['heatindex'], f_small, assets.WHITE, 'right')
	# Real WS4KP truncates this to a fixed 20-char limit at a fixed font
	# size (confirmed live against its own currentweather.mjs), not dynamic
	# font shrinking -- an earlier attempt at this same overflow problem
	# shrunk the font instead, which just made this one field visibly
	# smaller/inconsistent with every other label on the same screen
	# (found from direct user feedback). Truncation itself happens at the
	# data source (nws.py/ec.py/open_meteo.py's 'location' field).
	assets.draw_text(draw, data['location'], L['location'], f_small, assets.YELLOW, 'left')

	return img
