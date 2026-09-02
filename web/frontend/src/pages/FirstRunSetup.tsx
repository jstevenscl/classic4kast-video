import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, Loader2, ShieldCheck } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import api from '@/lib/api'

interface Props {
  onDone: () => void
}

// One-time first-launch prompt: create an admin login now, or explicitly
// skip it. Either choice is recorded server-side (credentials_choice_made
// in config.json) so this screen never shows again on its own -- a user who
// skips can still turn login on later from Settings -> Access & Security,
// same CredentialsCard used here just embedded on its own page.
export default function FirstRunSetup({ onDone }: Props) {
  const queryClient = useQueryClient()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['settings'] })

  const createMutation = useMutation({
    mutationFn: () => api.post('/settings/credentials/', { username: username.trim(), password }),
    onSuccess: (res) => {
      if (res.data.token) localStorage.setItem('classic4kast-session', res.data.token)
      invalidate()
      onDone()
    },
    onError: (err: any) => setError(err.response?.data?.detail ?? 'Could not create login.'),
  })

  const skipMutation = useMutation({
    mutationFn: () => api.post('/settings/credentials/skip/'),
    onSuccess: () => {
      invalidate()
      onDone()
    },
  })

  const mismatch = password.length > 0 && confirm.length > 0 && password !== confirm
  const canCreate = username.trim().length > 0 && password.length >= 6 && !mismatch

  return (
    <div className="min-h-screen flex items-center justify-center p-6 bg-background">
      <div className="w-full max-w-sm space-y-6">
        <div className="flex flex-col items-center gap-3">
          <img src="/brand/primary-full.png" alt="Classic4Kast Video+" className="w-full max-w-[280px]" />
          <p className="text-sm text-muted-foreground flex items-center gap-1.5">
            <ShieldCheck size={12} /> Set up an admin login (optional)
          </p>
        </div>

        <Card>
          <CardContent className="pt-6 space-y-4">
            <p className="text-xs text-muted-foreground">
              Fully optional -- classic4kast works fine with no login at all if this only runs on a private,
              trusted network. Set a username and password to require sign-in from now on, or skip this and
              enable it anytime later in Settings.
            </p>

            <div className="space-y-1.5">
              <label className="text-sm font-medium">Username</label>
              <Input
                autoFocus
                autoComplete="username"
                value={username}
                onChange={(e) => { setUsername(e.target.value); setError(null) }}
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-sm font-medium">Password</label>
              <Input
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(e) => { setPassword(e.target.value); setError(null) }}
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-sm font-medium">Confirm password</label>
              <Input
                type="password"
                autoComplete="new-password"
                value={confirm}
                onChange={(e) => { setConfirm(e.target.value); setError(null) }}
                onKeyDown={(e) => e.key === 'Enter' && canCreate && createMutation.mutate()}
              />
            </div>

            {mismatch && <p className="text-xs text-destructive">Passwords don't match.</p>}
            {password.length > 0 && password.length < 6 && (
              <p className="text-xs text-destructive">Password must be at least 6 characters.</p>
            )}
            {error && (
              <div className="flex items-center gap-2 text-sm text-red-400 bg-red-500/10 border border-red-500/20 rounded-md px-3 py-2">
                <AlertCircle size={14} className="shrink-0" /> {error}
              </div>
            )}

            <div className="flex items-center gap-2">
              <Button
                className="flex-1 gap-2"
                disabled={!canCreate || createMutation.isPending}
                onClick={() => createMutation.mutate()}
              >
                {createMutation.isPending
                  ? <><Loader2 size={14} className="animate-spin" /> Creating…</>
                  : 'Create admin login'
                }
              </Button>
              <Button
                variant="outline"
                className="flex-1"
                disabled={skipMutation.isPending}
                onClick={() => skipMutation.mutate()}
              >
                {skipMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : 'Skip for now'}
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
