import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Flame, Link2, ListMusic, ListVideo, Loader2, LogOut, Monitor, Moon,
  Palette, Radio, Settings as SettingsIcon, Sun,
} from 'lucide-react'
import Login from '@/pages/Login'
import FirstRunSetup from '@/pages/FirstRunSetup'
import Channels from '@/pages/Channels'
import WebChannels from '@/pages/WebChannels'
import FleetStatus from '@/pages/FleetStatus'
import ExportM3U from '@/pages/ExportM3U'
import Connections from '@/pages/Connections'
import Settings from '@/pages/Settings'
import api from '@/lib/api'

// App shell ported from VOD & DVR Manager's App.tsx -- same theme
// init/localStorage pattern (key renamed vodmanager-theme -> classic4kast-theme),
// same [240px_1fr] sticky sidebar+header layout, same auth
// checking/login/ready gating -- with this product's own nav items instead
// of VOD's (Channels/Fleet Status, Dispatcharr Connections, Settings).

export const THEMES = ['dark', 'mid', 'light', 'mono', 'warm'] as const
export type Theme = typeof THEMES[number]

const THEME_META: Record<Theme, { label: string; icon: React.ReactNode }> = {
  dark:  { label: 'Dark',  icon: <Moon size={11} /> },
  mid:   { label: 'Mid',   icon: <Palette size={11} /> },
  light: { label: 'Light', icon: <Sun size={11} /> },
  mono:  { label: 'Mono',  icon: <span className="text-[10px] font-bold leading-none">M</span> },
  warm:  { label: 'Warm',  icon: <Flame size={11} /> },
}

function initTheme(): Theme {
  const saved = localStorage.getItem('classic4kast-theme') as Theme | null
  const t: Theme = (saved && (THEMES as readonly string[]).includes(saved)) ? saved as Theme : 'dark'
  document.documentElement.setAttribute('data-theme', t)
  return t
}

type AuthState = 'checking' | 'first-run' | 'login' | 'ready'
export type Tab = 'channels' | 'webchannels' | 'fleet' | 'm3u' | 'connections' | 'settings'

interface NavItem { label: string; icon: React.ReactNode; tab: Tab }
interface NavGroup { label: string; items: NavItem[] }

const NAV_GROUPS: NavGroup[] = [
  { label: 'Channels', items: [
    { label: 'Channels', icon: <ListVideo size={15} />, tab: 'channels' },
    { label: 'Web Channels', icon: <Monitor size={15} />, tab: 'webchannels' },
    { label: 'Fleet Status', icon: <Radio size={15} />, tab: 'fleet' },
    { label: 'Export M3U', icon: <ListMusic size={15} />, tab: 'm3u' },
  ] },
  { label: 'Dispatcharr', items: [
    { label: 'Connections', icon: <Link2 size={15} />, tab: 'connections' },
  ] },
  { label: 'System', items: [
    { label: 'Settings', icon: <SettingsIcon size={15} />, tab: 'settings' },
  ] },
]

export default function App() {
  const [authState, setAuthState] = useState<AuthState>('checking')
  const [theme, setThemeState]    = useState<Theme>(initTheme)

  const [activeTab, setActiveTabState] = useState<Tab>(() => {
    const saved = localStorage.getItem('classic4kast-tab')
    return saved === 'channels' || saved === 'webchannels' || saved === 'fleet' || saved === 'm3u' || saved === 'connections' || saved === 'settings' ? saved : 'channels'
  })
  function setActiveTab(t: Tab) {
    localStorage.setItem('classic4kast-tab', t)
    setActiveTabState(t)
  }

  function setTheme(t: Theme) {
    document.documentElement.setAttribute('data-theme', t)
    localStorage.setItem('classic4kast-theme', t)
    setThemeState(t)
  }

  // /api/settings/ reports has_credentials + credentials_choice_made. On a
  // genuinely first launch (neither set yet) the one-time FirstRunSetup
  // prompt decides whether to create a login or skip; once that choice is
  // made (either way), this never shows again -- see config.py's
  // credentials_choice_made()/mark_credentials_choice_made().
  const { data: settings, isLoading } = useQuery({
    queryKey: ['settings'],
    queryFn: () => api.get('/settings/').then((r) => r.data),
    staleTime: 30_000,
    retry: false,
  })

  useEffect(() => {
    if (isLoading) return
    if (!settings?.has_credentials) {
      setAuthState(settings?.credentials_choice_made ? 'ready' : 'first-run')
      return
    }
    const token = localStorage.getItem('classic4kast-session')
    if (!token) { setAuthState('login'); return }
    api.get('/auth/verify/')
      .then((r) => setAuthState(r.data.valid ? 'ready' : 'login'))
      .catch(() => setAuthState('login'))
  }, [isLoading, settings?.has_credentials, settings?.credentials_choice_made])

  // Dispatcharr integration is opt-out, not required -- some users run this
  // fully standalone (an HLS URL handed to a player directly) and don't
  // want the Dispatcharr nav item/deploy controls at all. If it gets turned
  // off while sitting on the Connections tab, bounce back to Channels
  // rather than leave the user on a nav item that no longer exists.
  const dispatcharrEnabled = settings?.dispatcharr_enabled ?? true
  useEffect(() => {
    if (!dispatcharrEnabled && activeTab === 'connections') setActiveTab('channels')
  }, [dispatcharrEnabled, activeTab])

  const navGroups = dispatcharrEnabled ? NAV_GROUPS : NAV_GROUPS.filter((g) => g.label !== 'Dispatcharr')

  function handleLogin() {
    setAuthState('ready')
  }

  function handleLogout() {
    api.post('/auth/logout/').finally(() => {
      localStorage.removeItem('classic4kast-session')
      setAuthState('login')
    })
  }

  if (isLoading || authState === 'checking') {
    return (
      <div className="flex items-center justify-center min-h-screen text-muted-foreground gap-2">
        <Loader2 size={16} className="animate-spin" />
        <span className="text-sm">Loading…</span>
      </div>
    )
  }

  if (authState === 'first-run') {
    return <FirstRunSetup onDone={() => setAuthState('ready')} />
  }

  if (authState === 'login') {
    return <Login onLogin={handleLogin} />
  }

  return (
    <div className="min-h-screen grid grid-cols-[240px_1fr]">
      <aside className="sticky top-0 h-screen flex flex-col border-r border-border bg-card px-2.5 py-4 overflow-y-auto">
        <div className="px-1.5 pb-4">
          <img src="/brand/compact-horizontal.png" alt="Classic4Kast Video+" className="w-full h-auto" />
          {/* Echoes the logo's own colored bar (destructive/brand3/brand2/
              primary) as a real, functioning UI element -- not just present
              in the logo image -- so the brand palette actually shows up in
              the chrome, not only in a picture. */}
          <div className="mt-2 h-[3px] rounded-full flex overflow-hidden">
            <div className="flex-1 bg-primary" />
            <div className="flex-1 bg-destructive" />
            <div className="flex-1 bg-brand3" />
            <div className="flex-1 bg-brand2" />
            <div className="flex-1 bg-primary" />
          </div>
        </div>
        <nav className="flex-1 space-y-3.5">
          {navGroups.map((group) => (
            <div key={group.label}>
              <div className="px-2 pb-1 text-[10px] font-bold uppercase tracking-wider text-muted-foreground/70">{group.label}</div>
              {group.items.map((item) => {
                const isActive = activeTab === item.tab
                return (
                  <button
                    key={item.label}
                    onClick={() => setActiveTab(item.tab)}
                    className={`w-full flex items-center gap-2.5 px-2 py-1.5 rounded-md text-[13px] font-medium transition-colors ${
                      isActive
                        ? 'bg-primary/10 text-foreground border border-primary/30'
                        : 'text-muted-foreground border border-transparent hover:text-foreground hover:bg-accent'
                    }`}
                  >
                    <span className={isActive ? 'text-primary [&_svg]:w-[15px] [&_svg]:h-[15px]' : 'opacity-80 [&_svg]:w-[15px] [&_svg]:h-[15px]'}>{item.icon}</span>
                    {item.label}
                  </button>
                )
              })}
            </div>
          ))}
        </nav>
      </aside>

      <div className="flex flex-col min-w-0">
        <header className="sticky top-0 z-10 flex items-center gap-3.5 px-5 py-2.5 border-b border-border bg-card">
          <div className="flex-1" />
          <div className="flex items-center gap-0.5 rounded border border-border p-0.5">
            {(THEMES as readonly Theme[]).map((t) => {
              const meta = THEME_META[t]
              return (
                <button
                  key={t}
                  title={meta.label}
                  onClick={() => setTheme(t)}
                  className={`flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] transition-colors ${
                    theme === t
                      ? 'bg-primary text-primary-foreground'
                      : 'text-muted-foreground hover:text-foreground hover:bg-accent'
                  }`}
                >
                  {meta.icon}
                  <span>{meta.label}</span>
                </button>
              )
            })}
          </div>
          <button
            className="text-muted-foreground hover:text-foreground transition-colors p-1.5 rounded hover:bg-accent"
            title="Settings"
            onClick={() => setActiveTab('settings')}
          >
            <SettingsIcon size={15} />
          </button>
          {settings?.has_credentials && (
            <button
              className="text-muted-foreground hover:text-foreground transition-colors p-1.5 rounded hover:bg-accent"
              title="Sign out"
              onClick={handleLogout}
            >
              <LogOut size={15} />
            </button>
          )}
        </header>
        <main className="flex-1 min-w-0 p-4">
          {activeTab === 'channels' && <Channels />}
          {activeTab === 'webchannels' && <WebChannels />}
          {activeTab === 'fleet' && <FleetStatus />}
          {activeTab === 'm3u' && <ExportM3U />}
          {activeTab === 'connections' && <Connections />}
          {activeTab === 'settings' && <Settings />}
        </main>
      </div>
    </div>
  )
}
