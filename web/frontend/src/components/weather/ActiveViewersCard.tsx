import { useQuery } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import api from '@/lib/api'
import type { ChannelStatus } from '@/types'

function formatIdleSeconds(s: number): string {
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m`
  return `${Math.floor(m / 60)}h${m % 60}m`
}

// Ported from EDM's WeatherStar.tsx ActiveViewersCard. Reads GET /api/status
// (the web backend's proxy of the renderer's own in-memory per-city viewer
// state) -- a "Redirect"-profile deploy sends viewers straight to the
// renderer, bypassing Dispatcharr's own proxy/viewer-count entirely, so
// this is the only place that state is visible at all.
export default function ActiveViewersCard() {
  const { data, isLoading, isError } = useQuery<ChannelStatus[]>({
    queryKey: ['classic4kast-status'],
    queryFn: () => api.get('/status/').then((r) => r.data),
    refetchInterval: 5000,
  })

  const watching = (data ?? []).filter((c) => c.status === 'watching')
  const idle = (data ?? []).filter((c) => c.status !== 'watching')

  return (
    <Card>
      <CardContent className="pt-4 pb-4 space-y-3">
        <p className="text-sm font-medium">Active viewers</p>
        <p className="text-xs text-muted-foreground">
          Which channels currently have a real viewer -- Dispatcharr can't show this itself since "Redirect" sends the
          player straight to the stream, bypassing its own proxy entirely.
        </p>
        {isError ? (
          <p className="text-xs text-destructive">Renderer unreachable -- can't read live status right now.</p>
        ) : isLoading ? (
          <div className="flex items-center gap-2 text-xs text-muted-foreground"><Loader2 size={12} className="animate-spin" /> Loading…</div>
        ) : (data?.length ?? 0) === 0 ? (
          <p className="text-xs text-muted-foreground">No channels configured yet.</p>
        ) : (
          <div className="space-y-1">
            {watching.length === 0 && <p className="text-xs text-muted-foreground">Nobody's watching right now.</p>}
            {watching.map((c) => (
              <div key={c.slug} className="flex items-center justify-between text-xs px-2 py-1.5 rounded border border-success/40 bg-success/5">
                <span className="font-medium">{c.city_name}</span>
                <Badge variant="success">watching</Badge>
              </div>
            ))}
            {idle.length > 0 && (
              <details className="pt-1">
                <summary className="text-[10px] text-muted-foreground cursor-pointer uppercase tracking-wide">Idle ({idle.length})</summary>
                <div className="space-y-1 pt-1">
                  {idle.map((c) => (
                    <div key={c.slug} className="flex items-center justify-between text-xs px-2 py-1 rounded border border-border">
                      <span className="text-muted-foreground">{c.city_name}</span>
                      <span className="text-[10px] text-muted-foreground">
                        {c.status}{c.idle_seconds != null ? ` — idle ${formatIdleSeconds(c.idle_seconds)}` : ''}
                      </span>
                    </div>
                  ))}
                </div>
              </details>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
