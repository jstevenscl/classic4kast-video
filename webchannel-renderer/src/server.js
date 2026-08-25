'use strict';

// Serves this service's own HLS output directly -- same role as
// on_demand_server.py's aiohttp app for the weather renderer, at a
// DIFFERENT path prefix (/webchannel/... vs /weatherstar/...) so the web
// backend's reverse proxy can route to either renderer independently (see
// web/backend/main.py's new proxy_webchannel route).

const fs = require('fs');
const http = require('http');
const path = require('path');
const { WebSocketServer } = require('ws');

const config = require('./config');
const manager = require('./manager');
const loginSession = require('./login_session');

function contentTypeFor(filename) {
  return filename.endsWith('.m3u8') ? 'application/vnd.apple.mpegurl' : 'video/mp2t';
}

async function waitForFile(filePath) {
  const deadline = Date.now() + config.FILE_WAIT_TIMEOUT_SECONDS * 1000;
  while (Date.now() < deadline) {
    if (fs.existsSync(filePath)) return true;
    await new Promise((r) => setTimeout(r, 200));
  }
  return false;
}

function start() {
  const server = http.createServer(async (req, res) => {
    // Two shapes, same as on_demand_server.py's handle_hls_file/
    // handle_hls_file_keyed: /webchannel/{slug}/{filename} (only valid
    // when NO stream key is configured) and /webchannel/{slug}/{key}/
    // {filename} (only valid when a key IS configured and matches). Found
    // live, C4K-5qh: this route previously had no key concept at all, so a
    // stream key set in Settings (meant to gate public exposure) silently
    // never applied to web channels.
    const unkeyedMatch = req.url.match(/^\/webchannel\/([a-z0-9-]+)\/([\w.-]+\.(?:m3u8|ts))$/);
    const keyedMatch = req.url.match(/^\/webchannel\/([a-z0-9-]+)\/([^/]+)\/([\w.-]+\.(?:m3u8|ts))$/);
    if (unkeyedMatch || keyedMatch) {
      const requiredKey = manager.getStreamKey();
      let slug, filename;
      if (keyedMatch) {
        const [, keyedSlug, key, keyedFilename] = keyedMatch;
        if (!requiredKey || key !== requiredKey) { res.writeHead(403); res.end('invalid or missing key'); return; }
        slug = keyedSlug; filename = keyedFilename;
      } else {
        if (requiredKey) { res.writeHead(403); res.end('invalid or missing key'); return; }
        [, slug, filename] = unkeyedMatch;
      }
      const known = await manager.touch(slug);
      if (!known) { res.writeHead(404); res.end('unknown web channel'); return; }

      const filePath = path.join(manager.hlsDir(slug), filename);
      if (!(await waitForFile(filePath))) {
        res.writeHead(503); res.end('stream still starting, try again shortly'); return;
      }
      try {
        const data = fs.readFileSync(filePath);
        res.writeHead(200, { 'Content-Type': contentTypeFor(filename), 'Cache-Control': 'no-cache' });
        res.end(data);
      } catch (err) {
        res.writeHead(503); res.end('stream error');
      }
      return;
    }

    if (req.method === 'GET' && req.url === '/status') {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(manager.getStatus()));
      return;
    }

    res.writeHead(404); res.end();
  });

  // Interactive login-session screencast/input tunnel (see login_session.js).
  // noServer: true -- this HTTP server already owns port LISTEN_PORT for
  // the regular HLS routes above, so the upgrade is routed manually below
  // rather than letting WebSocketServer bind its own listener. Not
  // independently authenticated here: this service is only reachable
  // from inside the compose network (only `web` publishes a port), and
  // the FastAPI bridge route (web_channel_routes.py) is what validates the
  // browser's session token before ever opening this connection -- same
  // trust boundary every other Node<->web internal call already relies on.
  const wss = new WebSocketServer({ noServer: true });
  server.on('upgrade', (req, socket, head) => {
    const match = req.url.match(/^\/webchannel\/([a-z0-9-]+)\/login-session$/);
    if (!match) { socket.destroy(); return; }
    const [, slug] = match;
    wss.handleUpgrade(req, socket, head, (ws) => {
      handleLoginSessionSocket(slug, ws);
    });
  });

  server.listen(config.LISTEN_PORT, '0.0.0.0', () => {
    console.log(`[server] listening on :${config.LISTEN_PORT}`);
  });
  return server;
}

async function handleLoginSessionSocket(slug, ws) {
  const channel = await manager.getChannel(slug);
  if (!channel || !channel.target_url) {
    ws.send(JSON.stringify({ type: 'error', message: 'unknown web channel or no target URL' }));
    ws.close();
    return;
  }

  let session;
  try {
    session = await loginSession.startLoginSession(slug, channel.target_url, (frameData) => {
      if (ws.readyState === ws.OPEN) ws.send(JSON.stringify({ type: 'frame', data: frameData }));
    });
  } catch (err) {
    console.error(`[server][${slug}] login-session start failed: ${err.message}`);
    ws.send(JSON.stringify({ type: 'error', message: err.message }));
    ws.close();
    return;
  }

  ws.on('message', async (raw) => {
    let msg;
    try { msg = JSON.parse(raw); } catch (_) { return; }
    if (msg.type === 'capture') {
      try {
        const state = await loginSession.captureSessionState(slug);
        ws.send(JSON.stringify({ type: 'captured', ...state }));
      } catch (err) {
        ws.send(JSON.stringify({ type: 'error', message: err.message }));
      }
      return;
    }
    if (msg.type === 'input') {
      await loginSession.dispatchInput(slug, msg);
    }
  });

  // Deliberately does NOT close the underlying Puppeteer page on socket
  // close -- a brief disconnect/reconnect (network blip, browser tab
  // backgrounded) shouldn't lose in-progress login state; the page is only
  // torn down by login_session.js's own idle timeout, or a fresh viewer
  // sending 'capture' successfully. Multiple viewer sockets could in
  // principle attach to the same session's frame feed by re-calling
  // startLoginSession (session, onFrame) -- last one to connect gets frames.
  ws.on('close', () => {
    console.log(`[server][${slug}] login-session socket closed (page left running until idle timeout)`);
  });
}

module.exports = { start };
