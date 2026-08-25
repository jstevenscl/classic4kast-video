from renderer import assets
from renderer.layout import EXTENDED_FORECAST as L

# WS4KP's own Lo color ($extended-low: #8080FF) is a blue-on-blue read
# against this screen's actual background art here (sampled live:
# (20,19,200), a deep saturated blue) -- real contrast on paper, but found
# from direct user feedback to visually blend at this size. Lightened well
# past the source value for real legibility rather than a byte-for-byte
# color match; Hi keeps WS4KP's own yellow (already high-contrast against
# blue).
LO_LABEL_COLOR = (190, 210, 255)
HI_LABEL_COLOR = assets.YELLOW

# Real forecast condition text ("Chance Showers And Thunderstorms") routinely
# overflows the 155px-wide condition box at any readable font size -- this
# used to be handled by truncating the STRING to 20 chars and drawing one
# line, which cut real forecasts off mid-word. Wraps by word instead (same
# assets.wrap_text helper local_forecast.py/marine_forecast.py already use)
# across up to 3 lines, which is what the 74px-tall box actually has room
# for at this font size (found from direct user feedback: cut-off text was
# a readability regression, not the existing single-line design working as
# intended).
_COND_LINE_HEIGHT = 22


def _draw_wrapped(draw, text, box, font_obj, color):
	lines = assets.wrap_text(draw, text, font_obj, box['w'])
	max_lines = max(1, box['h'] // _COND_LINE_HEIGHT)
	lines = lines[:max_lines]
	total_h = len(lines) * _COND_LINE_HEIGHT
	start_y = box['y'] + (box['h'] - total_h) // 2
	for i, line in enumerate(lines):
		line_box = {'x': box['x'], 'y': start_y + i * _COND_LINE_HEIGHT, 'w': box['w'], 'h': _COND_LINE_HEIGHT}
		assets.draw_text(draw, line, line_box, font_obj, color, 'center')


def render(days):
	"""days: list of dicts from adapters.*.fetch_extended_forecast (date,
	icon, condition, lo, hi)."""
	img = assets.load_template('extended_forecast').copy()
	draw = assets.new_draw(img)
	f_date = assets.font('Star4000-Large', 20)
	f_cond = assets.font('Star4000', 16)
	f_temp = assets.font('Star4000-Large', 20)
	f_label = assets.font('Star4000-Small', 20)

	for i, day in enumerate(days[:L['visible_cols']]):
		col_x = L['first_col_x'] + i * L['col_width']
		col_y = L['col_y']

		def box(field):
			g = L[field]
			return {'x': col_x + g['x_off'], 'y': col_y + g['y_off'], 'w': g['w'], 'h': g['h']}

		assets.draw_text(draw, day['date'], box('date'), f_date, assets.YELLOW, 'center')
		_draw_wrapped(draw, day['condition'], box('condition'), f_cond, assets.WHITE)
		assets.draw_text(draw, 'Lo', box('lo_label'), f_label, LO_LABEL_COLOR, 'center')
		assets.draw_text(draw, 'Hi', box('hi_label'), f_label, HI_LABEL_COLOR, 'center')
		assets.draw_text(draw, day['lo'], box('lo'), f_temp, assets.WHITE, 'center')
		assets.draw_text(draw, day['hi'], box('hi'), f_temp, assets.WHITE, 'center')

		icon_g = L['icon']
		assets.paste_icon(img, 'current-conditions', day['icon'], {
			'x': col_x + icon_g['x_off'], 'y': col_y + icon_g['y_off'], 'w': icon_g['w'], 'h': icon_g['h'],
		})

	return img
