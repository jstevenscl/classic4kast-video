import type { Country, RenderMode } from '@/types'

// Ported from EDM's WeatherStar.tsx -- mirrors the renderer's own
// RENDER_MODES / COUNTRIES / SCREEN_SUPPORT_BY_COUNTRY. See
// weatherstar-native/renderer/adapters/{nws,ec,open_meteo}.py's own module
// docstrings for why each source has a different real ceiling of supported
// screens (not just a UI translation of the same product set).

export const RENDER_MODE_OPTIONS: { value: RenderMode; label: string; description: string }[] = [
  {
    value: 'on_demand',
    label: 'On-demand (recommended)',
    description: 'Instant "WEATHER LOADING" screen at all times (~5% idle CPU); real content starts ~10s after the first request, idle-stops back to the loading screen.',
  },
  {
    value: 'fire_on_start',
    label: 'Fire on start',
    description: 'Zero CPU at rest -- nothing runs until the first request. A first request has a real gap (nothing playable) before the loading screen and then real content appear.',
  },
  {
    value: 'always_on',
    label: 'Always on',
    description: 'Real content runs continuously, never idle-stopped -- zero cold-start delay ever, at this city’s full CPU cost (~30-40%) whether or not anyone is watching.',
  },
]

export const COUNTRY_OPTIONS: { value: Country; label: string }[] = [
  { value: 'US', label: 'United States (NWS)' },
  { value: 'CA', label: 'Canada (Environment Canada)' },
  { value: 'INTL', label: 'Other / International (Open-Meteo)' },
]

export const US_ONLY_SCREEN_KEYS = new Set([
  'showHazards', 'showHourlyGraph', 'showRadar', 'showLatestObservations',
  'showRegionalForecast', 'showLocalForecast', 'showTravel', 'showMarineForecast',
  'showTideInfo', 'showOutlook',
  // showAQI is NOT here -- Open-Meteo has real global coverage, unlike the
  // NWS/CPC/NOAA CO-OPS sources behind every other US-only screen above.
])

// No renderer screen exists for these at all yet -- kept as an explicit,
// currently-empty set so a future not-yet-built screen can be flagged the
// same way EDM's UI already does, rather than silently offering a checkbox
// with no visible effect.
export const NOT_IMPLEMENTED_SCREEN_KEYS = new Set<string>([])

export const SCREEN_KEYS = [
  'showHazards',
  'showCurrent',
  'showHourly',
  'showHourlyGraph',
  'showExtendedForecast',
  'showRadar',
  'showLatestObservations',
  'showRegionalForecast',
  'showLocalForecast',
  'showAlmanac',
  'showMarineForecast',
  'showAQI',
  'showTideInfo',
  'showOutlook',
  'showTravel',
] as const

export const SCREEN_LABEL: Record<string, string> = {
  showHazards: 'Hazards',
  showCurrent: 'Current Conditions',
  showHourly: 'Hourly Forecast',
  showHourlyGraph: 'Hourly Graph',
  showExtendedForecast: 'Extended Forecast',
  showRadar: 'Radar',
  showLatestObservations: 'Latest Observations',
  showRegionalForecast: 'Regional Forecast',
  showLocalForecast: 'Local Forecast',
  showAlmanac: 'Almanac',
  showMarineForecast: 'Marine Forecast',
  showAQI: 'Air Quality (AQI)',
  showTideInfo: 'Tide Info',
  showOutlook: '30-Day Outlook',
  showTravel: 'Travel Conditions',
}

export const DEFAULT_SCREENS: Record<string, boolean> = {
  showHazards: true,
  showCurrent: true,
  showHourly: true,
  showHourlyGraph: true,
  showExtendedForecast: true,
  showRadar: true,
  showLatestObservations: false,
  showRegionalForecast: false,
  showLocalForecast: false,
  showAlmanac: false,
  showMarineForecast: false,
  showAQI: false,
  showTideInfo: false,
  showOutlook: false,
  showTravel: false,
}

// 'Redirect' -- not 'Proxy' -- confirmed the right default for classic4kast:
// Dispatcharr's Proxy profile has no mechanism to resync a long-lived
// connection back to live edge, which caused real multi-hour drift
// (10-12 min/hour, compounding, measured in EDM's own testing). Redirect
// sends the client straight to our own fully-controlled origin instead.
// Requires the public URL (Settings page) to be genuinely reachable by end
// viewers.
export const DEFAULT_STREAM_PROFILE_NAME = 'Redirect'

export function timeAgo(iso: string) {
  const diff = Date.now() - new Date(iso).getTime()
  const s = Math.floor(diff / 1000)
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return new Date(iso).toLocaleDateString()
}

// Country-unsupported and not-yet-implemented screens are force-unchecked
// on load (not just disabled in the UI) -- a channel switched from US to
// CA/INTL shouldn't silently keep an NWS-only screen "on" in stored config.
export function applyCountryScreenSupport(screens: Record<string, boolean>, country: Country): Record<string, boolean> {
  const next = { ...screens }
  for (const key of NOT_IMPLEMENTED_SCREEN_KEYS) next[key] = false
  if (country === 'US') return next
  for (const key of US_ONLY_SCREEN_KEYS) next[key] = false
  return next
}

// Same free Esri geocoder WS4KP's own location search box calls straight
// from the browser (CORS-open, no API key needed).
export async function geocode(query: string): Promise<{ lat: number; lon: number } | null> {
  const url = `https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/find?f=json&text=${encodeURIComponent(query)}`
  const res = await fetch(url)
  if (!res.ok) throw new Error(`geocoder returned ${res.status}`)
  const data = await res.json()
  const loc = data.locations?.[0]
  if (!loc) return null
  return { lat: loc.feature.geometry.y, lon: loc.feature.geometry.x }
}
