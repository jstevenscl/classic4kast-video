import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { RENDER_MODE_OPTIONS } from '@/components/weather/channelConstants'
import api from '@/lib/api'
import type { RenderMode, WebChannelSourceType } from '@/types'

export interface WebChannelFormState {
  slug: string
  channel_name: string
  source_type: WebChannelSourceType
  enabled: boolean
  render_mode: RenderMode

  target_url: string
  viewport_width: string
  viewport_height: string
  screenshot_interval_ms: string
  page_load_wait_ms: string
  device_scale_factor: string
  dismiss_selector: string

  grafana_base_url: string
  grafana_dashboard_uid: string
  grafana_panel_id: string
  grafana_api_token: string
  grafana_org_id: string
  grafana_time_from: string
  grafana_time_to: string
  grafana_extra_query: string
}

export function emptyWebChannelForm(): WebChannelFormState {
  return {
    slug: '', channel_name: '', source_type: 'url', enabled: true, render_mode: 'on_demand',
    target_url: '', viewport_width: '1280', viewport_height: '720',
    screenshot_interval_ms: '1000', page_load_wait_ms: '2000', device_scale_factor: '1', dismiss_selector: '',
    grafana_base_url: '', grafana_dashboard_uid: '', grafana_panel_id: '', grafana_api_token: '',
    grafana_org_id: '1', grafana_time_from: 'now-1h', grafana_time_to: 'now', grafana_extra_query: '',
  }
}

// Deliberately its own form, not a source_type branch bolted onto
// ChannelForm.tsx -- that component's fields (location_query+geocode,
// ScreensGrid, country/ec_city_id) are all weather-specific and this
// channel type shares nothing with them except the render_mode picker
// (reused directly via RENDER_MODE_OPTIONS, not worth extracting a whole
// shared component for one <select>).
export default function WebChannelForm({ form, setForm, isEdit }: { form: WebChannelFormState; setForm: (f: WebChannelFormState) => void; isEdit: boolean }) {
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null)

  const handleTestGrafana = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const res = await api.post('/webchannels/test-grafana/', {
        grafana_base_url: form.grafana_base_url,
        grafana_dashboard_uid: form.grafana_dashboard_uid,
        grafana_panel_id: form.grafana_panel_id,
        grafana_api_token: form.grafana_api_token || null,
        grafana_org_id: Number(form.grafana_org_id) || 1,
      })
      setTestResult({ ok: true, message: res.data?.message || 'Connection OK' })
    } catch (err: any) {
      setTestResult({ ok: false, message: err?.response?.data?.detail || err?.message || 'Test failed' })
    } finally {
      setTesting(false)
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex flex-col gap-1">
          <span className="text-[10px] text-muted-foreground">Slug</span>
          <Input
            className="h-8 text-xs w-40"
            placeholder="e.g. status-board"
            value={form.slug}
            disabled={isEdit}
            onChange={(e) => setForm({ ...form, slug: e.target.value })}
          />
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-[10px] text-muted-foreground">Channel name</span>
          <Input
            className="h-8 text-xs w-48"
            placeholder="e.g. Ops Dashboard"
            value={form.channel_name}
            onChange={(e) => setForm({ ...form, channel_name: e.target.value })}
          />
        </div>
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer mt-4">
          <input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} />
          Enabled
        </label>
      </div>

      <div className="flex flex-col gap-1">
        <span className="text-[10px] text-muted-foreground">Source</span>
        <div className="flex rounded-md border border-border overflow-hidden w-fit">
          {(['url', 'grafana'] as const).map((t) => (
            <button
              key={t}
              type="button"
              className={`px-3 py-1.5 text-xs font-medium ${form.source_type === t ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-accent'}`}
              onClick={() => setForm({ ...form, source_type: t })}
            >
              {t === 'url' ? 'Website (screenshot)' : 'Grafana dashboard'}
            </button>
          ))}
        </div>
      </div>

      {form.source_type === 'url' ? (
        <div className="space-y-2 rounded-md border border-border p-2">
          <div className="flex flex-col gap-1">
            <span className="text-[10px] text-muted-foreground">Page URL</span>
            <Input
              className="h-8 text-xs"
              placeholder="https://example.com/dashboard"
              value={form.target_url}
              onChange={(e) => setForm({ ...form, target_url: e.target.value })}
            />
          </div>
          <div className="flex flex-wrap gap-2">
            <div className="flex flex-col gap-1">
              <span className="text-[10px] text-muted-foreground">Viewport width</span>
              <input type="number" className="h-8 text-xs bg-background border border-border rounded px-2 w-28"
                value={form.viewport_width} onChange={(e) => setForm({ ...form, viewport_width: e.target.value })} />
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-[10px] text-muted-foreground">Viewport height</span>
              <input type="number" className="h-8 text-xs bg-background border border-border rounded px-2 w-28"
                value={form.viewport_height} onChange={(e) => setForm({ ...form, viewport_height: e.target.value })} />
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-[10px] text-muted-foreground">Screenshot interval (ms)</span>
              <input type="number" className="h-8 text-xs bg-background border border-border rounded px-2 w-32"
                value={form.screenshot_interval_ms} onChange={(e) => setForm({ ...form, screenshot_interval_ms: e.target.value })} />
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-[10px] text-muted-foreground">Page load wait (ms)</span>
              <input type="number" className="h-8 text-xs bg-background border border-border rounded px-2 w-32"
                value={form.page_load_wait_ms} onChange={(e) => setForm({ ...form, page_load_wait_ms: e.target.value })} />
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-[10px] text-muted-foreground">Device scale factor</span>
              <input type="number" step="0.5" min="1" max="3" className="h-8 text-xs bg-background border border-border rounded px-2 w-24"
                value={form.device_scale_factor} onChange={(e) => setForm({ ...form, device_scale_factor: e.target.value })} />
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-[10px] text-muted-foreground">Dismiss selector(s) (optional)</span>
            <Input className="h-8 text-xs" placeholder="e.g. .opt-out-link, #cookie-accept"
              value={form.dismiss_selector} onChange={(e) => setForm({ ...form, dismiss_selector: e.target.value })} />
            <p className="text-[10px] text-muted-foreground">
              CSS selector clicked once after the page loads, before capture starts -- use it to dismiss a cookie banner or first-visit welcome modal that would otherwise sit in every screenshot. Separate multiple selectors with commas to click them in sequence (some pages show more than one banner, e.g. a cookie-consent link plus an unrelated security notice). Each is independent -- a selector that isn't found on the page is skipped, it won't block the others. Leave blank if the page doesn't need it.
            </p>
          </div>
          <p className="text-[10px] text-muted-foreground">
            Rendered by a shared headless-Chromium instance (one browser process for every website/Grafana channel combined, one lightweight tab per channel) -- see webchannel-renderer.
          </p>
        </div>
      ) : (
        <div className="space-y-2 rounded-md border border-border p-2">
          <div className="flex flex-wrap gap-2">
            <div className="flex flex-col gap-1 flex-1 min-w-[220px]">
              <span className="text-[10px] text-muted-foreground">Grafana base URL</span>
              <Input className="h-8 text-xs" placeholder="http://grafana.local:3000"
                value={form.grafana_base_url} onChange={(e) => setForm({ ...form, grafana_base_url: e.target.value })} />
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-[10px] text-muted-foreground">Org ID</span>
              <input type="number" className="h-8 text-xs bg-background border border-border rounded px-2 w-20"
                value={form.grafana_org_id} onChange={(e) => setForm({ ...form, grafana_org_id: e.target.value })} />
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <div className="flex flex-col gap-1">
              <span className="text-[10px] text-muted-foreground">Dashboard UID</span>
              <Input className="h-8 text-xs w-40" autoComplete="off" value={form.grafana_dashboard_uid}
                onChange={(e) => setForm({ ...form, grafana_dashboard_uid: e.target.value })} />
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-[10px] text-muted-foreground">Panel ID</span>
              {/* autoComplete="off" alone doesn't reliably stop Chrome's
                  saved-credential autofill on a plain text input sitting
                  near a password field -- confirmed live (a saved username
                  landed here). A bogus autocomplete token is Chrome's own
                  documented workaround. */}
              <Input className="h-8 text-xs w-24" autoComplete="one-time-code" value={form.grafana_panel_id}
                onChange={(e) => setForm({ ...form, grafana_panel_id: e.target.value })} />
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-[10px] text-muted-foreground">API token {isEdit && '(leave blank to keep existing)'}</span>
            <Input type="password" className="h-8 text-xs" placeholder="glsa_..." autoComplete="new-password"
              value={form.grafana_api_token} onChange={(e) => setForm({ ...form, grafana_api_token: e.target.value })} />
          </div>
          <div className="flex flex-wrap gap-2">
            <div className="flex flex-col gap-1">
              <span className="text-[10px] text-muted-foreground">Time from</span>
              <Input className="h-8 text-xs w-28" value={form.grafana_time_from}
                onChange={(e) => setForm({ ...form, grafana_time_from: e.target.value })} />
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-[10px] text-muted-foreground">Time to</span>
              <Input className="h-8 text-xs w-28" value={form.grafana_time_to}
                onChange={(e) => setForm({ ...form, grafana_time_to: e.target.value })} />
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-[10px] text-muted-foreground">Screenshot interval (ms)</span>
              <input type="number" className="h-8 text-xs bg-background border border-border rounded px-2 w-32"
                value={form.screenshot_interval_ms} onChange={(e) => setForm({ ...form, screenshot_interval_ms: e.target.value })} />
            </div>
            <div className="flex flex-col gap-1 flex-1 min-w-[160px]">
              <span className="text-[10px] text-muted-foreground">Extra query params (optional)</span>
              <Input className="h-8 text-xs" placeholder="var-host=prod&theme=dark" value={form.grafana_extra_query}
                onChange={(e) => setForm({ ...form, grafana_extra_query: e.target.value })} />
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <div className="flex flex-col gap-1">
              <span className="text-[10px] text-muted-foreground">Panel width</span>
              <input type="number" className="h-8 text-xs bg-background border border-border rounded px-2 w-28"
                value={form.viewport_width} onChange={(e) => setForm({ ...form, viewport_width: e.target.value })} />
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-[10px] text-muted-foreground">Panel height</span>
              <input type="number" className="h-8 text-xs bg-background border border-border rounded px-2 w-28"
                value={form.viewport_height} onChange={(e) => setForm({ ...form, viewport_height: e.target.value })} />
            </div>
          </div>
          <p className="text-[10px] text-muted-foreground">
            Fetched directly from Grafana's own render API (needs the grafana-image-renderer plugin installed on that Grafana instance) -- no Chromium/browser involved for this channel at all.
          </p>
          <div className="flex items-center gap-2">
            <Button type="button" size="sm" variant="outline" className="h-7 text-xs"
              disabled={testing || !form.grafana_base_url || !form.grafana_dashboard_uid || !form.grafana_panel_id}
              onClick={handleTestGrafana}>
              {testing ? <Loader2 size={12} className="animate-spin" /> : 'Test connection'}
            </Button>
            {testResult && (
              <span className={`text-xs ${testResult.ok ? 'text-success' : 'text-destructive'}`}>{testResult.message}</span>
            )}
          </div>
        </div>
      )}

      <div className="flex flex-col gap-1">
        <span className="text-[10px] text-muted-foreground">Render mode</span>
        <select
          className="h-8 text-xs bg-background border border-border rounded px-2 w-full max-w-xs"
          value={form.render_mode}
          onChange={(e) => setForm({ ...form, render_mode: e.target.value as RenderMode })}
        >
          {RENDER_MODE_OPTIONS.map((opt) => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
        </select>
        <p className="text-[10px] text-muted-foreground max-w-md">
          {RENDER_MODE_OPTIONS.find((opt) => opt.value === form.render_mode)?.description}
        </p>
      </div>
    </div>
  )
}
