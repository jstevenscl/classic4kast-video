# Web Channels renderer -- screenshots arbitrary websites/Grafana dashboards
# into HLS, via a single shared warm Chromium instance (one browser process,
# one lightweight tab per channel) -- see src/browser.js. Deliberately a
# THIRD, separate service/image from renderer/ (the Python/Pillow weather
# renderer, which is Chromium-free by design -- see renderer/Dockerfile's own
# header) so the heavier browser dependency, its shared-memory requirements,
# and any crash/OOM risk never share a process or container with the 24-
# channel weather fleet. Same 3-endpoint control-plane polling CONTRACT as
# renderer/renderer/control_plane_client.py (reimplemented in Node, see
# src/control_plane_client.js), same AGENT_TOKEN, but its own agent
# endpoints (/api/agent/web-channels/...) and its own HLS path prefix
# (/webchannel/{slug}/...) so neither renderer's polling code ever has to
# change for the other to exist.
FROM node:20-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      chromium ffmpeg tini fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true \
    PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

WORKDIR /app
COPY package.json ./
RUN npm install --omit=dev

COPY src ./src

# /data holds per-channel HLS output + frame staging, mounted as a volume in
# compose (classic4kast_webchannel_data) -- deliberately NOT the weather
# renderer's own volume, so there's no shared-path write contention.
RUN mkdir -p /data

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["node", "src/index.js"]
