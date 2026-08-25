from renderer import assets
from renderer.layout import SPC_OUTLOOK as L


def render(outlook_image):
	"""outlook_image: PIL Image from adapters.spc.fetch_outlook, already
	sized to L['box']'s dimensions."""
	img = assets.load_template('spc_outlook').copy()
	box = L['box']
	img.paste(outlook_image, (box['x'], box['y']))
	return img
