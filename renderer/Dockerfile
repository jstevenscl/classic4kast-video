# Native (Chromium-free) WeatherStar renderer -- draws directly with Pillow
# onto templates extracted from netbymatt/ws4kp, instead of screenshotting a
# live browser. Replaces the weatherstar/ (Chromium) service: same HLS URL
# contract (/weatherstar/{slug}/{filename} -> /data/{slug}/hls/{filename},
# now served directly by renderer/on_demand_server.py's aiohttp app instead
# of nginx -- see that module's docstring for why nginx alone can't do the
# fire-on-demand cold-start trigger), same CONTROL_PLANE_URL/AGENT_TOKEN
# config polling contract, but ~1000x cheaper per render and a genuinely
# real-time clock/ticker instead of a periodic-screenshot one, and channels
# only render while someone's actually watching. See renderer/*.py for the
# architecture rationale and measured cost comparison.
FROM python:3.12-alpine

RUN apk add --no-cache ffmpeg tini tzdata

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY renderer ./renderer

# WS4KP's fonts ship as .woff (web font) -- Pillow needs .ttf/.otf.
# Converted once here at build time, not per-render.
RUN cd renderer/fonts && \
    for f in Star4000 Star4000-Large Star4000-Extended Star4000-Small; do \
      python3 -c "from fontTools.ttLib import TTFont; f=TTFont('$f.woff'); f.flavor=None; f.save('$f.ttf')"; \
    done

# /data holds per-city HLS output -- mounted as a volume in compose so
# output survives container restarts.
RUN mkdir -p /data

ENTRYPOINT ["/sbin/tini", "--"]
CMD ["python3", "-m", "renderer.on_demand_server"]
