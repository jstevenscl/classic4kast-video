from renderer import assets
from renderer.layout import RADAR as L


def render(frame_image, city_name=None):
	"""frame_image: one PIL Image from adapters.radar.fetch_radar_frames,
	already sized to L['box']'s dimensions (the geo-reference graticule is
	baked into it already -- see adapters.radar._draw_geo_reference). Marks
	the box center with a crosshair -- the crop is always centered on the
	target city (see adapters.radar._crop_and_composite), so center is
	always correct without needing per-city marker coordinates."""
	img = assets.load_template('radar').copy()
	box = L['box']
	img.paste(frame_image, (box['x'], box['y']))
	draw = assets.new_draw(img)
	cx, cy = box['x'] + box['w'] // 2, box['y'] + box['h'] // 2
	r = 5
	draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 255), width=2)
	draw.line([cx - 10, cy, cx - r, cy], fill=(255, 255, 255), width=2)
	draw.line([cx + r, cy, cx + 10, cy], fill=(255, 255, 255), width=2)
	draw.line([cx, cy - 10, cx, cy - r], fill=(255, 255, 255), width=2)
	draw.line([cx, cy + r, cx, cy + 10], fill=(255, 255, 255), width=2)
	if city_name:
		f = assets.font('Star4000-Small', 18)
		assets.draw_text(draw, city_name, {'x': cx - 60, 'y': cy + 10, 'w': 120, 'h': 24}, f, assets.YELLOW, 'center')
	return img
