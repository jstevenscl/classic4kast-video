import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, PlayCircle, Radio, RefreshCw } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import StreamPlayer from '@/components/StreamPlayer'
import { timeAgo } from '@/components/weather/channelConstants'
import api from '@/lib/api'
import type { WeatherStarChannel } from '@/types'

function previewUrl(slug: string, streamKey?: string | null) {
  const keySegment = streamKey ? `/${streamKey}` : ''
  return `/weatherstar/${slug}${keySegment}/stream.m3u8`
}

// Ported from EDM's WeatherStar.tsx FleetStatusTab.
export default function FleetStatus() {
  const queryClient = useQueryClient()
  const [player, setPlayer] = useState<{ url: string; name: string } | null>(null)

  const { data: channels, isLoading } = useQuery<WeatherStarChannel[]>({
    queryKey: ['classic4kast-channels'],
    queryFn: () => api.get('/channels/').then((r) => r.data),
    refetchInterval: 30_000,
  })

  const { data: streamKeyData } = useQuery<{ key: string | null }>({
    queryKey: ['classic4kast-stream-key'],
    queryFn: () => api.get('/config/stream-key/').then((r) => r.data),
  })

  const onPreview = (ch: WeatherStarChannel) => setPlayer({ url: previewUrl(ch.slug, streamKeyData?.key), name: ch.city_name })

  const renderMutation = useMutation({
    mutationFn: (id: number) => api.post(`/channels/${id}/render/`).then((r) => r.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['classic4kast-channels'] }),
  })

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Radio size={20} className="text-primary" />
        <h1 className="text-xl font-semibold">Fleet Status</h1>
      </div>

      <Card>
        <CardContent className="pt-4 space-y-3">
          <p className="text-xs text-muted-foreground">
            Last render status for each channel. Renders run automatically on a schedule; use "Re-render now" to force one immediately.
          </p>
          {isLoading ? (
            <div className="flex items-center gap-2 text-xs text-muted-foreground py-4"><Loader2 size={14} className="animate-spin" /> Loading…</div>
          ) : !channels?.length ? (
            <p className="text-sm text-muted-foreground py-4 text-center">No channels configured yet.</p>
          ) : (
            <div className="rounded-lg border border-border overflow-hidden">
              <div className="grid grid-cols-[1fr_1fr_1fr_1fr_1fr_90px_140px] gap-0 border-b border-border bg-accent/30 text-xs text-muted-foreground font-medium">
                <div className="px-3 py-2">City</div>
                <div className="px-3 py-2">Slug</div>
                <div className="px-3 py-2">Enabled</div>
                <div className="px-3 py-2">Last Render</div>
                <div className="px-3 py-2">Result</div>
                <div className="px-3 py-2" />
                <div className="px-3 py-2" />
              </div>
              {channels.map((ch) => {
                const isRendering = ch.force_render || (renderMutation.isPending && renderMutation.variables === ch.id)
                return (
                  <div key={ch.id} className="grid grid-cols-[1fr_1fr_1fr_1fr_1fr_90px_140px] gap-0 border-b border-border last:border-0 text-sm items-start">
                    <div className="px-3 py-2 font-medium">{ch.city_name}</div>
                    <div className="px-3 py-2 text-muted-foreground">{ch.slug}</div>
                    <div className="px-3 py-2">
                      <Badge variant={ch.enabled ? 'success' : 'outline'}>{ch.enabled ? 'Enabled' : 'Disabled'}</Badge>
                    </div>
                    <div className="px-3 py-2 text-xs text-muted-foreground">
                      {ch.last_render_at ? timeAgo(ch.last_render_at) : 'Never'}
                    </div>
                    <div className="px-3 py-2 space-y-1">
                      {ch.last_render_status === 'success' && <Badge variant="success">Success</Badge>}
                      {ch.last_render_status === 'error' && <Badge variant="destructive">Error</Badge>}
                      {!ch.last_render_status && <Badge variant="outline">Never rendered</Badge>}
                      {ch.last_render_status === 'error' && ch.last_render_error && (
                        <p className="text-[10px] text-destructive truncate max-w-[220px]" title={ch.last_render_error}>
                          {ch.last_render_error.length > 80 ? `${ch.last_render_error.slice(0, 80)}…` : ch.last_render_error}
                        </p>
                      )}
                    </div>
                    <div className="px-3 py-2">
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-7 text-xs gap-1"
                        disabled={!ch.last_render_at}
                        title={ch.last_render_at ? 'Preview live stream' : 'No render yet'}
                        onClick={() => onPreview(ch)}
                      >
                        <PlayCircle size={11} />
                        Preview
                      </Button>
                    </div>
                    <div className="px-3 py-2">
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-7 text-xs gap-1 whitespace-nowrap"
                        disabled={isRendering}
                        onClick={() => renderMutation.mutate(ch.id)}
                      >
                        {isRendering ? <Loader2 size={11} className="animate-spin" /> : <RefreshCw size={11} />}
                        Re-render now
                      </Button>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </CardContent>
      </Card>

      {player && <StreamPlayer url={player.url} name={player.name} onClose={() => setPlayer(null)} />}
    </div>
  )
}
