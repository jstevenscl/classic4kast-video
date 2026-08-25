'use strict';

// Env-driven config -- same override convention as the Python renderer's own
// config (control_plane_client.py / on_demand_server.py): every knob has a
// sane default, nothing requires a code change to run locally.

const DATA_ROOT = process.env.DATA_ROOT || '/data';
const LISTEN_PORT = parseInt(process.env.LISTEN_PORT || '8091', 10);

const CONTROL_PLANE_URL = (process.env.CONTROL_PLANE_URL || 'http://web:8283').replace(/\/+$/, '');
const AGENT_TOKEN = process.env.AGENT_TOKEN || '';

// How often the prewarm loop re-polls /api/agent/web-channels/ for new/
// retoggled channels -- mirrors on_demand_server.py's PREWARM_POLL_SECONDS.
const PREWARM_POLL_SECONDS = parseInt(process.env.CONFIG_POLL_SECONDS || '30', 10);
const REAPER_INTERVAL_SECONDS = 30;
// Fallback only -- the real idle timeout is polled live from
// /api/agent/settings/ (fleet-wide, shared with the weather renderer), same
// as on_demand_server.py's own fallback pattern.
const IDLE_TIMEOUT_FALLBACK_SECONDS = parseInt(process.env.IDLE_TIMEOUT_FALLBACK_SECONDS || '600', 10);

// How long the request handler waits for a cold-started channel to produce
// its first HLS file before giving up -- mirrors on_demand_server.py's
// FILE_WAIT_TIMEOUT_SECONDS.
const FILE_WAIT_TIMEOUT_SECONDS = 20;

const CHROMIUM_PATH = process.env.PUPPETEER_EXECUTABLE_PATH || '/usr/bin/chromium';
const CHROMIUM_ARGS = [
  '--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage',
  '--disable-gpu', '--disable-software-rasterizer',
];

const HLS_SEGMENT_SECONDS = parseInt(process.env.HLS_SEGMENT_SECONDS || '4', 10);
const HLS_PLAYLIST_SIZE = parseInt(process.env.HLS_PLAYLIST_SIZE || '6', 10);

module.exports = {
  DATA_ROOT, LISTEN_PORT, CONTROL_PLANE_URL, AGENT_TOKEN,
  PREWARM_POLL_SECONDS, REAPER_INTERVAL_SECONDS, IDLE_TIMEOUT_FALLBACK_SECONDS,
  FILE_WAIT_TIMEOUT_SECONDS, CHROMIUM_PATH, CHROMIUM_ARGS,
  HLS_SEGMENT_SECONDS, HLS_PLAYLIST_SIZE,
};
