'use strict';

// Reimplements, in Node, the same 3-endpoint control-plane contract
// documented in renderer/renderer/control_plane_client.py -- against the
// PARALLEL web-channel endpoints (web_channel_routes.py's
// web_channel_agent_router), not the weather ones. Deliberately its own
// implementation rather than a shared library (different language), but
// same X-Api-Key auth, same fetch/report shape.

const { CONTROL_PLANE_URL, AGENT_TOKEN } = require('./config');

function isConfigured() {
  return !!(CONTROL_PLANE_URL && AGENT_TOKEN);
}

async function _get(path) {
  const res = await fetch(`${CONTROL_PLANE_URL}${path}`, {
    headers: { 'X-Api-Key': AGENT_TOKEN },
    signal: AbortSignal.timeout(10000),
  });
  if (!res.ok) throw new Error(`${path} -> HTTP ${res.status}`);
  return res.json();
}

async function fetchActiveWebChannels() {
  if (!isConfigured()) return [];
  try {
    return await _get('/api/agent/web-channels/');
  } catch (err) {
    console.error(`[control-plane] fetchActiveWebChannels failed: ${err.message}`);
    return [];
  }
}

// Fleet-wide settings -- shared endpoint with the weather renderer
// (idle_timeout_seconds applies equally to both fleets).
async function fetchSettings() {
  if (!isConfigured()) return null;
  try {
    return await _get('/api/agent/settings/');
  } catch (err) {
    console.error(`[control-plane] fetchSettings failed: ${err.message}`);
    return null;
  }
}

async function reportRenderResult(slug, success, error) {
  if (!isConfigured()) return;
  try {
    const res = await fetch(`${CONTROL_PLANE_URL}/api/agent/web-channels/render-result/`, {
      method: 'POST',
      headers: { 'X-Api-Key': AGENT_TOKEN, 'Content-Type': 'application/json' },
      body: JSON.stringify({ slug, success, error: error || null }),
      signal: AbortSignal.timeout(10000),
    });
    if (!res.ok) console.error(`[control-plane] render-result report -> HTTP ${res.status}`);
  } catch (err) {
    console.error(`[control-plane] reportRenderResult failed: ${err.message}`);
  }
}

module.exports = { isConfigured, fetchActiveWebChannels, fetchSettings, reportRenderResult };
