<img src="docs/logo.png" alt="Classic4Kast Video+" width="360" />

A self-hosted, always-fresh local weather channel: renders WeatherStar-4000-style
screens (current conditions, extended forecast, radar, almanac, and more) and
serves them as a live HLS stream — no browser, no screenshot capture, just a
native compositor drawing straight into ffmpeg. Deploy it as its own channel
in [Dispatcharr](https://github.com/Dispatcharr/Dispatcharr), or point any
HLS-capable player at it directly.

<p align="center">
  <img src="docs/screenshots/buffalo-extended-forecast.jpg" alt="Extended forecast screen" width="49%" />
  <img src="docs/screenshots/buffalo-regional-observations-canada.jpg" alt="Regional observations screen, including nearby Canadian cities" width="49%" />
</p>

<p align="center"><em>Two example channels (Buffalo, NY and Austin, TX — used
throughout this repo's docs as generic examples). Regional Observations
pulls in real nearby US and Canadian cities when the channel is near
the border.</em></p>

Dispatcharr integration is optional. Classic4Kast Video+ runs standalone with zero
Dispatcharr connections configured; when you do add one (or several — same
host or remote), it deploys real Dispatcharr channels into existing channel
groups, not raw stream-import groups.

> **New here?** See [USERGUIDE.md](USERGUIDE.md) for a full walkthrough —
> install, first channel, Dispatcharr wiring, day-to-day use. This README is
> a concise technical reference for people already up and running.

## Requirements

- Docker + Docker Compose
- ffmpeg is bundled in the renderer image — nothing to install separately
- Optional: one or more running [Dispatcharr](https://github.com/Dispatcharr/Dispatcharr)
  instances, if you want deployed channels rather than a standalone stream

## Architecture

One container, one compose service — three supervised processes inside it
(via `supervisord`), each with its own crash/restart isolation but sharing
one image and one `docker compose up`:

- **`renderer`** — draws each weather screen with Pillow, composites frames
  live, and feeds them straight into a persistent ffmpeg process producing
  an HLS stream per channel. Renders only while a channel is being watched
  (configurable per channel: on-demand, fire-on-start, or always-on).
- **`webchannel`** — the same on-demand/fire-on-start/always-on model,
  applied to arbitrary websites and Grafana dashboards instead of weather:
  a single shared headless-Chromium instance (one browser, one lightweight
  tab per channel) screenshots each page on an interval and feeds the same
  persistent-ffmpeg → HLS pipeline. Grafana-sourced channels skip Chromium
  entirely and fetch a rendered PNG straight from Grafana's own image-
  renderer API. Runs at a lower CPU scheduling priority than `renderer` so
  it can't starve the weather fleet under contention. Login-gated pages
  (cloud SSO/MFA included) are supported via an interactive session
  capture — see [USERGUIDE.md § 11](USERGUIDE.md#logging-into-gated-pages-session-capture).
- **`web`** — the admin UI and control plane: channel configuration (both
  kinds), Dispatcharr connection management, and deploy/undeploy. Both
  renderers poll `web` for their channel lists and report render results
  back over two independent token-authed API contracts; `web` is the only
  process with a published port.

All three talk to each other over `localhost` inside the one container.

## Quick start

```sh
docker compose up -d
```

`AGENT_TOKEN` no longer needs to be set by hand — the container generates
and persists a random one to its data volume on first boot. Only pass
`AGENT_TOKEN=<value>` in the environment if you specifically need to pin it
to a known value.

Open `http://<host>:8283`, set an admin username/password on first load, and
create your first channel.

<p align="center">
  <img src="docs/screenshots/channels-list.jpg" alt="Channels list in the admin UI" width="80%" />
</p>

## Configuration

Environment variables (set via compose):

| Var | Purpose |
|---|---|
| `AGENT_TOKEN` | Optional. Shared secret the two renderer processes use to authenticate their polls of `web`, all over localhost. Auto-generated and persisted to the data volume if unset. |
| `APP_PORT` | Port `web` listens on (the only port this container publishes). Default `8283`. |
| `CLASSIC4KAST_ADMIN_USER` / `CLASSIC4KAST_ADMIN_PASSWORD` | Optional: set admin credentials via env instead of the first-run UI. Takes precedence over stored credentials. |

Everything else (channels of both kinds, Dispatcharr connections, public
URL, stream key, idle timeout) is configured from the `web` UI and stored
in its SQLite DB / `config.json`, not via environment variables.
`docker-compose.override.yml.example` covers the one remaining override
scenario (republishing the port).

## Stream stability

If you see stuttering or clock drift on a deployed channel, check which
Dispatcharr **stream profile** it's using — deploy defaults to `Redirect`
for a reason: Dispatcharr's `Proxy` profile has been observed causing
multi-hour clock drift (10–12 minutes/hour) against this renderer's steady
origin stream, which reads as stutter/desync to viewers. `Redirect` avoids
the extra hop entirely.

## Third-party assets

Fonts, icons, screen templates, and default background music are vendored
from [netbymatt/ws4kp](https://github.com/netbymatt/ws4kp) and
[netbymatt/ws4kp-music](https://github.com/netbymatt/ws4kp-music) (MIT
licensed). See [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) for full
attribution.

## License

[PolyForm Noncommercial 1.0.0](LICENSE) — free to self-host, modify, and
share for any noncommercial purpose (personal, homelab, nonprofit,
educational, evaluation). Commercial use — selling it, charging for
hosting it, or bundling it into a paid product/service — isn't permitted.
Vendored third-party assets (see above) keep their own original MIT
license.
