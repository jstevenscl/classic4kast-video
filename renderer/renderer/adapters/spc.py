"""
SPC (Storm Prediction Center) Day 1 Convective Outlook adapter. Unlike
radar, this is a national forecast product issued only a few times a day
(not a fast-changing local time series -- see project notes on why this
screen stays static while radar animates). Real, live-confirmed URL:
https://www.spc.noaa.gov/products/outlook/day1otlk.png (the smaller
'_sm' variant exists too but is too low-res to read at our display size).

No documented crop/georeferencing exists for this image the way IEM
publishes a .wld file for the radar composite -- SPC's own map already
bakes in its legend, issue time, and forecaster attribution. We show the
full national map scaled to fit rather than guess at a local-area crop
that could end up misaligned.
"""
from io import BytesIO

import httpx
from PIL import Image

UA = {'User-Agent': 'classic4kast (self-hosted weather renderer, personal use)'}
URL = 'https://www.spc.noaa.gov/products/outlook/day1otlk.png'


async def fetch_outlook(box_size):
	async with httpx.AsyncClient(headers=UA) as client:
		r = await client.get(URL, timeout=15)
		r.raise_for_status()
	img = Image.open(BytesIO(r.content)).convert('RGB')
	img.thumbnail(box_size, Image.LANCZOS)
	out = Image.new('RGB', box_size, (255, 255, 255))
	out.paste(img, ((box_size[0] - img.width) // 2, (box_size[1] - img.height) // 2))
	return out
