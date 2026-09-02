import { useEffect, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Loader2, RefreshCw, Settings as SettingsIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import api from '@/lib/api'
import type { RefreshAllResult } from '@/types'

// Ported from EDM's WeatherStar.tsx: PublicUrlCard, StreamKeyCard,
// RefreshAllCard, IdleTimeoutCard -- all grouped here under the "System ->
// Settings" nav item instead of living inline atop the Channels tab like
// EDM did, since this app has a dedicated Settings page and these are all
// fleet-wide admin knobs rather than per-channel ones.

function PublicUrlCard() {
  const [url, setUrl] = useState('')
  const [touched, setTouched] = useState(false)
  const [saved, setSaved] = useState(false)
  const queryClient = useQueryClient()

  const { data } = useQuery<{ url: string | null }>({
    queryKey: ['classic4kast-public-url'],
    queryFn: () => api.get('/config/public-url/').then((r) => r.data),
  })

  useEffect(() => {
    if (!touched && data?.url) setUrl(data.url)
  }, [data, touched])

  const saveMutation = useMutation({
    mutationFn: () => api.post('/config/public-url/', { url }),
    onSuccess: () => {
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
      queryClient.invalidateQueries({ queryKey: ['classic4kast-public-url'] })
    },
  })

  return (
    <Card>
      <CardContent className="pt-4 pb-4 space-y-2">
        <p className="text-sm font-medium">Public URL</p>
        <p className="text-xs text-muted-foreground">
          The URL Dispatcharr connections use to reach deployed classic4kast channels -- a real reachable address
          (Tailscale, LAN, or a public domain), not necessarily the same host classic4kast itself runs on.
        </p>
        <div className="flex items-center gap-2">
          <Input
            className="h-8 text-xs flex-1" placeholder="http://100.x.x.x"
            value={url} onChange={(e) => { setUrl(e.target.value); setTouched(true) }}
          />
          <Button size="sm" className="h-8 text-xs" disabled={saveMutation.isPending || !url.trim()} onClick={() => saveMutation.mutate()}>
            {saveMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : 'Save'}
          </Button>
          {saved && <CheckCircle2 size={14} className="text-success" />}
        </div>
      </CardContent>
    </Card>
  )
}

function StreamKeyCard() {
  const [key, setKey] = useState('')
  const [touched, setTouched] = useState(false)
  const [saved, setSaved] = useState(false)
  const queryClient = useQueryClient()

  const { data } = useQuery<{ key: string | null }>({
    queryKey: ['classic4kast-stream-key'],
    queryFn: () => api.get('/config/stream-key/').then((r) => r.data),
  })

  useEffect(() => {
    if (!touched && data?.key) setKey(data.key)
  }, [data, touched])

  const saveMutation = useMutation({
    mutationFn: () => api.post('/config/stream-key/', { key }),
    onSuccess: () => {
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
      queryClient.invalidateQueries({ queryKey: ['classic4kast-stream-key'] })
    },
  })

  const generateKey = () => {
    const bytes = new Uint8Array(24)
    crypto.getRandomValues(bytes)
    setKey(Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join(''))
    setTouched(true)
  }

  return (
    <Card>
      <CardContent className="pt-4 pb-4 space-y-2">
        <p className="text-sm font-medium">Stream access key</p>
        <p className="text-xs text-muted-foreground">
          Required only if the public URL above is a real internet-facing domain (not a Tailscale/private address) --
          gates the public stream so a guessable channel slug alone isn't enough to watch/hotlink it. Leave blank to
          leave the endpoint unauthenticated (fine for a private URL).
        </p>
        <div className="flex items-center gap-2">
          <Input
            className="h-8 text-xs flex-1 font-mono" placeholder="(no key required)"
            value={key} onChange={(e) => { setKey(e.target.value); setTouched(true) }}
          />
          <Button size="sm" variant="outline" className="h-8 text-xs" onClick={generateKey}>Generate</Button>
          <Button size="sm" className="h-8 text-xs" disabled={saveMutation.isPending} onClick={() => saveMutation.mutate()}>
            {saveMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : 'Save'}
          </Button>
          {saved && <CheckCircle2 size={14} className="text-success" />}
        </div>
      </CardContent>
    </Card>
  )
}

function CredentialsCard() {
  const queryClient = useQueryClient()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [saved, setSaved] = useState(false)

  const { data } = useQuery<{ has_credentials: boolean; credentials_env_override: boolean }>({
    queryKey: ['settings'],
    queryFn: () => api.get('/settings/').then((r) => r.data),
  })
  const hasCredentials = data?.has_credentials ?? false
  const envOverride = data?.credentials_env_override ?? false

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['settings'] })

  const saveMutation = useMutation({
    mutationFn: () => api.post('/settings/credentials/', { username: username.trim(), password }),
    onSuccess: (res) => {
      // Storing the fresh token here means enabling/changing login from this
      // page never immediately bounces the admin who just typed it to a
      // login screen -- see routes.py's set_credentials_endpoint comment.
      if (res.data.token) localStorage.setItem('classic4kast-session', res.data.token)
      invalidate()
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
      setUsername('')
      setPassword('')
      setConfirm('')
    },
  })

  const clearMutation = useMutation({
    mutationFn: () => api.delete('/settings/credentials/'),
    onSuccess: () => {
      localStorage.removeItem('classic4kast-session')
      invalidate()
      window.location.reload()
    },
  })

  const mismatch = password.length > 0 && confirm.length > 0 && password !== confirm

  if (envOverride) {
    return (
      <Card>
        <CardContent className="pt-4 pb-4 space-y-2">
          <p className="text-sm font-medium">Admin login</p>
          <p className="text-xs text-muted-foreground max-w-md">
            Pinned via the CLASSIC4KAST_ADMIN_USER / CLASSIC4KAST_ADMIN_PASSWORD environment variables -- can't be
            changed from this page. Unset them to manage credentials here instead.
          </p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardContent className="pt-4 pb-4 space-y-2">
        <p className="text-sm font-medium">Admin login</p>
        <p className="text-xs text-muted-foreground max-w-md">
          Optional -- classic4kast works fine with no login at all (fine for a private/trusted network). Set a
          username and password to require sign-in on every future visit; leave this alone if you don't want that.
          {hasCredentials && ' Login is currently enabled -- fill in below to change it, or remove it to go back to no login.'}
        </p>
        <div className="flex flex-wrap items-end gap-2">
          <div className="flex flex-col gap-1">
            <span className="text-[10px] text-muted-foreground">Username</span>
            <Input
              className="h-8 text-xs w-36" autoComplete="username"
              value={username} onChange={(e) => setUsername(e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-[10px] text-muted-foreground">Password</span>
            <Input
              className="h-8 text-xs w-36" type="password" autoComplete="new-password"
              value={password} onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-[10px] text-muted-foreground">Confirm password</span>
            <Input
              className="h-8 text-xs w-36" type="password" autoComplete="new-password"
              value={confirm} onChange={(e) => setConfirm(e.target.value)}
            />
          </div>
          <Button
            size="sm" className="h-8 text-xs"
            disabled={!username.trim() || password.length < 6 || mismatch || saveMutation.isPending}
            onClick={() => saveMutation.mutate()}
          >
            {saveMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : hasCredentials ? 'Update' : 'Enable login'}
          </Button>
          {hasCredentials && (
            <Button
              size="sm" variant="outline" className="h-8 text-xs"
              disabled={clearMutation.isPending}
              onClick={() => clearMutation.mutate()}
            >
              {clearMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : 'Remove login'}
            </Button>
          )}
          {saved && <CheckCircle2 size={14} className="text-success" />}
        </div>
        {mismatch && <p className="text-[10px] text-destructive">Passwords don't match.</p>}
        {password.length > 0 && password.length < 6 && (
          <p className="text-[10px] text-destructive">Password must be at least 6 characters.</p>
        )}
        {saveMutation.isError && (
          <p className="text-[10px] text-destructive">
            {(saveMutation.error as any)?.response?.data?.detail ?? 'Failed to save'}
          </p>
        )}
      </CardContent>
    </Card>
  )
}

function RefreshAllCard() {
  const [results, setResults] = useState<RefreshAllResult[] | null>(null)
  const queryClient = useQueryClient()

  const mutation = useMutation({
    mutationFn: () => api.post('/refresh-all/'),
    onSuccess: (res) => {
      setResults(res.data.results as RefreshAllResult[])
      queryClient.invalidateQueries({ queryKey: ['classic4kast-channels'] })
    },
  })

  const failed = (results ?? []).filter((r) => !r.ok)

  return (
    <Card>
      <CardContent className="pt-4 pb-4 space-y-2">
        <p className="text-sm font-medium">Refresh all deployed stream URLs</p>
        <p className="text-xs text-muted-foreground">
          Updates every already-deployed channel's stream URL on every Dispatcharr connection to match the public
          URL/key settings above -- use this after changing either one. Only the URL changes; channel number, group,
          logo, and EPG mapping are untouched.
        </p>
        <Button size="sm" className="h-8 text-xs gap-1" disabled={mutation.isPending} onClick={() => mutation.mutate()}>
          {mutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
          Refresh all
        </Button>
        {mutation.isError && (
          <p className="text-[10px] text-destructive">
            {(mutation.error as any)?.response?.data?.detail ?? 'Refresh failed'}
          </p>
        )}
        {results && (
          <p className="text-[10px] text-muted-foreground">
            {results.length - failed.length}/{results.length} deployments updated
            {failed.length > 0 && ` -- ${failed.length} failed (${failed.map((f) => `${f.slug}@${f.connection_label ?? f.connection_id}`).join(', ')})`}
          </p>
        )}
      </CardContent>
    </Card>
  )
}

function IdleTimeoutCard() {
  const [seconds, setSeconds] = useState(600)
  const [touched, setTouched] = useState(false)
  const [saved, setSaved] = useState(false)
  const queryClient = useQueryClient()

  const { data } = useQuery<{ seconds: number }>({
    queryKey: ['app-settings-idle'],
    queryFn: () => api.get('/config/idle-timeout/').then((r) => r.data),
  })

  useEffect(() => {
    if (!touched && data?.seconds != null) setSeconds(data.seconds)
  }, [data, touched])

  const saveMutation = useMutation({
    mutationFn: () => api.post('/config/idle-timeout/', { seconds }),
    onSuccess: () => {
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
      queryClient.invalidateQueries({ queryKey: ['app-settings-idle'] })
    },
  })

  return (
    <Card>
      <CardContent className="pt-4 pb-4 space-y-2">
        <p className="text-sm font-medium">Idle timeout</p>
        <p className="text-xs text-muted-foreground">
          How long a channel keeps streaming with no requests before its render pipeline is stopped and cold-started
          again on the next request.
        </p>
        <div className="flex items-center gap-2">
          <input
            type="number" min={30} max={7200}
            className="h-8 text-xs bg-background border border-border rounded px-2 w-28"
            value={seconds}
            onChange={(e) => { setSeconds(Number(e.target.value)); setTouched(true) }}
          />
          <span className="text-xs text-muted-foreground">seconds</span>
          <Button size="sm" className="h-8 text-xs" disabled={saveMutation.isPending} onClick={() => saveMutation.mutate()}>
            {saveMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : 'Save'}
          </Button>
          {saved && <CheckCircle2 size={14} className="text-success" />}
        </div>
      </CardContent>
    </Card>
  )
}

function HlsBufferCard() {
  const [size, setSize] = useState(16)
  const [touched, setTouched] = useState(false)
  const [saved, setSaved] = useState(false)
  const queryClient = useQueryClient()

  const { data } = useQuery<{ size: number }>({
    queryKey: ['app-settings-hls-list-size'],
    queryFn: () => api.get('/config/hls-list-size/').then((r) => r.data),
  })

  useEffect(() => {
    if (!touched && data?.size != null) setSize(data.size)
  }, [data, touched])

  const saveMutation = useMutation({
    mutationFn: () => api.post('/config/hls-list-size/', { size }),
    onSuccess: () => {
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
      queryClient.invalidateQueries({ queryKey: ['app-settings-hls-list-size'] })
    },
  })

  return (
    <Card>
      <CardContent className="pt-4 pb-4 space-y-2">
        <p className="text-sm font-medium">HLS buffer window</p>
        <p className="text-xs text-muted-foreground">
          How many 6-second segments the renderer keeps in each channel's live manifest -- a bigger window gives
          players more cushion against playback stutter, at the cost of a bit more live-edge delay. Only takes
          effect on a channel's next restart (idle-stop/resume, or use "Re-render now" on a channel's Fleet Status
          row to apply it immediately to an actively-watched one).
        </p>
        <div className="flex items-center gap-2">
          <input
            type="number" min={4} max={60}
            className="h-8 text-xs bg-background border border-border rounded px-2 w-28"
            value={size}
            onChange={(e) => { setSize(Number(e.target.value)); setTouched(true) }}
          />
          <span className="text-xs text-muted-foreground">segments (~{size * 6}s)</span>
          <Button size="sm" className="h-8 text-xs" disabled={saveMutation.isPending} onClick={() => saveMutation.mutate()}>
            {saveMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : 'Save'}
          </Button>
          {saved && <CheckCircle2 size={14} className="text-success" />}
        </div>
      </CardContent>
    </Card>
  )
}

function HlsSegmentTimeCard() {
  const [seconds, setSeconds] = useState(6)
  const [touched, setTouched] = useState(false)
  const [saved, setSaved] = useState(false)
  const queryClient = useQueryClient()

  const { data } = useQuery<{ seconds: number }>({
    queryKey: ['app-settings-hls-time'],
    queryFn: () => api.get('/config/hls-time/').then((r) => r.data),
  })

  useEffect(() => {
    if (!touched && data?.seconds != null) setSeconds(data.seconds)
  }, [data, touched])

  const saveMutation = useMutation({
    mutationFn: () => api.post('/config/hls-time/', { seconds }),
    onSuccess: () => {
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
      queryClient.invalidateQueries({ queryKey: ['app-settings-hls-time'] })
    },
  })

  return (
    <Card>
      <CardContent className="pt-4 pb-4 space-y-2">
        <p className="text-sm font-medium">HLS segment length</p>
        <p className="text-xs text-muted-foreground">
          How long each HLS segment is. A separate lever from the buffer window above -- this targets stutter at
          segment-boundary join points (a brief player-side hiccup independent of whether data was available in
          time), not buffer starvation. Longer segments mean fewer join points but more live-edge delay -- a
          non-issue for a weather channel. Only takes effect on a channel's next restart.
        </p>
        <div className="flex items-center gap-2">
          <input
            type="number" min={2} max={20}
            className="h-8 text-xs bg-background border border-border rounded px-2 w-28"
            value={seconds}
            onChange={(e) => { setSeconds(Number(e.target.value)); setTouched(true) }}
          />
          <span className="text-xs text-muted-foreground">seconds</span>
          <Button size="sm" className="h-8 text-xs" disabled={saveMutation.isPending} onClick={() => saveMutation.mutate()}>
            {saveMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : 'Save'}
          </Button>
          {saved && <CheckCircle2 size={14} className="text-success" />}
        </div>
      </CardContent>
    </Card>
  )
}

function DispatcharrToggleCard() {
  const queryClient = useQueryClient()

  const { data } = useQuery<{ dispatcharr_enabled: boolean }>({
    queryKey: ['settings'],
    queryFn: () => api.get('/settings/').then((r) => r.data),
  })
  const enabled = data?.dispatcharr_enabled ?? true

  const mutation = useMutation({
    mutationFn: (next: boolean) => api.post('/settings/dispatcharr-enabled/', { enabled: next }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['settings'] }),
  })

  return (
    <Card>
      <CardContent className="pt-4 pb-4 space-y-2">
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="text-sm font-medium">Dispatcharr integration</p>
            <p className="text-xs text-muted-foreground max-w-md">
              Off by default works fine for a standalone install -- turn this on to deploy channels into Dispatcharr
              and see the Dispatcharr nav item. Turning it back off only hides the controls; existing connections and
              deployments aren't touched.
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={enabled}
            disabled={mutation.isPending}
            onClick={() => mutation.mutate(!enabled)}
            className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${enabled ? 'bg-primary' : 'bg-muted'}`}
          >
            <span
              className={`absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${enabled ? 'translate-x-5' : 'translate-x-0'}`}
            />
          </button>
        </div>
      </CardContent>
    </Card>
  )
}

function SettingsGroup({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-3">
      <div className="px-0.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground/70">{label}</div>
      <div className="space-y-3">{children}</div>
    </div>
  )
}

export default function Settings() {
  const { data } = useQuery<{ dispatcharr_enabled: boolean }>({
    queryKey: ['settings'],
    queryFn: () => api.get('/settings/').then((r) => r.data),
  })
  const dispatcharrEnabled = data?.dispatcharr_enabled ?? true

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <SettingsIcon size={20} className="text-primary" />
        <h1 className="text-xl font-semibold">Settings</h1>
      </div>
      <SettingsGroup label="General">
        <DispatcharrToggleCard />
      </SettingsGroup>
      {dispatcharrEnabled && (
        <SettingsGroup label="Dispatcharr Integration">
          <PublicUrlCard />
          <RefreshAllCard />
        </SettingsGroup>
      )}
      <SettingsGroup label="Access & Security">
        <CredentialsCard />
        <StreamKeyCard />
      </SettingsGroup>
      <SettingsGroup label="Renderer Tuning">
        <IdleTimeoutCard />
        <HlsBufferCard />
        <HlsSegmentTimeCard />
      </SettingsGroup>
    </div>
  )
}
