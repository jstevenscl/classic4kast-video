import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, Copy, Download, ListMusic, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import api from '@/lib/api'
import type { WeatherStarChannel, WebChannel } from '@/types'

// Standalone alternative to Dispatcharr deploy -- builds a plain .m3u8
// playlist from a picked set of weather/web channels, for VLC/Threadfin/
// Jellyfin/a smart TV app. Reuses the exact same public-URL/stream-key
// plumbing Dispatcharr's own "Redirect" profile deploy uses (see
// m3u_routes.py's module docstring) -- no separate URL setting here.
export default function ExportM3U() {
  const [weatherSlugs, setWeatherSlugs] = useState<string[]>([])
  const [webSlugs, setWebSlugs] = useState<string[]>([])
  const [downloadError, setDownloadError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const { data: channels } = useQuery<WeatherStarChannel[]>({
    queryKey: ['classic4kast-channels'],
    queryFn: () => api.get('/channels/').then((r) => r.data),
  })
  const { data: webChannels } = useQuery<WebChannel[]>({
    queryKey: ['classic4kast-webchannels'],
    queryFn: () => api.get('/webchannels/').then((r) => r.data),
  })
  const { data: publicUrlData } = useQuery<{ url: string | null }>({
    queryKey: ['classic4kast-public-url'],
    queryFn: () => api.get('/config/public-url/').then((r) => r.data),
  })
  const { data: streamKeyData } = useQuery<{ key: string | null }>({
    queryKey: ['classic4kast-stream-key'],
    queryFn: () => api.get('/config/stream-key/').then((r) => r.data),
  })

  const toggleWeather = (slug: string) => {
    setWeatherSlugs((prev) => (prev.includes(slug) ? prev.filter((s) => s !== slug) : [...prev, slug]))
  }
  const toggleWeb = (slug: string) => {
    setWebSlugs((prev) => (prev.includes(slug) ? prev.filter((s) => s !== slug) : [...prev, slug]))
  }

  const selectedCount = weatherSlugs.length + webSlugs.length
  const streamKey = streamKeyData?.key ?? ''
  const hasNoKey = !streamKey
  const publicUrl = publicUrlData?.url ?? ''
  const looksPrivate = /^https?:\/\/(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|[^.]+\.ts\.net)/i.test(publicUrl)

  const m3uParams = () => {
    const params = new URLSearchParams()
    if (weatherSlugs.length) params.set('weather_slugs', weatherSlugs.join(','))
    if (webSlugs.length) params.set('web_slugs', webSlugs.join(','))
    if (streamKey) params.set('key', streamKey)
    return params
  }

  // The URL to hand a non-interactive fetcher (Dispatcharr's M3U source,
  // Threadfin, Jellyfin) that polls on its own schedule -- deliberately NOT
  // behind session auth (see m3u_routes.py's module docstring for why),
  // gated only by the stream key baked in above when one's set. Absolute,
  // not relative -- whatever's fetching it isn't running the SPA on this
  // origin.
  const shareableUrl = publicUrl ? `${publicUrl.replace(/\/+$/, '')}/api/m3u/?${m3uParams().toString()}` : ''

  const downloadMutation = useMutation({
    mutationFn: async () => {
      const res = await api.get(`/m3u/?${m3uParams().toString()}`, { responseType: 'blob' })
      const url = URL.createObjectURL(res.data as Blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'classic4kast.m3u8'
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    },
    onError: (err: any) => setDownloadError(err.response?.data?.detail ?? 'Could not generate the playlist'),
  })

  const copyUrl = async () => {
    await navigator.clipboard.writeText(shareableUrl)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <ListMusic size={20} className="text-primary" />
        <h1 className="text-xl font-semibold">Export M3U</h1>
      </div>
      <p className="text-sm text-muted-foreground max-w-2xl">
        An alternative to Dispatcharr deploy -- pick channels below and download a plain .m3u8 playlist for
        VLC, Threadfin, Jellyfin, or a smart TV app. Uses the same Public URL (and stream key, if set) as
        Dispatcharr's own "Redirect" stream profile -- see <span className="font-medium">Settings</span>.
      </p>

      {!publicUrl && (
        <Card>
          <CardContent className="pt-4 pb-4">
            <p className="flex items-center gap-2 text-sm text-destructive">
              <AlertTriangle size={14} className="shrink-0" /> Set a Public URL first (Settings → Dispatcharr
              Integration) -- the playlist can't point players anywhere without it.
            </p>
          </CardContent>
        </Card>
      )}

      {publicUrl && hasNoKey && !looksPrivate && (
        <Card>
          <CardContent className="pt-4 pb-4">
            <p className="flex items-center gap-2 text-sm text-amber-600">
              <AlertTriangle size={14} className="shrink-0" /> No stream key is set and your Public URL doesn't
              look like a private/Tailscale address -- anyone who gets this playlist file can watch these
              streams. Set a stream key in Settings first if that's not OK.
            </p>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="pt-4 pb-4 space-y-2">
          <p className="text-sm font-medium">Weather channels</p>
          {!channels?.length && <p className="text-xs text-muted-foreground">No weather channels yet.</p>}
          <div className="space-y-1">
            {(channels ?? []).map((c) => (
              <label key={c.slug} className="flex items-center gap-2 text-sm px-1 py-1 rounded hover:bg-accent cursor-pointer">
                <input type="checkbox" checked={weatherSlugs.includes(c.slug)} onChange={() => toggleWeather(c.slug)} />
                {c.city_name} <span className="text-xs text-muted-foreground">({c.slug})</span>
              </label>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="pt-4 pb-4 space-y-2">
          <p className="text-sm font-medium">Web channels</p>
          {!webChannels?.length && <p className="text-xs text-muted-foreground">No web channels yet.</p>}
          <div className="space-y-1">
            {(webChannels ?? []).map((c) => (
              <label key={c.slug} className="flex items-center gap-2 text-sm px-1 py-1 rounded hover:bg-accent cursor-pointer">
                <input type="checkbox" checked={webSlugs.includes(c.slug)} onChange={() => toggleWeb(c.slug)} />
                {c.channel_name} <span className="text-xs text-muted-foreground">({c.slug})</span>
              </label>
            ))}
          </div>
        </CardContent>
      </Card>

      {selectedCount > 0 && publicUrl && (
        <Card>
          <CardContent className="pt-4 pb-4 space-y-2">
            <p className="text-sm font-medium">Playlist URL</p>
            <p className="text-xs text-muted-foreground">
              Paste this into Dispatcharr's M3U &amp; EPG Manager (Add M3U Account → URL) or Threadfin/Jellyfin as
              an M3U source -- it's fetched directly, no login required, so it always reflects your current
              selection below.
            </p>
            <div className="flex items-center gap-2">
              <Input className="h-8 text-xs flex-1 font-mono" readOnly value={shareableUrl} onClick={(e) => (e.target as HTMLInputElement).select()} />
              <Button size="sm" variant="outline" className="h-8 text-xs gap-1" onClick={copyUrl}>
                {copied ? <CheckCircle2 size={12} className="text-success" /> : <Copy size={12} />}
                {copied ? 'Copied' : 'Copy'}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      <Button
        className="gap-2"
        disabled={selectedCount === 0 || !publicUrl || downloadMutation.isPending}
        onClick={() => { setDownloadError(null); downloadMutation.mutate() }}
      >
        {downloadMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
        Download playlist ({selectedCount} channel{selectedCount === 1 ? '' : 's'})
      </Button>
      {downloadError && <p className="text-xs text-destructive">{downloadError}</p>}
    </div>
  )
}
