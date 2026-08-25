import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Cloud, Loader2, Plus, PlayCircle, Rocket, Trash2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import StreamPlayer from '@/components/StreamPlayer'
import ActiveViewersCard from '@/components/weather/ActiveViewersCard'
import ChannelForm, { emptyForm, type ChannelFormState } from '@/components/weather/ChannelForm'
import DeployModal from '@/components/weather/DeployModal'
import { RENDER_MODE_OPTIONS } from '@/components/weather/channelConstants'
import api from '@/lib/api'
import type { WeatherStarChannel } from '@/types'

// Preview URL is proxied through this app's own backend (same-origin
// rationale as EDM's own /weatherstar/ nginx route -- an admin's browser
// generally can't reach the renderer container's loopback-only dev port
// directly). streamKey, when set, must be inserted as the same path segment
// the deploy endpoint bakes into a real deployed Stream's URL.
function previewUrl(slug: string, streamKey?: string | null) {
  const keySegment = streamKey ? `/${streamKey}` : ''
  return `/weatherstar/${slug}${keySegment}/stream.m3u8`
}

function formFromChannel(ch: WeatherStarChannel): ChannelFormState {
  return {
    slug: ch.slug,
    city_name: ch.city_name,
    location_query: ch.location_query,
    lat: String(ch.lat),
    lon: String(ch.lon),
    units: ch.units,
    enabled: ch.enabled,
    render_mode: ch.render_mode,
    country: ch.country,
    ec_city_id: ch.ec_city_id ?? '',
    screens: { ...ch.screens },
  }
}

// Ported from EDM's WeatherStar.tsx ChannelsTab -- channel list, create/edit
// forms, deploy entry point. Instance concept replaced by Dispatcharr
// connection throughout (see DeployModal).
export default function Channels() {
  const queryClient = useQueryClient()
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState<ChannelFormState>(emptyForm())
  const [editingChannel, setEditingChannel] = useState<WeatherStarChannel | null>(null)
  const [editForm, setEditForm] = useState<ChannelFormState>(emptyForm())
  const [deployingChannelId, setDeployingChannelId] = useState<number | null>(null)
  const [player, setPlayer] = useState<{ url: string; name: string } | null>(null)

  const { data: channels, isLoading } = useQuery<WeatherStarChannel[]>({
    queryKey: ['classic4kast-channels'],
    queryFn: () => api.get('/channels/').then((r) => r.data),
  })

  const { data: streamKeyData } = useQuery<{ key: string | null }>({
    queryKey: ['classic4kast-stream-key'],
    queryFn: () => api.get('/config/stream-key/').then((r) => r.data),
  })

  const { data: appSettings } = useQuery<{ dispatcharr_enabled: boolean }>({
    queryKey: ['settings'],
    queryFn: () => api.get('/settings/').then((r) => r.data),
  })
  const dispatcharrEnabled = appSettings?.dispatcharr_enabled ?? true

  const onPreview = (ch: WeatherStarChannel) => setPlayer({ url: previewUrl(ch.slug, streamKeyData?.key), name: ch.city_name })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['classic4kast-channels'] })

  const createMutation = useMutation({
    mutationFn: () =>
      api.post('/channels/', {
        slug: form.slug,
        city_name: form.city_name,
        location_query: form.location_query,
        lat: Number(form.lat),
        lon: Number(form.lon),
        units: form.units,
        screens: form.screens,
        enabled: form.enabled,
        render_mode: form.render_mode,
        country: form.country,
        ec_city_id: form.ec_city_id || null,
      }),
    onSuccess: () => {
      invalidate()
      setShowCreate(false)
      setForm(emptyForm())
    },
  })

  const updateMutation = useMutation({
    mutationFn: () =>
      api.patch(`/channels/${editingChannel!.id}/`, {
        city_name: editForm.city_name,
        location_query: editForm.location_query,
        lat: Number(editForm.lat),
        lon: Number(editForm.lon),
        units: editForm.units,
        screens: editForm.screens,
        enabled: editForm.enabled,
        render_mode: editForm.render_mode,
        country: editForm.country,
        ec_city_id: editForm.ec_city_id || null,
      }),
    onSuccess: () => {
      invalidate()
      setEditingChannel(null)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/channels/${id}/`),
    onSuccess: invalidate,
  })

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Cloud size={20} className="text-primary" />
        <h1 className="text-xl font-semibold">Channels</h1>
      </div>

      <ActiveViewersCard />

      <Card>
        <CardContent className="pt-4 space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">
              Each channel is a city config the renderer turns into a looping weather display.
            </p>
            <Button size="sm" className="h-7 text-xs gap-1" onClick={() => setShowCreate((s) => !s)}>
              <Plus size={12} /> New channel
            </Button>
          </div>

          {showCreate && (
            <div className="space-y-3 rounded-md border border-border p-3">
              <ChannelForm form={form} setForm={setForm} isEdit={false} />
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  className="h-8 text-xs"
                  disabled={!form.slug || !form.city_name || !form.location_query || !form.lat || !form.lon || (form.country === 'CA' && !form.ec_city_id.trim()) || createMutation.isPending}
                  onClick={() => createMutation.mutate()}
                >
                  {createMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : 'Create'}
                </Button>
                {/* Was silently disabled with zero explanation -- looked
                    exactly like a failed create when it was really just an
                    unmet required field (most often: lat/lon never got
                    filled in because "Look up lat/lon" was never clicked
                    or its lookup failed). Spell out what's actually
                    missing instead of leaving the button inert. */}
                {(!form.slug || !form.city_name || !form.location_query || !form.lat || !form.lon || (form.country === 'CA' && !form.ec_city_id.trim())) && (
                  <p className="text-[10px] text-muted-foreground">
                    Missing: {[
                      !form.slug && 'slug',
                      !form.city_name && 'city name',
                      !form.location_query && 'location query',
                      (!form.lat || !form.lon) && 'lat/lon (use "Look up lat/lon" or enter manually)',
                      form.country === 'CA' && !form.ec_city_id.trim() && 'Environment Canada city ID',
                    ].filter(Boolean).join(', ')}
                  </p>
                )}
              </div>
              {createMutation.isError && (
                <p className="text-xs text-destructive">
                  {(createMutation.error as any)?.response?.data?.detail || (createMutation.error as any)?.message || 'Failed to create channel.'}
                </p>
              )}
            </div>
          )}

          {isLoading ? (
            <div className="flex items-center gap-2 text-xs text-muted-foreground py-4"><Loader2 size={14} className="animate-spin" /> Loading…</div>
          ) : !channels?.length ? (
            <p className="text-sm text-muted-foreground py-4 text-center">No channels yet. Create one to start rendering weather.</p>
          ) : (
            <div className="rounded-lg border border-border overflow-hidden">
              <div className="grid grid-cols-[1.2fr_1fr_1fr_80px_120px] gap-0 border-b border-border bg-accent/30 text-xs text-muted-foreground font-medium">
                <div className="px-3 py-2">City</div>
                <div className="px-3 py-2">Slug</div>
                <div className="px-3 py-2">Location Query</div>
                <div className="px-3 py-2">Status</div>
                <div className="px-3 py-2" />
              </div>
              {channels.map((ch) => (
                <div key={ch.id} className="grid grid-cols-[1.2fr_1fr_1fr_80px_120px] gap-0 border-b border-border last:border-0 text-sm items-center">
                  <div className="px-3 py-2 font-medium">{ch.city_name}</div>
                  <div className="px-3 py-2 text-muted-foreground">{ch.slug}</div>
                  <div className="px-3 py-2 text-muted-foreground truncate">{ch.location_query}</div>
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
                    {ch.country !== 'US' && (
                      <Badge variant="brand3">{ch.country === 'CA' ? 'Canada' : 'International'}</Badge>
                    )}
                  </div>
                  <div className="px-2 py-2 flex items-center justify-center gap-1">
                    <button
                      className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground"
                      title="Preview live stream"
                      onClick={() => onPreview(ch)}
                    >
                      <PlayCircle size={12} />
                    </button>
                    {dispatcharrEnabled && (
                      <button
                        className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground"
                        title="Deploy to a Dispatcharr connection"
                        onClick={() => setDeployingChannelId(ch.id)}
                      >
                        <Rocket size={12} />
                      </button>
                    )}
                    <button
                      className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground text-xs"
                      onClick={() => { setEditingChannel(ch); setEditForm(formFromChannel(ch)) }}
                    >
                      edit
                    </button>
                    <button
                      className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-destructive"
                      onClick={() => deleteMutation.mutate(ch.id)}
                    >
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
              <div className="w-full max-w-lg rounded-lg border border-border bg-card shadow-xl p-4 space-y-3">
                <p className="text-sm font-medium">Edit "{editingChannel.city_name}"</p>
                <ChannelForm form={editForm} setForm={setEditForm} isEdit={true} />
                <div className="flex gap-2 pt-1">
                  <Button size="sm" className="h-8 text-xs" disabled={updateMutation.isPending || (editForm.country === 'CA' && !editForm.ec_city_id.trim())} onClick={() => updateMutation.mutate()}>
                    {updateMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : 'Save'}
                  </Button>
                  <Button size="sm" variant="outline" className="h-8 text-xs" onClick={() => setEditingChannel(null)}>Cancel</Button>
                </div>
                {updateMutation.isError && (
                  <p className="text-xs text-destructive">
                    {(updateMutation.error as any)?.response?.data?.detail || (updateMutation.error as any)?.message || 'Failed to save channel.'}
                  </p>
                )}
              </div>
            </div>
          )}

          {deployingChannelId !== null && (() => {
            const liveChannel = channels?.find((c) => c.id === deployingChannelId)
            return liveChannel ? (
              <DeployModal channel={liveChannel} onClose={() => setDeployingChannelId(null)} />
            ) : null
          })()}
        </CardContent>
      </Card>

      {player && <StreamPlayer url={player.url} name={player.name} onClose={() => setPlayer(null)} />}
    </div>
  )
}
