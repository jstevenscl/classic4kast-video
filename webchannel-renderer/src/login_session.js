'use strict';

// Interactive login-session capture: an admin watches a live CDP screencast
// of a real Puppeteer page and drives it with their own mouse/keyboard (via
// CDP Input.dispatch* calls) to log into an arbitrary login-gated site --
// UniFi Protect/Network was the motivating case, whose own cloud-SSO login
// has MFA that a scripted credential/form-fill could never get through.
// Once logged in, the resulting cookies + localStorage are captured so the
// regular capture loop (manager.js's startUrlCapture) can reuse them on
// every future page load without re-authenticating.
//
// Deliberately a SEPARATE page from the channel's regular capture page
// (manager.js keeps its own in ChannelState) -- a login session can run
// concurrently with, or instead of, an already-active capture loop without
// disturbing it, and closes cleanly on its own regardless of the channel's
// own lifecycle.

const { getWarmBrowser } = require('./browser');

const _sessions = new Map(); // slug -> { page, cdpSession, frameHandler, lastActivity, timeout }

const IDLE_TIMEOUT_MS = 5 * 60 * 1000; // abandoned session (no input, no viewer) auto-closes

function _touch(session) {
  session.lastActivity = Date.now();
  clearTimeout(session.timeout);
  session.timeout = setTimeout(() => {
    console.warn(`[login-session][${session.slug}] idle ${IDLE_TIMEOUT_MS / 1000}s -- auto-closing abandoned session`);
    closeLoginSession(session.slug).catch(() => {});
  }, IDLE_TIMEOUT_MS);
}

async function _sendImmediateSnapshot(session) {
  // CDP's screencast only PUSHES a frame when the page actually repaints --
  // found live: a (re)connecting viewer of an already-settled, static page
  // (nothing left to repaint) got NO frame at all until something visually
  // changed, even though the page has real content sitting on screen right
  // now. A plain page.screenshot() sidesteps that -- shows current state
  // immediately on connect/reconnect, same expectation any remote-desktop
  // viewer has, independent of whatever the ongoing screencast stream does
  // next.
  if (!session.onFrame) return;
  try {
    const data = await session.page.screenshot({ encoding: 'base64', type: 'jpeg', quality: 60 });
    session.onFrame(data);
  } catch (err) {
    console.warn(`[login-session][${session.slug}] immediate snapshot failed: ${err.message}`);
  }
}

async function startLoginSession(slug, targetUrl, onFrame) {
  // Only one interactive session per channel at a time -- a second attempt
  // just takes over the existing page rather than leaking a duplicate one.
  const existing = _sessions.get(slug);
  if (existing) {
    console.log(`[login-session][${slug}] reusing already-open session`);
    existing.onFrame = onFrame;
    _touch(existing);
    await _sendImmediateSnapshot(existing);
    return existing;
  }

  const browser = await getWarmBrowser();
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 720 });
  const cdpSession = await page.createCDPSession();

  const session = { slug, page, cdpSession, onFrame, lastActivity: Date.now(), timeout: null };
  _sessions.set(slug, session);
  _touch(session);

  cdpSession.on('Page.screencastFrame', async (evt) => {
    try {
      // Ack is required by CDP or the browser stops sending further frames
      // -- easy to miss since a screencast that just silently stalls after
      // one frame looks like a bug elsewhere, not a missing ack.
      await cdpSession.send('Page.screencastFrameAck', { sessionId: evt.sessionId });
    } catch (_) { /* session may have already closed */ }
    if (session.onFrame) session.onFrame(evt.data);
  });

  // No explicit frame-rate cap requested -- CDP only sends the NEXT frame
  // once the previous one's ack lands (see the screencastFrame handler
  // above), so this is naturally self-paced to the ack round-trip time
  // rather than flooding the WebSocket, fine for a login flow that isn't
  // fast-motion content.
  await cdpSession.send('Page.startScreencast', {
    format: 'jpeg', quality: 60, maxWidth: 1280, maxHeight: 720,
  });

  try {
    await page.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
  } catch (err) {
    console.error(`[login-session][${slug}] initial navigation failed: ${err.message}`);
  }
  await _sendImmediateSnapshot(session);

  console.log(`[login-session][${slug}] started`);
  return session;
}

async function dispatchInput(slug, event) {
  // event.inputType, NOT event.type -- found live while testing: the
  // outer WebSocket message already uses `type` as its own top-level
  // discriminator ('input' vs 'capture' vs 'frame' vs 'error', see
  // server.js), so the inner CDP-ish action needs a different field name.
  // Using `type` for both meant this whole function's checks below could
  // never match (event.type was always the literal string 'input'), so no
  // click/keystroke ever actually reached the page -- confirmed live via a
  // direct WebSocket test client before this fix.
  const session = _sessions.get(slug);
  if (!session) return;
  _touch(session);
  try {
    if (event.inputType === 'mousemove' || event.inputType === 'mousedown' || event.inputType === 'mouseup' || event.inputType === 'wheel') {
      await session.cdpSession.send('Input.dispatchMouseEvent', {
        type: event.inputType === 'mousemove' ? 'mouseMoved'
          : event.inputType === 'mousedown' ? 'mousePressed'
          : event.inputType === 'mouseup' ? 'mouseReleased' : 'mouseWheel',
        x: event.x, y: event.y,
        button: event.button || 'left', clickCount: event.clickCount || 1,
        deltaX: event.deltaX || 0, deltaY: event.deltaY || 0,
      });
    } else if (event.inputType === 'keydown' || event.inputType === 'keyup') {
      await session.cdpSession.send('Input.dispatchKeyEvent', {
        type: event.inputType === 'keydown' ? 'keyDown' : 'keyUp',
        key: event.key, code: event.code,
        windowsVirtualKeyCode: event.keyCode, nativeVirtualKeyCode: event.keyCode,
      });
      // A bare keyDown does NOT insert text into a focused input, even
      // with `text` set on it -- confirmed live (typed characters never
      // appeared in the target site's username/password fields until this
      // was added). Chrome's CDP backend needs a SEPARATE 'char'-type
      // event carrying the text -- this is exactly what Puppeteer's own
      // Keyboard.sendCharacter() does under the hood for printable keys,
      // just not exposed at the raw Input.dispatchKeyEvent level.
      if (event.inputType === 'keydown' && event.text) {
        await session.cdpSession.send('Input.dispatchKeyEvent', {
          type: 'char', text: event.text, unmodifiedText: event.text,
        });
      }
    }
  } catch (err) {
    console.error(`[login-session][${slug}] input dispatch error: ${err.message}`);
  }
}

async function captureSessionState(slug) {
  const session = _sessions.get(slug);
  if (!session) throw new Error('no active login session for this channel');
  _touch(session);
  const cookies = await session.page.cookies();
  const localStorageJson = await session.page.evaluate(() => {
    const out = {};
    for (let i = 0; i < window.localStorage.length; i++) {
      const key = window.localStorage.key(i);
      out[key] = window.localStorage.getItem(key);
    }
    return out;
  });
  return { cookies, localStorage: localStorageJson };
}

async function closeLoginSession(slug) {
  const session = _sessions.get(slug);
  if (!session) return;
  _sessions.delete(slug);
  clearTimeout(session.timeout);
  try { await session.cdpSession.send('Page.stopScreencast'); } catch (_) { /* already gone */ }
  try { await session.page.close(); } catch (_) { /* already gone */ }
  console.log(`[login-session][${slug}] closed`);
}

module.exports = { startLoginSession, dispatchInput, captureSessionState, closeLoginSession };
