'use strict';

// One shared warm Chromium process for the lifetime of this service --
// ported directly from Scorecastarr's stream/manager.js getWarmBrowser()
// (C:\Projects\Scorecastarr\scorecastarr\stream\manager.js). Every channel
// gets its own page (tab), never its own browser process -- this is the
// whole point of the design (see the plan's Context section: per-channel
// resource cost is a first-order constraint given the user's 24-channel
// weather fleet).

const puppeteer = require('puppeteer-core');
const { CHROMIUM_PATH, CHROMIUM_ARGS } = require('./config');

let _warmBrowser = null;
let _warmBrowserBusy = false;

async function getWarmBrowser() {
  if (_warmBrowser) {
    try { await _warmBrowser.pages(); return _warmBrowser; } catch (_) {
      console.warn('[browser] Warm browser died -- relaunching');
      _warmBrowser = null;
    }
  }
  if (_warmBrowserBusy) {
    while (_warmBrowserBusy) await new Promise((r) => setTimeout(r, 100));
    if (_warmBrowser) return _warmBrowser;
  }
  _warmBrowserBusy = true;
  try {
    console.log('[browser] Launching warm browser (shared Chromium instance)');
    _warmBrowser = await puppeteer.launch({
      executablePath: CHROMIUM_PATH,
      headless: true,
      args: CHROMIUM_ARGS,
    });
    _warmBrowser.on('disconnected', () => {
      console.warn('[browser] Warm browser disconnected -- will relaunch on next channel start');
      _warmBrowser = null;
    });
    console.log('[browser] Warm browser ready');
  } finally {
    _warmBrowserBusy = false;
  }
  return _warmBrowser;
}

async function closeWarmBrowser() {
  if (_warmBrowser) {
    try { await _warmBrowser.close(); } catch (_) { /* shutting down anyway */ }
    _warmBrowser = null;
  }
}

module.exports = { getWarmBrowser, closeWarmBrowser };
