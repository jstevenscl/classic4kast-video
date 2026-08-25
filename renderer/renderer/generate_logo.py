"""
One-off generator for the default WeatherStar channel logo (sun-behind-cloud
on the WS4KP navy/yellow palette) -- run once at build/dev time, output
checked in as renderer/assets/static/logo.png and served statically by
on_demand_server.py at GET /weatherstar/logo.png. Not run per-request.
"""
from PIL import Image, ImageDraw

SIZE = 512
NAVY = (10, 24, 79)
NAVY_LIGHT = (26, 52, 128)
YELLOW = (255, 204, 0)
WHITE = (255, 255, 255)
CLOUD_SHADOW = (200, 210, 230)


def generate():
    img = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Rounded-square badge background, subtle vertical gradient (navy -> lighter navy)
    for y in range(SIZE):
        t = y / SIZE
        r = int(NAVY[0] + (NAVY_LIGHT[0] - NAVY[0]) * t)
        g = int(NAVY[1] + (NAVY_LIGHT[1] - NAVY[1]) * t)
        b = int(NAVY[2] + (NAVY_LIGHT[2] - NAVY[2]) * t)
        draw.line([(0, y), (SIZE, y)], fill=(r, g, b, 255))
    mask = Image.new('L', (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=96, fill=255)
    img.putalpha(mask)

    # Sun: circle + 8 short rays, upper-right of center
    sun_cx, sun_cy, sun_r = 320, 190, 78
    for i in range(8):
        import math
        ang = i * (math.pi / 4)
        x1 = sun_cx + math.cos(ang) * (sun_r + 14)
        y1 = sun_cy + math.sin(ang) * (sun_r + 14)
        x2 = sun_cx + math.cos(ang) * (sun_r + 46)
        y2 = sun_cy + math.sin(ang) * (sun_r + 46)
        draw.line([(x1, y1), (x2, y2)], fill=YELLOW, width=14)
    draw.ellipse(
        [sun_cx - sun_r, sun_cy - sun_r, sun_cx + sun_r, sun_cy + sun_r],
        fill=YELLOW,
    )

    # Cloud: three overlapping ellipses + base rectangle, lower-left, drawn
    # over the sun's bottom-left rays so it reads as "in front of"
    cloud_body = [
        (110, 300, 250, 160),   # (cx, cy, w, h) small left lobe
        (230, 260, 320, 220),   # big center lobe
        (360, 300, 220, 160),   # right lobe
    ]
    cloud_color = WHITE
    for cx, cy, w, h in cloud_body:
        draw.ellipse([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], fill=cloud_color)
    draw.rounded_rectangle([120, 300, 430, 380], radius=40, fill=cloud_color)

    return img


if __name__ == '__main__':
    generate().save('/tmp/logo.png')
    print('wrote /tmp/logo.png')
