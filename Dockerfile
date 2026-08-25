# Classic4Kast Video+ -- single-container build.
#
# Ships all three services (weather renderer, web admin/API, web-channel
# renderer) as ONE image/ONE container, supervised as three separate OS
# processes (supervisord below) rather than three separate containers.
# This keeps the crash/restart isolation that mattered (a Chromium OOM in
# the web-channel renderer only takes down ITS supervised process --
# supervisord restarts it independently, the weather renderer's own Python
# process is never touched) without the deploy-ergonomics cost of three
# containers for one product. See supervisord.conf for the CPU-priority
# note on why the weather renderer is niced *above* the web-channel
# renderer, not just process-isolated from it.
#
# Split-container Dockerfiles (renderer/Dockerfile, web/Dockerfile,
# webchannel-renderer/Dockerfile) are kept for local per-service dev/debug
# builds -- this root Dockerfile is what docker-compose.yml actually ships.

FROM node:20-alpine AS frontend-build
WORKDIR /app
COPY web/frontend/package.json web/frontend/package-lock.json ./
RUN npm ci
COPY web/frontend/ ./
RUN npm run build

FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg tini tzdata supervisor \
      nodejs npm \
      chromium fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true \
    PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium \
    PYTHONUNBUFFERED=1

WORKDIR /app

# ── Weather renderer (Python/Pillow) ────────────────────────────────────────
COPY renderer/requirements.txt ./renderer-requirements.txt
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r renderer-requirements.txt
COPY renderer/renderer ./renderer/renderer
RUN cd renderer/renderer/fonts && \
    for f in Star4000 Star4000-Large Star4000-Extended Star4000-Small; do \
      python3 -c "from fontTools.ttLib import TTFont; f=TTFont('$f.woff'); f.flavor=None; f.save('$f.ttf')"; \
    done

# ── Web backend + built frontend (FastAPI) ──────────────────────────────────
COPY web/backend/requirements.txt ./web-requirements.txt
RUN pip install --no-cache-dir -r web-requirements.txt
COPY web/backend ./web
COPY --from=frontend-build /app/dist ./web/static

# ── Web-channel renderer (Node/Puppeteer) ───────────────────────────────────
COPY webchannel-renderer/package.json ./webchannel/package.json
RUN cd webchannel && npm install --omit=dev
COPY webchannel-renderer/src ./webchannel/src

# /data holds every service's own subdirectory (renderer/, web/, webchannel/)
# -- one volume in compose, but each service still only ever touches its own
# subtree, same separation the three-volume split had.
RUN mkdir -p /data

COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8283

ENTRYPOINT ["/usr/bin/tini", "--", "/entrypoint.sh"]
