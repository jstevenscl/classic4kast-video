from datetime import datetime, timedelta

from renderer import assets
from renderer.adapters import regional_map
from renderer.layout import REGIONAL_MAP as L


def render(basemap_img, stations, lat, lon, span_degrees, tz):
	"""Same map style as screens.regional_map_forecast, titled 'Forecast for
	<Day> Night' with tomorrow night's low temp/icon -- the companion page
	real WS4KP+ shows right after the day forecast map (see
	adapters.nws.fetch_regional_map_forecast_night's docstring)."""
	img = assets.load_template('regional_map_blank').copy()
	draw = assets.new_draw(img)
	f_title = assets.font('Star4000', 30)
	tomorrow = datetime.now(tz) + timedelta(days=1)
	assets.draw_text(draw, 'Forecast', L['title_top'], f_title, assets.YELLOW, 'left')
	assets.draw_text(draw, f'for {tomorrow.strftime("%A")} Night', L['title_bottom'], f_title, assets.YELLOW, 'left')

	box = L['box']
	img.paste(basemap_img, (box['x'], box['y']))
	regional_map.render_markers(img, box, stations, lat, lon, span_degrees)
	return img
