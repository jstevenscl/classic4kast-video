'use strict';

// Grafana's native server-side render endpoint (backed by the
// grafana-image-renderer plugin, running as part of the user's OWN Grafana
// deployment -- not this service). Fetching a PNG over plain HTTP means zero
// Puppeteer/Chromium involvement on our side for a 'grafana' source_type
// channel -- see the plan's section 4.
//
// GET {base}/render/d-solo/{dashboardUid}/{slug}
//     ?orgId=...&panelId=...&width=...&height=...&tz=...&from=...&to=...
// Authorization: Bearer {token}

async function fetchGrafanaPng(channel) {
  const {
    slug, grafana_base_url: base, grafana_dashboard_uid: uid, grafana_panel_id: panelId,
    grafana_api_token: token, grafana_org_id: orgId, grafana_time_from: from, grafana_time_to: to,
    grafana_extra_query: extraQuery, viewport_width: width, viewport_height: height,
  } = channel;

  const params = new URLSearchParams({
    orgId: String(orgId || 1),
    panelId: String(panelId),
    width: String(width || 1280),
    height: String(height || 720),
    tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
    from: from || 'now-1h',
    to: to || 'now',
  });
  const url = `${base.replace(/\/+$/, '')}/render/d-solo/${uid}/${encodeURIComponent(slug)}?${params}${extraQuery ? `&${extraQuery}` : ''}`;

  const res = await fetch(url, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    signal: AbortSignal.timeout(30000),
  });

  const contentType = res.headers.get('content-type') || '';
  if (!res.ok || !contentType.startsWith('image/')) {
    // Grafana returns an error BODY (often HTML/JSON) when the
    // grafana-image-renderer plugin isn't installed on the target instance --
    // surface that text verbatim rather than treating a non-image response
    // as a valid (garbage) frame.
    let bodyText = '';
    try { bodyText = (await res.text()).slice(0, 500); } catch (_) { /* best effort */ }
    throw new Error(`Grafana render failed (HTTP ${res.status}, content-type ${contentType || 'none'}): ${bodyText || '(empty body)'}`);
  }

  return Buffer.from(await res.arrayBuffer());
}

module.exports = { fetchGrafanaPng };
