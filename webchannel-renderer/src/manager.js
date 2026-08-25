'use strict';

// Channel lifecycle: render_mode state machine (on_demand/fire_on_start/
// always_on, same three-way semantics as renderer/renderer/on_demand_server.py
// -- see that file's module docstring for the full reasoning) plus the
// screenshot-loop -> persistent-ffmpeg -> HLS pipeline (ported from
// Scorecastarr's stream/manager.js).
//
// Simplification vs. both source patterns: ffmpeg is started ONCE per
// channel and just keeps looping whatever's currently at frame.jpg (image2
// demuxer with -loop 1 re-reads the file on each loop -- this is what lets
// Scorecastarr's Puppeteer screenshots "replace frame.jpg; ffmpeg picks them
// up each loop" without restarting ffmpeg). Going idle (on_demand) or
// resuming just starts/stops the capture loop that WRITES frame.jpg --
// ffmpeg itself is left running throughout an on_demand channel's warm
// baseline, exactly like the cheap always-running loading_stream.py loop in
// the Python renderer.

const fs = require('fs');
const path = require('path');
const { spawn, execFileSync } = require('child_process');

const config = require('./config');
const cpc = require('./control_plane_client');
const { getWarmBrowser } = require('./browser');
const { fetchGrafanaPng } = require('./grafana_source');
const { writeLoadingFrame } = require('./loading_frame');

const states = new Map(); // slug -> ChannelState
const latestChannels = new Map(); // slug -> channel config, refreshed each prewarm poll

class ChannelState {
  constructor() {
    this.ffmpeg = null;         // persistent per-channel ffmpeg process
    this.captureActive = false; // true once the screenshot/grafana loop is running
    this.stopCaptureFn = null;
    this.browser = null;
    this.page = null;
    this.lastAccess = 0;
    this.forceRenderSeen = false;
    this.keepBaseline = false;  // true once ensureBaseline has claimed this channel
  }
}

function getState(slug) {
  let s = states.get(slug);
  if (!s) { s = new ChannelState(); states.set(slug, s); }
  return s;
}

function channelDir(slug) { return path.join(config.DATA_ROOT, slug); }
function frameDir(slug) { return path.join(channelDir(slug), 'frames'); }
function framePath(slug) { return path.join(frameDir(slug), 'frame.jpg'); }
function frameTmpPath(slug) { return path.join(frameDir(slug), 'frame.tmp.jpg'); }
function hlsDir(slug) { return path.join(channelDir(slug), 'hls'); }

function ensureDir(d) { if (!fs.existsSync(d)) fs.mkdirSync(d, { recursive: true }); }

// ── ffmpeg (persistent per-channel, reads frame.jpg on a loop) ─────────────

function startFfmpeg(slug) {
  ensureDir(hlsDir(slug));
  const args = [
    '-loglevel', 'warning',
    '-re', '-loop', '1', '-framerate', '2', '-i', framePath(slug),
    '-vf', 'format=yuv420p',
    '-c:v', 'libx264', '-preset', 'veryfast', '-tune', 'stillimage',
    '-b:v', '1200k', '-maxrate', '1800k', '-bufsize', '2400k', '-pix_fmt', 'yuv420p',
    '-g', String(2 * config.HLS_SEGMENT_SECONDS), '-sc_threshold', '0',
    '-an',
    '-f', 'hls',
    '-hls_time', String(config.HLS_SEGMENT_SECONDS),
    '-hls_list_size', String(config.HLS_PLAYLIST_SIZE),
    '-hls_flags', 'delete_segments+independent_segments',
    '-hls_segment_filename', path.join(hlsDir(slug), 'stream%05d.ts'),
    path.join(hlsDir(slug), 'stream.m3u8'),
  ];
  const proc = spawn('ffmpeg', args, { stdio: ['ignore', 'ignore', 'pipe'] });
  proc.stderr.on('data', (d) => {
    const line = d.toString().trim();
    if (line) console.error(`[ffmpeg][${slug}] ${line}`);
  });
  proc.on('exit', (code, sig) => {
    const s = states.get(slug);
    if (s && s.ffmpeg === proc) {
      s.ffmpeg = null;
      console.log(`[manager][${slug}] ffmpeg exited (${code}/${sig})`);
      // Restart automatically if the channel is still supposed to be
      // running (baseline or live) -- an ffmpeg crash must not permanently
      // dark a channel, same restart-on-crash posture as live_stream.py's
      // own watchdog.
      if (s.captureActive || s.keepBaseline) {
        setTimeout(() => {
          if (states.get(slug) === s && (s.captureActive || s.keepBaseline) && !s.ffmpeg) {
            s.ffmpeg = startFfmpeg(slug);
          }
        }, 2000);
      }
    }
  });
  return proc;
}

// ── Baseline (loading placeholder + ffmpeg running, no browser/Grafana) ────
// Mirrors on_demand_server.py's _ensure_loading -- idempotent, cheap.

function ensureBaseline(slug, channel) {
  const state = getState(slug);
  state.keepBaseline = true;
  if (state.ffmpeg) return;
  ensureDir(frameDir(slug));
  if (!fs.existsSync(framePath(slug))) {
    try {
      writeLoadingFrame(framePath(slug), channel.channel_name || slug, channel.viewport_width || 1280, channel.viewport_height || 720);
    } catch (err) {
      console.error(`[manager][${slug}] loading frame write failed: ${err.message}`);
    }
  }
  state.ffmpeg = startFfmpeg(slug);
  console.log(`[manager][${slug}] baseline running (ffmpeg + loading placeholder)`);
}

// ── Capture loops ────────────────────────────────────────────────────────

async function startUrlCapture(slug, channel) {
  const browser = await getWarmBrowser();
  const page = await browser.newPage();
  page.on('console', (msg) => { if (msg.type() === 'error') console.error(`[page][${slug}] ${msg.text()}`); });
  page.on('pageerror', (err) => console.error(`[page][${slug}] pageerror: ${err.message}`));
  await page.setViewport({
    width: channel.viewport_width || 1280,
    height: channel.viewport_height || 720,
    deviceScaleFactor: channel.device_scale_factor || 1,
  });

  // Reuse a captured login session (see login_session.js) if this channel
  // has one -- both MUST happen before goto(): cookies apply to the
  // request itself, and localStorage has no document/origin context to
  // write into until evaluateOnNewDocument's injected script runs as part
  // of that same navigation. Without a saved session this is a no-op, same
  // as today.
  if (channel.session_state) {
    const { cookies, localStorage: storedLocalStorage } = channel.session_state;
    if (cookies && cookies.length) {
      try {
        await page.setCookie(...cookies);
      } catch (err) {
        console.warn(`[manager][${slug}] failed to apply saved session cookies (continuing without them): ${err.message}`);
      }
    }
    if (storedLocalStorage && Object.keys(storedLocalStorage).length) {
      await page.evaluateOnNewDocument((entries) => {
        for (const [key, value] of Object.entries(entries)) {
          try { window.localStorage.setItem(key, value); } catch (_) { /* storage disabled/full -- not fatal */ }
        }
      }, storedLocalStorage);
    }
  }

  await page.goto(channel.target_url, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await new Promise((r) => setTimeout(r, channel.page_load_wait_ms || 2000));

  // Optional one-time dismiss clicks (cookie banners, first-visit welcome
  // modals) -- runs once here, before the capture loop starts, not on
  // every frame. Comma-separated: a page can have more than one banner
  // (e.g. a cookie-consent link AND an unrelated security notice bar), each
  // needing its own selector clicked in sequence. A missing/already-gone
  // element is expected per-selector (that banner may not appear every
  // time, or a later selector may depend on an earlier click closing
  // something that was overlapping it) so each is logged and swallowed
  // independently, never fatal to the channel or to the remaining selectors.
  if (channel.dismiss_selector) {
    for (const selector of channel.dismiss_selector.split(',').map((s) => s.trim()).filter(Boolean)) {
      try {
        await page.click(selector, { timeout: 5000 });
        console.log(`[manager][${slug}] dismiss_selector clicked: ${selector}`);
      } catch (err) {
        console.warn(`[manager][${slug}] dismiss_selector not found/clickable (continuing): ${selector} -- ${err.message}`);
      }
    }
  }

  const state = getState(slug);
  state.browser = browser;
  state.page = page;

  let active = true;
  let reportedSuccess = false;
  const tmp = frameTmpPath(slug);
  const dest = framePath(slug);

  (async function loop() {
    while (active) {
      const t0 = Date.now();
      try {
        await page.screenshot({ path: tmp, type: 'jpeg', quality: 90 });
        fs.renameSync(tmp, dest);
        if (!reportedSuccess) { reportedSuccess = true; cpc.reportRenderResult(slug, true, null); }
      } catch (err) {
        console.error(`[manager][${slug}] screenshot error: ${err.message}`);
        cpc.reportRenderResult(slug, false, err.message);
      }
      const wait = Math.max(0, (channel.screenshot_interval_ms || 1000) - (Date.now() - t0));
      if (active) await new Promise((r) => setTimeout(r, wait));
    }
  })().catch((err) => console.error(`[manager][${slug}] capture loop crashed: ${err.message}`));

  return async () => {
    active = false;
    try { await page.close(); } catch (_) { /* already gone */ }
  };
}

async function startGrafanaCapture(slug, channel) {
  // Deliberately no Puppeteer/Chromium involvement here at all -- see
  // grafana_source.js's module comment. Same atomic-rename-into-place
  // staging path ffmpeg already reads, so everything downstream is
  // identical to URL-mode capture -- EXCEPT the persistent ffmpeg's input
  // is hardcoded to expect JPEG (image2/mjpeg demuxer, see startFfmpeg's
  // `-framerate 2 -i frame.jpg`), and Grafana's render API returns PNG, not
  // JPEG. Found live: feeding raw PNG bytes into a file named frame.jpg
  // made ffmpeg log a stream of "unable to decode APP fields" errors and
  // never produce a valid frame. Converting PNG -> real JPEG here (a cheap
  // one-off ffmpeg call, same execFileSync pattern as loading_frame.js) is
  // simpler than teaching the persistent ffmpeg process to accept either
  // format depending on source_type.
  let active = true;
  let reportedSuccess = false;
  const pngTmp = path.join(frameDir(slug), 'frame.grafana.png');
  const tmp = frameTmpPath(slug);
  const dest = framePath(slug);

  (async function loop() {
    while (active) {
      const t0 = Date.now();
      try {
        const png = await fetchGrafanaPng(channel);
        fs.writeFileSync(pngTmp, png);
        execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-i', pngTmp, '-frames:v', '1', '-q:v', '3', tmp], { stdio: 'pipe' });
        fs.renameSync(tmp, dest);
        if (!reportedSuccess) { reportedSuccess = true; cpc.reportRenderResult(slug, true, null); }
      } catch (err) {
        // A transient failure retries next interval rather than tearing
        // down the channel -- see the plan's Grafana error-handling note.
        console.error(`[manager][${slug}] grafana fetch error: ${err.message}`);
        cpc.reportRenderResult(slug, false, err.message);
      }
      const wait = Math.max(0, (channel.screenshot_interval_ms || 5000) - (Date.now() - t0));
      if (active) await new Promise((r) => setTimeout(r, wait));
    }
  })().catch((err) => console.error(`[manager][${slug}] grafana loop crashed: ${err.message}`));

  return async () => { active = false; };
}

async function startCapture(slug, channel) {
  const state = getState(slug);
  if (state.captureActive) return;
  ensureBaseline(slug, channel);
  state.captureActive = true;
  try {
    state.stopCaptureFn = channel.source_type === 'grafana'
      ? await startGrafanaCapture(slug, channel)
      : await startUrlCapture(slug, channel);
    console.log(`[manager][${slug}] capture active (${channel.source_type})`);
  } catch (err) {
    console.error(`[manager][${slug}] capture start failed: ${err.message}`);
    cpc.reportRenderResult(slug, false, err.message);
    state.captureActive = false;
    state.stopCaptureFn = null;
  }
}

async function stopCapture(slug) {
  const state = states.get(slug);
  if (!state || !state.captureActive) return;
  if (state.stopCaptureFn) { try { await state.stopCaptureFn(); } catch (_) { /* best effort */ } }
  state.captureActive = false;
  state.stopCaptureFn = null;
  state.browser = null;
  state.page = null;
  // Rewrite the loading placeholder so the still-running ffmpeg baseline
  // shows "LOADING" again instead of a stale dashboard screenshot.
  const channel = latestChannels.get(slug);
  try {
    writeLoadingFrame(framePath(slug), (channel && channel.channel_name) || slug,
      (channel && channel.viewport_width) || 1280, (channel && channel.viewport_height) || 720);
  } catch (err) {
    console.error(`[manager][${slug}] re-arm loading frame failed: ${err.message}`);
  }
  console.log(`[manager][${slug}] capture stopped, baseline re-armed`);
}

async function stopChannelFully(slug) {
  await stopCapture(slug);
  const state = states.get(slug);
  if (!state) return;
  state.keepBaseline = false;
  if (state.ffmpeg) {
    const proc = state.ffmpeg;
    state.ffmpeg = null;
    await new Promise((resolve) => {
      const t = setTimeout(() => { try { proc.kill('SIGKILL'); } catch (_) { /* already dead */ } resolve(); }, 5000);
      proc.once('exit', () => { clearTimeout(t); resolve(); });
      try { proc.kill('SIGTERM'); } catch (_) { resolve(); }
    });
  }
  try { fs.rmSync(channelDir(slug), { recursive: true, force: true }); } catch (_) { /* best effort */ }
  states.delete(slug);
  console.log(`[manager][${slug}] fully stopped`);
}

// Same cached-then-fresh-fetch fallback as touch() below, but read-only --
// used by the login-session WebSocket route (server.js) to resolve a
// channel's target_url without touching capture/idle state at all.
async function getChannel(slug) {
  let channel = latestChannels.get(slug);
  if (!channel) {
    const fresh = await cpc.fetchActiveWebChannels();
    channel = fresh.find((c) => c.slug === slug);
    if (channel) latestChannels.set(slug, channel);
  }
  return channel || null;
}

// ── Touch (real HTTP request -- mirrors _get_or_start) ──────────────────────

async function touch(slug) {
  const state = getState(slug);
  state.lastAccess = Date.now();
  if (state.captureActive) return true;

  let channel = latestChannels.get(slug);
  if (!channel) {
    const fresh = await cpc.fetchActiveWebChannels();
    channel = fresh.find((c) => c.slug === slug);
    if (channel) latestChannels.set(slug, channel);
  }
  if (!channel) return false;

  ensureBaseline(slug, channel);
  startCapture(slug, channel).catch(() => { /* logged inside startCapture */ });
  return true;
}

// ── render_mode state machine (prewarm + reaper, mirrors on_demand_server.py) ─

async function prewarmTick() {
  const channels = await cpc.fetchActiveWebChannels();
  const seenSlugs = new Set();
  for (const channel of channels) {
    seenSlugs.add(channel.slug);
    latestChannels.set(channel.slug, channel);
    const state = getState(channel.slug);

    if (channel.force_render) {
      if (!state.forceRenderSeen) {
        state.forceRenderSeen = true;
        if (state.captureActive) {
          console.log(`[manager][${channel.slug}] force-render requested -- restarting capture`);
          await stopCapture(channel.slug);
          await startCapture(channel.slug, channel);
        }
      }
    } else {
      state.forceRenderSeen = false;
    }

    if (channel.render_mode === 'always_on') {
      ensureBaseline(channel.slug, channel);
      if (!state.captureActive) await startCapture(channel.slug, channel);
      state.lastAccess = Date.now(); // never idle-stopped, keep the reaper's log sane if mode later changes
    } else if (channel.render_mode === 'fire_on_start') {
      // true zero cost at rest -- nothing until the first real request
    } else {
      ensureBaseline(channel.slug, channel); // on_demand: cheap loading baseline only
    }
  }
  // Channels removed/disabled since the last poll -- tear down fully rather
  // than leaking a warm baseline for something no longer configured.
  for (const slug of Array.from(states.keys())) {
    if (!seenSlugs.has(slug) && states.get(slug).keepBaseline) {
      console.log(`[manager][${slug}] no longer active -- tearing down`);
      await stopChannelFully(slug);
      latestChannels.delete(slug);
    }
  }
}

function startPrewarmLoop() {
  (async function loop() {
    while (true) {
      try { await prewarmTick(); } catch (err) { console.error(`[manager] prewarm error: ${err.message}`); }
      await new Promise((r) => setTimeout(r, config.PREWARM_POLL_SECONDS * 1000));
    }
  })();
}

// Real access-key gate for public-facing streams (see server.js's route
// handling) -- was previously entirely absent here despite
// on_demand_server.py's weather-channel routes having real stream-key
// validation (found live, C4K-5qh: web channels were bypassing the same
// key a user might have set in Settings to gate their public stream).
// null = not yet fetched successfully; '' = control plane deliberately has
// no key configured; non-empty = required value. Only updated on a
// SUCCESSFUL poll -- a transient control-plane outage holds the last
// known-good value rather than failing open, same reasoning as
// on_demand_server.py's own _stream_key_cache.
let streamKeyCache = null;

function getStreamKey() {
  return streamKeyCache;
}

function startStreamKeyPoll() {
  (async function loop() {
    while (true) {
      try {
        const settings = await cpc.fetchSettings();
        // Found live: the Python backend serializes "no key configured"
        // as JSON null (config.get_stream_key returns None), which has
        // typeof 'object', not 'string' -- a strict string-type check
        // here silently ignored every "key cleared" update once a real
        // key had been cached once, leaving streamKeyCache stuck on the
        // stale value forever (confirmed live: unkeyed requests kept
        // 403ing minutes after clearing the key in Settings). A
        // successful settings fetch is authoritative regardless of
        // whether stream_key came back as a string or null.
        if (settings) {
          streamKeyCache = settings.stream_key || '';
        }
      } catch (err) {
        console.error(`[manager] stream-key poll error: ${err.message}`);
      }
      await new Promise((r) => setTimeout(r, config.PREWARM_POLL_SECONDS * 1000));
    }
  })();
}

function startReaperLoop() {
  (async function loop() {
    while (true) {
      await new Promise((r) => setTimeout(r, config.REAPER_INTERVAL_SECONDS * 1000));
      try {
        const settings = await cpc.fetchSettings();
        const idleTimeout = (settings && settings.idle_timeout_seconds) || config.IDLE_TIMEOUT_FALLBACK_SECONDS;
        const now = Date.now();
        for (const [slug, state] of states.entries()) {
          if (!state.captureActive) continue;
          const channel = latestChannels.get(slug);
          const mode = (channel && channel.render_mode) || 'on_demand';
          if (mode === 'always_on') continue;
          const idleSeconds = (now - (state.lastAccess || 0)) / 1000;
          if (idleSeconds > idleTimeout) {
            console.log(`[manager][${slug}] idle ${idleSeconds.toFixed(0)}s (limit ${idleTimeout}s) -- stopping capture`);
            await stopCapture(slug);
            if (mode === 'fire_on_start') await stopChannelFully(slug); // true zero CPU at rest
          }
        }
      } catch (err) {
        console.error(`[manager] reaper error: ${err.message}`);
      }
    }
  })();
}

// ── Status (mirrors on_demand_server.py's handle_status shape) ─────────────

function getStatus() {
  const now = Date.now();
  const out = [];
  for (const [slug, channel] of latestChannels.entries()) {
    const state = states.get(slug);
    const running = !!(state && state.ffmpeg);
    const live = !!(state && state.captureActive);
    const idleFor = state && state.lastAccess ? (now - state.lastAccess) / 1000 : null;
    let status;
    if (channel.render_mode === 'always_on') status = 'watching';
    else if (live) status = 'watching';
    else if (running) status = 'idle (loading screen)';
    else status = 'cold';
    out.push({
      slug, channel_name: channel.channel_name, source_type: channel.source_type,
      render_mode: channel.render_mode, status, idle_seconds: idleFor !== null ? Math.round(idleFor) : null,
    });
  }
  return out;
}

async function shutdown() {
  for (const slug of Array.from(states.keys())) {
    await stopChannelFully(slug);
  }
}

module.exports = {
  touch, getChannel, startPrewarmLoop, startReaperLoop, getStatus, shutdown,
  channelDir, hlsDir, getStreamKey, startStreamKeyPoll,
};
