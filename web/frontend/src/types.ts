// Shared types for the classic4kast admin UI. Field sets mirror the backend's
// API contract (see plan's "Step 3" API contract list) -- ported from EDM's
// WeatherStarChannel/WeatherStarDeployment/ChannelGroup/Instance types in
// frontend/src/pages/WeatherStar.tsx, with EDM's single implicit "instance"
// concept replaced everywhere by a first-class, multi-row Dispatcharr
// connection (this product supports zero, one, or many, unlike EDM which
// always had exactly one already configured elsewhere in its own app).

export type RenderMode = 'on_demand' | 'fire_on_start' | 'always_on'
export type Country = 'US' | 'CA' | 'INTL'

export interface WeatherStarDeployment {
  connection_id: number
  connection_label: string
  name: string
  stream_profile_id: number | null
  logo_url: string | null
  channel_group_id: number
  channel_group_name: string
  channel_number: number
  dispatcharr_channel_id: number
  dispatcharr_stream_id: number
  // null/omitted: Dispatcharr's own default at deploy time (every profile on
  // the connection). [] or [ids]: explicitly scoped. See DeployModal.
  channel_profile_ids?: number[] | null
}

export interface DispatcharrChannelProfile {
  id: number
  name: string
  channel_count: number
}

export interface WeatherStarChannel {
  id: number
  slug: string
  city_name: string
  location_query: string
  lat: number
  lon: number
  units: 'imperial' | 'metric'
  screens: Record<string, boolean>
  enabled: boolean
  render_mode: RenderMode
  country: Country
  ec_city_id: string | null
  force_render: boolean
  last_render_at: string | null
  last_render_status: 'success' | 'error' | null
  last_render_error: string | null
  created_at: string
  updated_at: string
  deployments: WeatherStarDeployment[]
}

// A Dispatcharr connection -- new to this product vs. EDM, which only ever
// had one implicit "instance" pre-configured elsewhere in its own app. This
// product must work with zero connections at all (pure standalone
// renderer), so every UI surface that lists connections has to render
// sensibly when this list is empty.
export interface DispatcharrConnection {
  id: number
  label: string
  url: string
  // Token itself is never returned by the list endpoint (only a reveal
  // endpoint returns it, on demand) -- kept optional/absent here.
  has_token?: boolean
  created_at?: string
}

export interface ChannelGroup {
  id: number
  name: string
  channel_count: string | number
}

export interface StreamProfile {
  id: number
  name: string
  is_active: boolean
}

export interface ChannelStatus {
  slug: string
  city_name: string
  render_mode: RenderMode
  status: 'watching' | 'idle (loading screen)' | 'idle (always-on)' | 'cold'
  idle_seconds: number | null
}

export type WebChannelSourceType = 'url' | 'grafana'

// Mirrors web/backend/web_channels_db.py's web_channels row shape -- a
// deliberately separate type from WeatherStarChannel (see that backend
// module's own comment: no shared table/fields, only a mirrored shape).
export interface WebChannel {
  id: number
  slug: string
  channel_name: string
  source_type: WebChannelSourceType
  enabled: boolean
  render_mode: RenderMode

  target_url: string | null
  viewport_width: number
  viewport_height: number
  screenshot_interval_ms: number
  page_load_wait_ms: number
  device_scale_factor: number
  dismiss_selector: string | null
  // Derived server-side (see web_channels_db.py's _web_channel_out) -- the
  // real captured cookies/localStorage are never returned to the browser,
  // only whether one exists, for the "Log in" / "Session captured" UI.
  has_session: boolean

  grafana_base_url: string | null
  grafana_dashboard_uid: string | null
  grafana_panel_id: string | null
  // Never returned by the CRUD API (redacted server-side) -- present here
  // only because the API response shape includes the key as null.
  grafana_api_token: null
  grafana_org_id: number
  grafana_time_from: string
  grafana_time_to: string
  grafana_extra_query: string | null

  force_render: boolean
  last_render_at: string | null
  last_render_status: 'success' | 'error' | null
  last_render_error: string | null
  deployments: WeatherStarDeployment[]
  created_at: string
  updated_at: string
}

export interface BulkDeployResult {
  connection_id: number
  connection_label?: string
  ok: boolean
  error?: string
}

export interface RefreshAllResult {
  channel_id: number
  slug: string
  connection_id: number
  connection_label?: string
  ok: boolean
  error?: string
}
