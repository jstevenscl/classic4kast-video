import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Copy, Loader2, LogIn, Monitor, Plus, PlayCircle, RefreshCw, Rocket, Trash2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import StreamPlayer from '@/components/StreamPlayer'
import LoginSessionModal from '@/components/webchannel/LoginSessionModal'
import WebChannelDeployModal from '@/components/webchannel/WebChannelDeployModal'
import WebChannelForm, { emptyWebChannelForm, type WebChannelFormState } from '@/components/webchannel/WebChannelForm'
import { RENDER_MODE_OPTIONS } from '@/components/weather/channelConstants'
import api from '@/lib/api'
import type { WebChannel } from '@/types'

function previewUrl(slug: string) {
  return `/webchannel/${slug}/stream.m3u8`
}

function formFromChannel(ch: WebChannel): WebChannelFormState {
  return {
    slug: ch.slug, channel_name: ch.channel_name, source_type: ch.source_type,
    enabled: ch.enabled, render_mode: ch.render_mode,
    target_url: ch.target_url ?? '', viewport_width: String(ch.viewport_width), viewport_height: String(ch.viewport_height),
    screenshot_interval_ms: String(ch.screenshot_interval_ms), page_load_wait_ms: String(ch.page_load_wait_ms),
    device_scale_factor: String(ch.device_scale_factor), dismiss_selector: ch.dismiss_selector ?? '',
    grafana_base_url: ch.grafana_base_url ?? '', grafana_dashboard_uid: ch.grafana_dashboard_uid ?? '',
    grafana_panel_id: ch.grafana_panel_id ?? '', grafana_api_token: '',
    grafana_org_id: String(ch.grafana_org_id), grafana_time_from: ch.grafana_time_from, grafana_time_to: ch.grafana_time_to,
    grafana_extra_query: ch.grafana_extra_query ?? '',
  }
}

function payloadFromForm(form: WebChannelFormState) {
  return {
    slug: form.slug, channel_name: form.channel_name, source_type: form.source_type,
    enabled: form.enabled, render_mode: form.render_mode,
    target_url: form.source_type === 'url' ? form.target_url : null,
    viewport_width: Number(form.viewport_width) || 1280,
    viewport_height: Number(form.viewport_height) || 720,
    screenshot_interval_ms: Number(form.screenshot_interval_ms) || 1000,
    page_load_wait_ms: Number(form.page_load_wait_ms) || 2000,
    device_scale_factor: Number(form.device_scale_factor) || 1,
    dismiss_selector: form.source_type === 'url' ? (form.dismiss_selector || null) : null,
    grafana_base_url: form.source_type === 'grafana' ? form.grafana_base_url : null,
    grafana_dashboard_uid: form.source_type === 'grafana' ? form.grafana_dashboard_uid : null,
    grafana_panel_id: form.source_type === 'grafana' ? form.grafana_panel_id : null,
    // Blank means "don't change" on update (see patch handling below) and
    // "none" on create -- both map to omitting/nulling the field.
    grafana_api_token: form.grafana_api_token || null,
    grafana_org_id: Number(form.grafana_org_id) || 1,
    grafana_time_from: form.grafana_time_from || 'now-1h',
    grafana_time_to: form.grafana_time_to || 'now',
    grafana_extra_query: form.grafana_extra_query || null,
  }
}

function isFormValid(form: WebChannelFormState) {
  if (!form.slug || !form.channel_name) return false
  if (form.source_type === 'url') return !!form.target_url
  return !!(form.grafana_base_url && form.grafana_dashboard_uid && form.grafana_panel_id)
}

// Structurally mirrors pages/Channels.tsx (create/edit/delete/preview/
// render-now/deploy) against /api/webchannels/ instead of /api/channels/ --
// see WebChannelForm.tsx for why this has its own form rather than a
// source_type branch on the weather one, and WebChannelDeployModal.tsx for
// the same reasoning applied to Dispatcharr deploy.
export default function WebChannels() {
  const queryClient = useQueryClient()
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState<WebChannelFormState>(emptyWebChannelForm())
  const [editingChannel, setEditingChannel] = useState<WebChannel | null>(null)
  const [editForm, setEditForm] = useState<WebChannelFormState>(emptyWebChannelForm())
  const [player, setPlayer] = useState<{ url: string; name: string } | null>(null)
  const [deployingChannelId, setDeployingChannelId] = useState<number | null>(null)
  const [copiedChannelId, setCopiedChannelId] = useState<number | null>(null)
  const [loginSessionChannelId, setLoginSessionChannelId] = useState<number | null>(null)

  const { data: channels, isLoading } = useQuery<WebChannel[]>({
    queryKey: ['classic4kast-webchannels'],
    queryFn: () => api.get('/webchannels/').then((r) => r.data),
  })

  const { data: appSettings } = useQuery<{ dispatcharr_enabled: boolean }>({
    queryKey: ['settings'],
    queryFn: () => api.get('/settings/').then((r) => r.data),
  })
  const dispatcharrEnabled = appSettings?.dispatcharr_enabled ?? true

  const onPreview = (ch: WebChannel) => setPlayer({ url: previewUrl(ch.slug), name: ch.channel_name })

  // Fetches the real, externally-reachable stream URL (public URL + stream
  // key baked in, same assembly the deploy flow uses -- see
  // web_channel_routes.py's _web_channel_stream_url) and copies it, rather
  // than copying the admin-proxied previewUrl() above (that one only
  // resolves from inside this app's own origin, useless to hand to
  // Dispatcharr or a standalone player). Found from direct user feedback:
  // "nothing to show the url of where to reach the channel."
  const copyStreamUrlMutation = useMutation({
    mutationFn: (id: number) => api.get(`/webchannels/${id}/stream-url/`).then((r) => r.data.url as string),
    onSuccess: (url, id) => {
      // Found live: navigator.clipboard?.writeText(url).catch(...) throws
      // synchronously when clipboard is undefined (optional chaining only
      // guarded the .writeText call, not the .catch() after it) -- that
      // aborted this whole handler before setCopiedChannelId below ever
      // ran, so the checkmark silently never appeared even though the URL
      // fetch itself succeeded. try/catch is unconditionally safe here.
      try { navigator.clipboard?.writeText(url) } catch { /* no clipboard access in this context */ }
      setCopiedChannelId(id)
      setTimeout(() => setCopiedChannelId((prev) => (prev === id ? null : prev)), 2500)
    },
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['classic4kast-webchannels'] })

  const createMutation = useMutation({
    mutationFn: () => api.post('/webchannels/', payloadFromForm(form)),
    onSuccess: () => { invalidate(); setShowCreate(false); setForm(emptyWebChannelForm()) },
  })

  const updateMutation = useMutation({
    mutationFn: () => api.patch(`/webchannels/${editingChannel!.id}/`, payloadFromForm(editForm)),
    onSuccess: () => { invalidate(); setEditingChannel(null) },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/webchannels/${id}/`),
    onSuccess: invalidate,
  })

  const renderMutation = useMutation({
    mutationFn: (id: number) => api.post(`/webchannels/${id}/render/`),
    onSuccess: invalidate,
  })

  const clearSessionMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/webchannels/${id}/session/`),
    onSuccess: invalidate,
  })

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Monitor size={20} className="text-primary" />
        <h1 className="text-xl font-semibold">Web Channels</h1>
      </div>

      <Card>
        <CardContent className="pt-4 space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">
              Screenshot any website or Grafana dashboard into its own looping HLS channel -- same fire-on-start/on-demand/always-on lifecycle as weather channels.
            </p>
            <Button size="sm" className="h-7 text-xs gap-1" onClick={() => setShowCreate((s) => !s)}>
              <Plus size={12} /> New web channel
            </Button>
          </div>

          {showCreate && (
            <div className="space-y-3 rounded-md border border-border p-3">
              <WebChannelForm form={form} setForm={setForm} isEdit={false} />
              <div className="flex items-center gap-2">
                <Button size="sm" className="h-8 text-xs" disabled={!isFormValid(form) || createMutation.isPending} onClick={() => createMutation.mutate()}>
                  {createMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : 'Create'}
                </Button>
                {!isFormValid(form) && (
                  <p className="text-[10px] text-muted-foreground">
                    Missing: {[
                      !form.slug && 'slug',
                      !form.channel_name && 'channel name',
                      form.source_type === 'url' && !form.target_url && 'page URL',
                      form.source_type === 'grafana' && !form.grafana_base_url && 'Grafana base URL',
                      form.source_type === 'grafana' && !form.grafana_dashboard_uid && 'dashboard UID',
                      form.source_type === 'grafana' && !form.grafana_panel_id && 'panel ID',
                    ].filter(Boolean).join(', ')}
                  </p>
                )}
              </div>
              {createMutation.isError && (
                <p className="text-xs text-destructive">
                  {(createMutation.error as any)?.response?.data?.detail || (createMutation.error as any)?.message || 'Failed to create web channel.'}
                </p>
              )}
            </div>
          )}

          {isLoading ? (
            <div className="flex items-center gap-2 text-xs text-muted-foreground py-4"><Loader2 size={14} className="animate-spin" /> Loading…</div>
          ) : !channels?.length ? (
            <p className="text-sm text-muted-foreground py-4 text-center">No web channels yet. Create one to stream a website or Grafana dashboard.</p>
          ) : (
            <div className="rounded-lg border border-border overflow-hidden">
              <div className="grid grid-cols-[1.1fr_0.9fr_80px_1.3fr_270px] gap-0 border-b border-border bg-accent/30 text-xs text-muted-foreground font-medium">
                <div className="px-3 py-2">Channel</div>
                <div className="px-3 py-2">Slug</div>
                <div className="px-3 py-2">Source</div>
                <div className="px-3 py-2">Status</div>
                <div className="px-3 py-2" />
              </div>
              {channels.map((ch) => (
                <div key={ch.id} className="grid grid-cols-[1.1fr_0.9fr_80px_1.3fr_270px] gap-0 border-b border-border last:border-0 text-sm items-center">
                  <div className="px-3 py-2 font-medium">{ch.channel_name}</div>
                  <div className="px-3 py-2 text-muted-foreground">{ch.slug}</div>
                  <div className="px-3 py-2">
                    <Badge variant={ch.source_type === 'grafana' ? 'brand2' : 'brand3'}>{ch.source_type === 'grafana' ? 'Grafana' : 'Website'}</Badge>
                  </div>
                  <div className="px-3 py-2 flex flex-wrap gap-1">
                    <Badge variant={ch.enabled ? 'success' : 'outline'}>{ch.enabled ? 'Enabled' : 'Disabled'}</Badge>
                    {ch.render_mode !== 'on_demand' && (
                      <Badge
                        variant={ch.render_mode === 'always_on' ? 'brand2' : 'brand3'}
                        title={RENDER_MODE_OPTIONS.find((opt) => opt.value === ch.render_mode)?.description}
                      >
                        {RENDER_MODE_OPTIONS.find((opt) => opt.value === ch.render_mode)?.label}
                      </Badge>
                    )}
                    {ch.last_render_status === 'error' && (
                      <Badge variant="destructive" title={ch.last_render_error ?? undefined}>Render error</Badge>
                    )}
                    {ch.source_type === 'url' && (
                      <Badge variant={ch.has_session ? 'success' : 'outline'} title="Captured via 'Log in' -- reused automatically on every render">
                        {ch.has_session ? 'Session captured' : 'Not logged in'}
                      </Badge>
                    )}
                  </div>
                  <div className="px-2 py-2 flex items-center justify-center gap-1">
                    <button className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground" title="Preview live stream" onClick={() => onPreview(ch)}>
                      <PlayCircle size={12} />
                    </button>
                    {copiedChannelId === ch.id ? (
                      <CheckCircle2 size={12} className="text-success mx-1" />
                    ) : (
                      <button
                        className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground"
                        title="Copy this channel's real stream URL" disabled={copyStreamUrlMutation.isPending}
                        onClick={() => copyStreamUrlMutation.mutate(ch.id)}
                      >
                        <Copy size={12} />
                      </button>
                    )}
                    {dispatcharrEnabled && (
                      <button
                        className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground"
                        title="Deploy to a Dispatcharr connection"
                        onClick={() => setDeployingChannelId(ch.id)}
                      >
                        <Rocket size={12} />
                      </button>
                    )}
                    {ch.source_type === 'url' && (
                      <button
                        className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground"
                        title={ch.has_session ? 'Re-do login (replaces the saved session)' : 'Log in interactively -- for pages behind a login, including MFA'}
                        onClick={() => setLoginSessionChannelId(ch.id)}
                      >
                        <LogIn size={12} />
                      </button>
                    )}
                    {ch.source_type === 'url' && ch.has_session && (
                      <button
                        className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-destructive text-xs"
                        title="Forget the saved session"
                        disabled={clearSessionMutation.isPending}
                        onClick={() => clearSessionMutation.mutate(ch.id)}
                      >
                        clear
                      </button>
                    )}
                    <button
                      className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground"
                      title="Re-render now" disabled={renderMutation.isPending}
                      onClick={() => renderMutation.mutate(ch.id)}
                    >
                      <RefreshCw size={12} />
                    </button>
                    <button
                      className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground text-xs"
                      onClick={() => { setEditingChannel(ch); setEditForm(formFromChannel(ch)) }}
                    >
                      edit
                    </button>
                    <button className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-destructive" onClick={() => deleteMutation.mutate(ch.id)}>
                      <Trash2 size={12} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}

          {editingChannel && (
            <div
              className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
              onClick={(e) => { if (e.target === e.currentTarget) setEditingChannel(null) }}
            >
              <div className="w-full max-w-lg rounded-lg border border-border bg-card shadow-xl p-4 space-y-3 max-h-[90vh] overflow-y-auto">
                <p className="text-sm font-medium">Edit "{editingChannel.channel_name}"</p>
                <WebChannelForm form={editForm} setForm={setEditForm} isEdit={true} />
                <div className="flex gap-2 pt-1">
                  <Button size="sm" className="h-8 text-xs" disabled={!isFormValid(editForm) || updateMutation.isPending} onClick={() => updateMutation.mutate()}>
                    {updateMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : 'Save'}
                  </Button>
                  <Button size="sm" variant="outline" className="h-8 text-xs" onClick={() => setEditingChannel(null)}>Cancel</Button>
                </div>
                {updateMutation.isError && (
                  <p className="text-xs text-destructive">
                    {(updateMutation.error as any)?.response?.data?.detail || (updateMutation.error as any)?.message || 'Failed to save web channel.'}
                  </p>
                )}
              </div>
            </div>
          )}

          {deployingChannelId !== null && (() => {
            const liveChannel = channels?.find((c) => c.id === deployingChannelId)
            return liveChannel ? (
              <WebChannelDeployModal channel={liveChannel} onClose={() => setDeployingChannelId(null)} />
            ) : null
          })()}

          {loginSessionChannelId !== null && (() => {
            const liveChannel = channels?.find((c) => c.id === loginSessionChannelId)
            return liveChannel ? (
              <LoginSessionModal
                channel={liveChannel}
                onClose={() => setLoginSessionChannelId(null)}
                onCaptured={invalidate}
              />
            ) : null
          })()}
        </CardContent>
      </Card>

      {player && <StreamPlayer url={player.url} name={player.name} onClose={() => setPlayer(null)} />}
    </div>
  )
}
