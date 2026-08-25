"""
Shared font/icon/drawing helpers. Fonts ship as .woff (WS4KP's own format,
web fonts) -- Pillow needs .ttf/.otf, so these get converted once at
container build time (see Dockerfile), not on every render.
"""
import os
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

_DIR = os.path.dirname(__file__)
FONTS_DIR = os.path.join(_DIR, 'fonts')
ICONS_DIR = os.path.join(_DIR, 'icons_all')
TEMPLATES_DIR = os.path.join(_DIR, 'templates')
DATA_DIR = os.path.join(_DIR, 'data')

WHITE = (255, 255, 255)
YELLOW = (255, 255, 0)


@lru_cache(maxsize=None)
def font(name, size):
	"""name: 'Star4000' | 'Star4000-Large' | 'Star4000-Extended' | 'Star4000-Small'"""
	path = os.path.join(FONTS_DIR, f'{name}.ttf')
	return ImageFont.truetype(path, size)


@lru_cache(maxsize=None)
def load_template(screen_name):
	return Image.open(os.path.join(TEMPLATES_DIR, f'{screen_name}.png')).convert('RGB')


@lru_cache(maxsize=None)
def _load_icon_native(set_name, icon_name):
	path = os.path.join(ICONS_DIR, set_name, f'{icon_name}.gif')
	if not os.path.exists(path):
		path = os.path.join(ICONS_DIR, set_name, 'No-Data.gif')
	return Image.open(path).convert('RGBA')


def paste_icon(img, set_name, icon_name, box):
	"""box: {'x','y','w','h'}. set_name: 'current-conditions' | 'regional-maps' |
	'moon-phases'. Icons are NOT stretched to fill the box -- confirmed live
	against real WS4KP (its <img> is sized to the icon's own native pixel
	dimensions, not a fixed container box) -- so this scales preserving
	aspect ratio (contain-fit) and centers within the box instead. Icon
	native aspect ratios vary a lot (square suns vs. wide partly-cloudy
	glyphs vs. tall moon phases); stretching them all into one fixed box was
	visibly squishing the non-square ones."""
	icon = _load_icon_native(set_name, icon_name)
	scale = min(box['w'] / icon.width, box['h'] / icon.height)
	size = (max(1, round(icon.width * scale)), max(1, round(icon.height * scale)))
	resized = icon.resize(size)
	offset = (box['x'] + (box['w'] - size[0]) // 2, box['y'] + (box['h'] - size[1]) // 2)
	img.paste(resized, offset, resized)


def draw_text(draw, text, box, font_obj, color, align='left'):
	"""box: {'x','y','w','h'}. Draws with a 1px black outline in every
	direction, matching WS4KP's own text-shadow style."""
	bbox = draw.textbbox((0, 0), text, font=font_obj)
	tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
	if align == 'center':
		tx = box['x'] + (box['w'] - tw) / 2
	elif align == 'right':
		tx = box['x'] + box['w'] - tw
	else:
		tx = box['x']
	ty = box['y'] + (box['h'] - th) / 2 - bbox[1]
	for ox, oy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
		draw.text((tx + ox, ty + oy), text, font=font_obj, fill=(0, 0, 0))
	draw.text((tx, ty), text, font=font_obj, fill=color)


def new_draw(img):
	return ImageDraw.Draw(img)


def draw_advisory_banner(img, alert, box):
	"""Draws the bottom advisory bar matching WS4KP's real .scroll.hazard
	styling (colors/fonts/layout confirmed live against the actual element,
	not guessed): rgb(112,35,35) background, centered "Star4000 Small 26px"
	event-name header, "Star4000 32px" body text.

	`alert`: {'event':, 'description':} from adapters.nws.fetch_active_alerts,
	or None/falsy -- draws nothing, matching WS4KP's own collapse-when-
	nothing-active behavior (see layout.ADVISORY_BANNER).

	WS4KP scrolls the body text horizontally via a CSS transform animation;
	a baked static frame can't reproduce that motion without either faking
	it badly (tried, looked worse) or generating a real multi-frame scroll
	sequence (real added complexity for a bottom-of-screen advisory text).
	Word-wrapping the real text across the available height instead is the
	honest tradeoff: shows genuine live content, no motion, doesn't
	pretend to be something it isn't."""
	if not alert:
		return
	draw = new_draw(img)
	draw.rectangle([box['x'], box['y'], box['x'] + box['w'], box['y'] + box['h']], fill=box['bg'])
	draw.line([box['x'], box['y'], box['x'] + box['w'], box['y']], fill=(0, 0, 0), width=2)

	f_header = font('Star4000-Small', 26)
	f_body = font('Star4000', 22)

	event = alert.get('event', 'Weather Advisory')
	bbox = draw.textbbox((0, 0), event, font=f_header)
	header_x = box['x'] + (box['w'] - (bbox[2] - bbox[0])) / 2
	draw.text((header_x, box['y'] - 10), event, font=f_header, fill=WHITE)

	body_top = box['y'] + 20
	body_lines = wrap_text(draw, (alert.get('description') or '').replace('\n', ' '), f_body, box['w'] - 20)
	line_height = 26
	max_lines = (box['h'] - 20 - (body_top - box['y'])) // line_height
	for i, line in enumerate(body_lines[:max_lines]):
		draw.text((box['x'] + 10, body_top + i * line_height), line, font=f_body, fill=WHITE)


def wrap_text(draw, text, font_obj, max_width):
	words = text.split()
	lines, current = [], ''
	for word in words:
		trial = f'{current} {word}'.strip()
		if draw.textbbox((0, 0), trial, font=font_obj)[2] <= max_width:
			current = trial
		else:
			if current:
				lines.append(current)
			current = word
	if current:
		lines.append(current)
	return lines
