from renderer import assets
from renderer.adapters import regional_map
from renderer.layout import REGIONAL_MAP as L


def render(basemap_img, stations, lat, lon, span_degrees):
	"""basemap_img/stations: from adapters.regional_map.fetch_map."""
	img = assets.load_template('regional_map_blank').copy()
	draw = assets.new_draw(img)
	f_title = assets.font('Star4000', 30)
	assets.draw_text(draw, 'Regional', L['title_top'], f_title, assets.YELLOW, 'left')
	assets.draw_text(draw, 'Observations', L['title_bottom'], f_title, assets.YELLOW, 'left')

	box = L['box']
	img.paste(basemap_img, (box['x'], box['y']))
	regional_map.render_markers(img, box, stations, lat, lon, span_degrees)
	return img
