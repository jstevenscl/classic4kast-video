"""
Live per-frame overlays: the real WS4KP clock and scrolling advisory ticker,
drawn fresh onto a base screen image every frame using the SAME font assets
and pinned coordinates the static screens use (see layout.CLOCK_*/ADVISORY_BANNER).

This is the piece that a baked-and-looped clip fundamentally cannot do: a
looped video is a fixed sequence of frozen frames, so no render speed makes
its clock tick continuously. These functions instead get called once per
output frame by live_stream.py, which feeds a persistent ffmpeg process
directly (never bakes a loop) -- that's what makes the clock/ticker genuinely
live instead of a stale sample re-shown on repeat.
"""
from datetime import datetime

from renderer import assets
from renderer.layout import ADVISORY_BANNER, CLOCK_COLOR, CLOCK_DATE, CLOCK_FONT, CLOCK_TIME

TICKER_SPEED_PX_PER_SEC = 60


def draw_clock(img, tz):
	"""Draws the real WS4KP clock (time + date, Star4000-Small 32px, white)
	at its real pinned position. Called every output frame with the current
	wall-clock time -- this is what makes it tick in real time instead of
	being frozen at whatever moment the base screen was rendered."""
	draw = assets.new_draw(img)
	font_obj = assets.font(*CLOCK_FONT)
	now = datetime.now(tz)
	time_text = now.strftime('%I:%M:%S %p').lstrip('0')
	date_text = now.strftime('%a %b %d').upper()
	assets.draw_text(draw, time_text, CLOCK_TIME, font_obj, CLOCK_COLOR, align='center')
	date_box = {**CLOCK_DATE, 'y': CLOCK_DATE['y'] + 22}
	assets.draw_text(draw, date_text, date_box, font_obj, CLOCK_COLOR, align='center')


def draw_ticker(img, alert, elapsed_seconds, box=ADVISORY_BANNER):
	"""Draws the advisory banner as a genuinely scrolling ticker: the body
	text's x position is computed from real elapsed time
	(x = box_right - pixels_per_second * elapsed_time, wrapped once the text
	has fully scrolled past), matching WS4KP's own CSS transform-based scroll
	model instead of faking motion with word-wrap. Draws nothing if there's
	no active alert -- matches WS4KP's own collapse-when-clear behavior.
	"""
	if not alert:
		return
	draw = assets.new_draw(img)
	draw.rectangle([box['x'], box['y'], box['x'] + box['w'], box['y'] + box['h']], fill=box['bg'])
	draw.line([box['x'], box['y'], box['x'] + box['w'], box['y']], fill=(0, 0, 0), width=2)

	f_header = assets.font('Star4000-Small', 26)
	f_body = assets.font('Star4000', 32)

	event = alert.get('event', 'Weather Advisory')
	bbox = draw.textbbox((0, 0), event, font=f_header)
	header_x = box['x'] + (box['w'] - (bbox[2] - bbox[0])) / 2
	draw.text((header_x, box['y'] - 10), event, font=f_header, fill=assets.WHITE)

	body_text = (alert.get('description') or event).replace('\n', ' ').strip()
	body_bbox = draw.textbbox((0, 0), body_text, font=f_body)
	text_w = body_bbox[2] - body_bbox[0]

	# Real scroll: text enters from the right edge, exits past the left edge,
	# then loops -- cycle length is one full text-width-plus-screen-width
	# traversal, computed from real elapsed time so it never stutters or
	# jumps regardless of how render timing varies frame to frame.
	cycle = box['w'] + text_w
	offset = (elapsed_seconds * TICKER_SPEED_PX_PER_SEC) % cycle
	x = box['x'] + box['w'] - offset
	body_y = box['y'] + 24
	draw.text((x, body_y), body_text, font=f_body, fill=assets.WHITE)
