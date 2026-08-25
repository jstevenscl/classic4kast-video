from renderer import assets
from renderer.layout import HOURLY_GRAPH as L

TEMP_COLOR = (255, 40, 40)
DEWPOINT_COLOR = (40, 180, 40)
CLOUD_COLOR = (220, 220, 220)
PRECIP_COLOR = (60, 220, 220)
NUM_X_LABELS = 6  # real WS4KP shows ~36hrs with day-abbreviated labels at midnight crossings, confirmed live


def _nice_ticks(lo, hi, count=4):
	"""4 evenly-spaced labels spanning the real data range -- matches
	WS4KP's own axis (confirmed live: values like 103/89/76/62, an even
	spread of the true min/max, not rounded-to-10 ticks)."""
	if hi == lo:
		hi = lo + 1
	step = (hi - lo) / (count - 1)
	return [round(hi - step * i) for i in range(count)]


def _plot(draw, box, values, lo, hi, color):
	n = len(values)
	if n < 2:
		return
	def point(i, v):
		x = box['x'] + (box['w'] - 1) * i / (n - 1)
		frac = 0 if hi == lo else (v - lo) / (hi - lo)
		y = box['y'] + box['h'] - 1 - frac * (box['h'] - 1)
		return (x, y)
	pts = [point(i, v) for i, v in enumerate(values)]
	draw.line(pts, fill=color, width=2, joint='curve')


def render(points):
	"""points: list of dicts from adapters.nws.fetch_hourly_graph (time,
	hour_label, is_day_boundary, day_label, temp, dewpoint, precip, cloud)."""
	img = assets.load_template('hourly_graph').copy()
	draw = assets.new_draw(img)
	box = L['chart']
	f_label = assets.font('Star4000-Small', 20)

	draw.rectangle([box['x'], box['y'], box['x'] + box['w'], box['y'] + box['h']], fill=(20, 30, 70))

	temps = [p['temp'] for p in points]
	dewpoints = [p['dewpoint'] for p in points]
	lo, hi = min(temps + dewpoints), max(temps + dewpoints)
	ticks = _nice_ticks(lo, hi)

	for i, tick in enumerate(ticks):
		frac = i / (len(ticks) - 1)
		y = box['y'] + frac * box['h']
		assets.draw_text(
			draw, f'{tick}°', {'x': 0, 'y': y - 12, 'w': L['y_axis_label_x'] - 10, 'h': 24}, f_label, assets.YELLOW, 'right',
		)

	_plot(draw, box, [p['cloud'] for p in points], 0, 100, CLOUD_COLOR)
	_plot(draw, box, [p['precip'] for p in points], 0, 100, PRECIP_COLOR)
	_plot(draw, box, temps, lo, hi, TEMP_COLOR)
	_plot(draw, box, dewpoints, lo, hi, DEWPOINT_COLOR)

	n = len(points)
	step = max(1, n // NUM_X_LABELS)
	# Evenly-spaced label indices, PLUS every real day-boundary index forced
	# in -- picking only evenly-spaced samples could skip right over
	# midnight, silently dropping the day abbreviation real WS4KP always
	# shows at a day change (found from direct user feedback: ours never
	# showed one at all over a 36hr span).
	candidate_indices = sorted(set(range(0, n, step)) | {i for i, p in enumerate(points) if p['is_day_boundary']})
	day_boundary_indices = {i for i, p in enumerate(points) if p['is_day_boundary']}

	# Forcing the day-boundary index in could land it right next to a
	# regular evenly-spaced index, close enough on screen that the two
	# labels visually run together (found from direct user feedback: "FRI
	# 12 2" showing squished). Enforce a real minimum pixel gap between
	# consecutive labels, always keeping the day-boundary one over its
	# non-boundary neighbor when they'd otherwise collide.
	min_gap_px = 70
	label_indices = []
	for i in candidate_indices:
		x = box['x'] + (box['w'] - 1) * i / max(1, n - 1)
		if label_indices:
			prev_i = label_indices[-1]
			prev_x = box['x'] + (box['w'] - 1) * prev_i / max(1, n - 1)
			if x - prev_x < min_gap_px:
				if i in day_boundary_indices and prev_i not in day_boundary_indices:
					label_indices[-1] = i  # replace the too-close neighbor with the more informative day-boundary label
				continue
		label_indices.append(i)

	first_day = points[0]['day_label']
	last_shown_day = first_day
	for i in label_indices:
		p = points[i]
		# Show the day abbreviation on the first label of any day that
		# differs from the last one actually drawn -- not just an exact
		# midnight-hour match, so a label landing at e.g. "Fri 3A" (not
		# "Fri 12A") still carries the day prefix.
		if p['day_label'] != last_shown_day:
			label = f"{p['day_label']} {p['hour_label']}"
			last_shown_day = p['day_label']
		else:
			label = p['hour_label']
		x = box['x'] + (box['w'] - 1) * i / max(1, n - 1)
		assets.draw_text(
			draw, label, {'x': x - 40, 'y': L['x_axis_label_y'], 'w': 80, 'h': 24}, f_label, assets.YELLOW, 'center',
		)

	return img
