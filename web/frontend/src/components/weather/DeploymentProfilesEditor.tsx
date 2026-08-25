import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import api from '@/lib/api'

interface DeployedProfileState {
  id: number
  name: string
  enabled: boolean
}

// Ported from EDM's WeatherStar.tsx DeploymentProfilesEditor -- instance_id
// renamed connection_id throughout. Edits which channel profiles an
// ALREADY-deployed channel is enabled on, reading/writing against
// Dispatcharr's real per-profile membership (not just this deployment's
// last-known channel_profile_ids, which can go stale if Dispatcharr's own
// UI changed it since).
//
// apiBase: 'channels' (default, weather) or 'webchannels' -- both routers
// expose an identically-shaped .../deploy/{connectionId}/profiles/ endpoint
// (see web_channel_routes.py's deploy section), so this one editor covers
// both feature's DeployModal without a weather-specific dependency.
export default function DeploymentProfilesEditor({
  channelId, connectionId, onClose, apiBase = 'channels',
}: { channelId: number; connectionId: number; onClose: () => void; apiBase?: 'channels' | 'webchannels' }) {
  const queryClient = useQueryClient()
  const [selected, setSelected] = useState<Set<number> | null>(null)

  const { data: profiles, isLoading } = useQuery<DeployedProfileState[]>({
    queryKey: ['classic4kast-deploy-profiles', apiBase, channelId, connectionId],
    queryFn: () => api.get(`/${apiBase}/${channelId}/deploy/${connectionId}/profiles/`).then((r) => r.data),
  })

  useEffect(() => {
    if (profiles && selected === null) {
      setSelected(new Set(profiles.filter((p) => p.enabled).map((p) => p.id)))
    }
  }, [profiles, selected])

  const saveMutation = useMutation({
    mutationFn: () =>
      api.patch(`/${apiBase}/${channelId}/deploy/${connectionId}/profiles/`, {
        channel_profile_ids: [...(selected ?? [])],
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [apiBase === 'webchannels' ? 'classic4kast-webchannels' : 'classic4kast-channels'] })
      queryClient.invalidateQueries({ queryKey: ['classic4kast-deploy-profiles', apiBase, channelId, connectionId] })
      onClose()
    },
  })

  const toggle = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <div className="rounded border border-border p-2 space-y-1.5 bg-accent/20">
      <p className="text-[10px] text-muted-foreground uppercase tracking-wide">Channel profiles on this connection</p>
      {isLoading || !profiles ? (
        <div className="flex items-center gap-2 text-xs text-muted-foreground py-1"><Loader2 size={12} className="animate-spin" /> Loading…</div>
      ) : (
        <div className="space-y-1 max-h-32 overflow-y-auto">
          {profiles.map((p) => (
            <label key={p.id} className="flex items-center gap-1.5 text-xs px-1 py-0.5 rounded hover:bg-accent cursor-pointer">
              <input type="checkbox" checked={selected?.has(p.id) ?? false} onChange={() => toggle(p.id)} />
              {p.name}
            </label>
          ))}
        </div>
      )}
      {saveMutation.isError && (
        <p className="text-[10px] text-destructive">
          {(saveMutation.error as any)?.response?.data?.detail ?? 'Failed to save'}
        </p>
      )}
      <div className="flex gap-2 pt-0.5">
        <Button size="sm" className="h-7 text-xs" disabled={saveMutation.isPending || isLoading} onClick={() => saveMutation.mutate()}>
          {saveMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : 'Save'}
        </Button>
        <Button size="sm" variant="outline" className="h-7 text-xs" onClick={onClose}>Cancel</Button>
      </div>
    </div>
  )
}
