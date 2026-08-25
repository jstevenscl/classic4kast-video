import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Eye, EyeOff, Link2, Loader2, Plus, Trash2, XCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import api from '@/lib/api'
import type { DispatcharrConnection } from '@/types'

// New to classic4kast -- EDM never needed this page because it always had
// exactly one Dispatcharr "instance" pre-configured elsewhere in its own
// monorepo. Here a Dispatcharr connection is a first-class, optional,
// multi-row resource (zero/one/many), so it gets its own CRUD screen. Every
// other Dispatcharr-aware surface (the deploy modal's connection picker)
// must degrade gracefully when this list is empty -- this page is where
// that emptiness is created or resolved.

interface FormState {
  label: string
  url: string
  token: string
}

function emptyForm(): FormState {
  return { label: '', url: '', token: '' }
}

function ConnectionRow({ conn, onDeleted }: { conn: DispatcharrConnection; onDeleted: () => void }) {
  const [revealed, setRevealed] = useState<string | null>(null)
  const [revealing, setRevealing] = useState(false)

  const deleteMutation = useMutation({
    mutationFn: () => api.delete(`/dispatcharr-connections/${conn.id}/`),
    onSuccess: onDeleted,
  })

  async function toggleReveal() {
    if (revealed) { setRevealed(null); return }
    setRevealing(true)
    try {
      const { data } = await api.get(`/dispatcharr-connections/${conn.id}/token/`)
      setRevealed(data.token)
    } finally {
      setRevealing(false)
    }
  }

  return (
    <div className="grid grid-cols-[1fr_1.4fr_1fr_80px] gap-0 border-b border-border last:border-0 text-sm items-center">
      <div className="px-3 py-2 font-medium">{conn.label}</div>
      <div className="px-3 py-2 text-muted-foreground truncate">{conn.url}</div>
      <div className="px-3 py-2 text-xs font-mono text-muted-foreground truncate">
        {revealing ? <Loader2 size={12} className="animate-spin" /> : revealed ?? '••••••••••••'}
      </div>
      <div className="px-2 py-2 flex items-center justify-center gap-1">
        <button
          className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground"
          title={revealed ? 'Hide token' : 'Reveal token'}
          onClick={toggleReveal}
        >
          {revealed ? <EyeOff size={12} /> : <Eye size={12} />}
        </button>
        <button
          className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-destructive"
          title="Delete connection"
          disabled={deleteMutation.isPending}
          onClick={() => deleteMutation.mutate()}
        >
          <Trash2 size={12} />
        </button>
      </div>
    </div>
  )
}

export default function Connections() {
  const queryClient = useQueryClient()
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState<FormState>(emptyForm())
  const [testResult, setTestResult] = useState<'ok' | 'fail' | null>(null)
  const [testError, setTestError] = useState('')

  const { data: connections, isLoading } = useQuery<DispatcharrConnection[]>({
    queryKey: ['dispatcharr-connections'],
    queryFn: () => api.get('/dispatcharr-connections/').then((r) => r.data),
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['dispatcharr-connections'] })

  const testMutation = useMutation({
    mutationFn: () => api.post('/dispatcharr-connections/connect/', { url: form.url, token: form.token }),
    onSuccess: () => { setTestResult('ok'); setTestError('') },
    onError: (err: any) => { setTestResult('fail'); setTestError(err.response?.data?.detail ?? 'Could not connect') },
  })

  const createMutation = useMutation({
    mutationFn: () => api.post('/dispatcharr-connections/', { label: form.label, url: form.url, token: form.token }),
    onSuccess: () => {
      invalidate()
      setShowCreate(false)
      setForm(emptyForm())
      setTestResult(null)
    },
  })

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Link2 size={20} className="text-primary" />
        <h1 className="text-xl font-semibold">Dispatcharr Connections</h1>
      </div>
      <p className="text-sm text-muted-foreground max-w-2xl">
        Optional -- classic4kast works fully standalone with zero connections configured. Add one here to enable deploying
        a rendered channel as a real Dispatcharr channel. Add more than one to deploy the same channel to several
        Dispatcharr instances, same-host or remote.
      </p>

      <Card>
        <CardContent className="pt-4 space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">Each row is one reachable Dispatcharr instance (URL + API token).</p>
            <Button size="sm" className="h-7 text-xs gap-1" onClick={() => setShowCreate((s) => !s)}>
              <Plus size={12} /> New connection
            </Button>
          </div>

          {showCreate && (
            <div className="space-y-3 rounded-md border border-border p-3">
              <div className="flex flex-wrap items-end gap-2">
                <div className="flex flex-col gap-1">
                  <span className="text-[10px] text-muted-foreground">Label</span>
                  <Input className="h-8 text-xs w-40" placeholder="e.g. Main Dispatcharr" value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} />
                </div>
                <div className="flex flex-col gap-1">
                  <span className="text-[10px] text-muted-foreground">URL</span>
                  <Input className="h-8 text-xs w-56" placeholder="http://100.x.x.x:9191" value={form.url} onChange={(e) => { setForm({ ...form, url: e.target.value }); setTestResult(null) }} />
                </div>
                <div className="flex flex-col gap-1">
                  <span className="text-[10px] text-muted-foreground">API token</span>
                  <Input className="h-8 text-xs w-56 font-mono" value={form.token} onChange={(e) => { setForm({ ...form, token: e.target.value }); setTestResult(null) }} />
                </div>
                <Button
                  size="sm" variant="outline" className="h-8 text-xs gap-1"
                  disabled={!form.url.trim() || !form.token.trim() || testMutation.isPending}
                  onClick={() => testMutation.mutate()}
                >
                  {testMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : 'Test connection'}
                </Button>
              </div>

              {testResult === 'ok' && (
                <p className="flex items-center gap-1.5 text-xs text-success"><CheckCircle2 size={12} /> Connected successfully.</p>
              )}
              {testResult === 'fail' && (
                <p className="flex items-center gap-1.5 text-xs text-destructive"><XCircle size={12} /> {testError}</p>
              )}

              <Button
                size="sm" className="h-8 text-xs"
                disabled={!form.label.trim() || !form.url.trim() || !form.token.trim() || createMutation.isPending}
                onClick={() => createMutation.mutate()}
              >
                {createMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : 'Save connection'}
              </Button>
              {createMutation.isError && (
                <p className="text-[10px] text-destructive">
                  {(createMutation.error as any)?.response?.data?.detail ?? 'Failed to save'}
                </p>
              )}
            </div>
          )}

          {isLoading ? (
            <div className="flex items-center gap-2 text-xs text-muted-foreground py-4"><Loader2 size={14} className="animate-spin" /> Loading…</div>
          ) : !connections?.length ? (
            <p className="text-sm text-muted-foreground py-6 text-center">
              No Dispatcharr connections configured -- classic4kast is running in standalone mode. Add one above to enable deploy.
            </p>
          ) : (
            <div className="rounded-lg border border-border overflow-hidden">
              <div className="grid grid-cols-[1fr_1.4fr_1fr_80px] gap-0 border-b border-border bg-accent/30 text-xs text-muted-foreground font-medium">
                <div className="px-3 py-2">Label</div>
                <div className="px-3 py-2">URL</div>
                <div className="px-3 py-2">Token</div>
                <div className="px-3 py-2" />
              </div>
              {connections.map((c) => (
                <ConnectionRow key={c.id} conn={c} onDeleted={invalidate} />
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
