import { useEffect, useState } from 'react'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Loader2, RefreshCw, Rocket, Trash2, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import api from '@/lib/api'
import type {
  BulkDeployResult, ChannelGroup, DispatcharrChannelProfile,
  DispatcharrConnection, StreamProfile, WeatherStarChannel,
} from '@/types'
import { DEFAULT_STREAM_PROFILE_NAME } from './channelConstants'
import DeploymentProfilesEditor from './DeploymentProfilesEditor'

// Ported from EDM's WeatherStar.tsx DeployModal. Every "instance" concept
// is renamed "Dispatcharr connection" throughout, and the connection list
// now comes from this product's own /api/dispatcharr-connections/ endpoint
// instead of assuming EDM's single pre-existing instance list. Handles
// zero connections configured -- see the empty state in the render below.
export default function DeployModal({ channel, onClose }: { channel: WeatherStarChannel; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [mode, setMode] = useState<'single' | 'bulk'>('single')
  const [connectionId, setConnectionId] = useState<number | ''>('')
  const [groupId, setGroupId] = useState<number | ''>('')
  const [name, setName] = useState(`${channel.city_name}`)
  const [streamProfileId, setStreamProfileId] = useState<number | ''>('')
  const [profileTouched, setProfileTouched] = useState(false)
  const [logoUrl, setLogoUrl] = useState('')
  const [logoTouched, setLogoTouched] = useState(false)
  // 'all' omits channel_profile_ids entirely (Dispatcharr's own default --
  // every profile on the connection). 'specific' sends exactly the checked
  // ids, including [] if none are checked.
  const [profileMode, setProfileMode] = useState<'all' | 'specific'>('all')
  const [selectedProfileIds, setSelectedProfileIds] = useState<number[]>([])

  const { data: publicUrlData } = useQuery<{ url: string | null }>({
    queryKey: ['classic4kast-public-url'],
    queryFn: () => api.get('/config/public-url/').then((r) => r.data),
  })

  useEffect(() => {
    if (logoTouched || logoUrl || !publicUrlData?.url) return
    setLogoUrl(`${publicUrlData.url.replace(/\/+$/, '')}/weatherstar/logo.png?c=${channel.slug}`)
  }, [publicUrlData, logoTouched, logoUrl, channel.slug])

  const { data: connections } = useQuery<DispatcharrConnection[]>({
    queryKey: ['dispatcharr-connections'],
    queryFn: () => api.get('/dispatcharr-connections/').then((r) => r.data),
  })

  const { data: groups, isLoading: groupsLoading } = useQuery<ChannelGroup[]>({
    queryKey: ['dispatcharr-groups', connectionId],
    queryFn: () =>
      // Backend already applies the channel_count > 0 group filter
      // server-side (excludes stream-import-only groups) -- render as-is,
      // don't re-filter here.
      api.get(`/dispatcharr-connections/${connectionId}/groups/`).then((r) => r.data),
    enabled: connectionId !== '',
  })

  const { data: streamProfiles } = useQuery<StreamProfile[]>({
    queryKey: ['dispatcharr-stream-profiles', connectionId],
    queryFn: () => api.get(`/dispatcharr-connections/${connectionId}/stream-profiles/`).then((r) => r.data),
    enabled: connectionId !== '',
  })

  useEffect(() => {
    if (profileTouched || !streamProfiles?.length) return
    const preferred = streamProfiles.find((p) => p.name === DEFAULT_STREAM_PROFILE_NAME)
    if (preferred) setStreamProfileId(preferred.id)
  }, [streamProfiles, profileTouched])

  const { data: channelProfiles } = useQuery<DispatcharrChannelProfile[]>({
    queryKey: ['dispatcharr-channel-profiles', connectionId],
    queryFn: () => api.get(`/dispatcharr-connections/${connectionId}/channel-profiles/`).then((r) => r.data),
    enabled: connectionId !== '',
  })

  const toggleSelectedProfile = (id: number) => {
    setSelectedProfileIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['classic4kast-channels'] })

  const deployMutation = useMutation({
    mutationFn: () =>
      api.post(`/channels/${channel.id}/deploy/`, {
        connection_id: connectionId,
        channel_group_id: groupId,
        name: name.trim() || undefined,
        stream_profile_id: streamProfileId === '' ? null : streamProfileId,
        logo_url: logoUrl.trim() || undefined,
        channel_profile_ids: profileMode === 'specific' ? selectedProfileIds : undefined,
      }),
    onSuccess: () => {
      invalidate()
      setConnectionId('')
      setGroupId('')
      setStreamProfileId('')
      setProfileTouched(false)
      setLogoTouched(false)
      setName(channel.city_name)
      setProfileMode('all')
      setSelectedProfileIds([])
    },
  })

  const undeployMutation = useMutation({
    mutationFn: (targetConnectionId: number) => api.delete(`/channels/${channel.id}/deploy/${targetConnectionId}/`),
    onSuccess: invalidate,
  })

  const [refreshedConnectionId, setRefreshedConnectionId] = useState<number | null>(null)
  const [editingProfilesConnectionId, setEditingProfilesConnectionId] = useState<number | null>(null)
  const refreshMutation = useMutation({
    mutationFn: (targetConnectionId: number) => api.post(`/channels/${channel.id}/deploy/${targetConnectionId}/refresh/`),
    onSuccess: (_res, targetConnectionId) => {
      setRefreshedConnectionId(targetConnectionId)
      setTimeout(() => setRefreshedConnectionId(null), 2500)
    },
  })

  const availableConnections = (connections ?? []).filter(
    (c) => !channel.deployments.some((d) => d.connection_id === c.id),
  )

  // Bulk mode -- resolves group/profile by NAME independently per
  // connection (their numeric ids never match across separate Dispatcharr
  // instances).
  const [bulkConnectionIds, setBulkConnectionIds] = useState<number[]>([])
  const [bulkGroupName, setBulkGroupName] = useState('')
  const [bulkProfileName, setBulkProfileName] = useState('')
  const [bulkProfileTouched, setBulkProfileTouched] = useState(false)
  const [bulkResults, setBulkResults] = useState<BulkDeployResult[] | null>(null)
  const [bulkChannelProfileMode, setBulkChannelProfileMode] = useState<'all' | 'specific'>('all')
  const [bulkChannelProfileNames, setBulkChannelProfileNames] = useState<string[]>([])

  const toggleBulkChannelProfileName = (name: string) => {
    setBulkChannelProfileNames((prev) => (prev.includes(name) ? prev.filter((x) => x !== name) : [...prev, name]))
  }

  const toggleBulkConnection = (id: number) => {
    setBulkConnectionIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  const bulkGroupQueries = useQueries({
    queries: bulkConnectionIds.map((id) => ({
      queryKey: ['dispatcharr-groups', id],
      queryFn: () => api.get(`/dispatcharr-connections/${id}/groups/`).then((r) => (r.data as ChannelGroup[]).map((g) => g.name)),
    })),
  })
  const bulkProfileQueries = useQueries({
    queries: bulkConnectionIds.map((id) => ({
      queryKey: ['dispatcharr-stream-profiles', id],
      queryFn: () =>
        api.get(`/dispatcharr-connections/${id}/stream-profiles/`).then((r) =>
          (r.data as StreamProfile[]).filter((p) => p.is_active).map((p) => p.name),
        ),
    })),
  })
  const bulkChannelProfileQueries = useQueries({
    queries: bulkConnectionIds.map((id) => ({
      queryKey: ['dispatcharr-channel-profiles', id],
      queryFn: () => api.get(`/dispatcharr-connections/${id}/channel-profiles/`).then((r) => (r.data as DispatcharrChannelProfile[]).map((p) => p.name)),
    })),
  })

  const nameUnionAndCommon = (queries: { data?: string[] }[]) => {
    const lists = queries.map((q) => q.data).filter((d): d is string[] => !!d)
    const union = [...new Set(lists.flat())].sort((a, b) => a.localeCompare(b))
    const common = lists.length > 0 ? union.filter((n) => lists.every((l) => l.includes(n))) : []
    return { union, common }
  }
  const { union: bulkGroupNames, common: bulkCommonGroupNames } = nameUnionAndCommon(bulkGroupQueries)
  const { union: bulkProfileNames, common: bulkCommonProfileNames } = nameUnionAndCommon(bulkProfileQueries)
  const { common: bulkCommonChannelProfileNames } = nameUnionAndCommon(bulkChannelProfileQueries)

  useEffect(() => {
    if (bulkProfileTouched || bulkConnectionIds.length === 0) return
    if (bulkCommonProfileNames.includes(DEFAULT_STREAM_PROFILE_NAME)) {
      setBulkProfileName(DEFAULT_STREAM_PROFILE_NAME)
    }
  }, [bulkCommonProfileNames, bulkProfileTouched, bulkConnectionIds.length])

  const bulkDeployMutation = useMutation({
    mutationFn: () =>
      api.post(`/channels/${channel.id}/deploy-bulk/`, {
        connection_ids: bulkConnectionIds,
        channel_group_name: bulkGroupName.trim(),
        stream_profile_name: bulkProfileName.trim() || undefined,
        name: name.trim() || undefined,
        logo_url: logoUrl.trim() || undefined,
        channel_profile_names: bulkChannelProfileMode === 'specific' ? bulkChannelProfileNames : undefined,
      }),
    onSuccess: (res) => {
      invalidate()
      setBulkResults(res.data.results as BulkDeployResult[])
      const succeededIds = new Set(
        (res.data.results as BulkDeployResult[]).filter((r) => r.ok).map((r) => r.connection_id),
      )
      setBulkConnectionIds((prev) => prev.filter((id) => !succeededIds.has(id)))
    },
  })

  const noConnectionsAtAll = (connections ?? []).length === 0

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="w-full max-w-md rounded-lg border border-border bg-card shadow-xl p-4 space-y-3 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between">
          <p className="text-sm font-medium">Deploy "{channel.city_name}"</p>
          <button className="p-1 rounded hover:bg-accent text-muted-foreground" onClick={onClose}><X size={14} /></button>
        </div>

        {channel.deployments.length > 0 && (
          <div className="space-y-1">
            <p className="text-[10px] text-muted-foreground uppercase tracking-wide">Deployed to</p>
            {channel.deployments.map((d) => (
              <div key={d.connection_id} className="space-y-1">
                <div className="flex items-center justify-between text-xs rounded border border-border px-2 py-1.5">
                  <span>
                    <span className="font-medium">{d.connection_label}</span>
                    <span className="text-muted-foreground"> — "{d.name}" — {d.channel_group_name} #{d.channel_number}</span>
                  </span>
                  <span className="flex items-center gap-0.5">
                    {refreshedConnectionId === d.connection_id ? (
                      <CheckCircle2 size={12} className="text-success mx-1" />
                    ) : (
                      <button
                        className="p-1 rounded hover:bg-accent text-muted-foreground"
                        title="Update this deployment's stream URL to match the current public URL/key settings"
                        disabled={refreshMutation.isPending}
                        onClick={() => refreshMutation.mutate(d.connection_id)}
                      >
                        <RefreshCw size={12} />
                      </button>
                    )}
                    <button
                      className="p-1 rounded hover:bg-accent text-muted-foreground text-[10px] font-medium"
                      title="Edit which channel profiles this is enabled on"
                      onClick={() => setEditingProfilesConnectionId((prev) => (prev === d.connection_id ? null : d.connection_id))}
                    >
                      profiles
                    </button>
                    <button
                      className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-destructive"
                      title="Remove from this connection"
                      disabled={undeployMutation.isPending}
                      onClick={() => undeployMutation.mutate(d.connection_id)}
                    >
                      <Trash2 size={12} />
                    </button>
                  </span>
                </div>
                {editingProfilesConnectionId === d.connection_id && (
                  <DeploymentProfilesEditor
                    channelId={channel.id}
                    connectionId={d.connection_id}
                    onClose={() => setEditingProfilesConnectionId(null)}
                  />
                )}
              </div>
            ))}
            {refreshMutation.isError && (
              <p className="text-[10px] text-destructive">
                {(refreshMutation.error as any)?.response?.data?.detail ?? 'Refresh failed'}
              </p>
            )}
          </div>
        )}

        {noConnectionsAtAll ? (
          <p className="text-xs text-muted-foreground pt-2 border-t border-border">
            No Dispatcharr connections configured -- add one under Dispatcharr &rarr; Connections to enable deploy.
          </p>
        ) : (
          <div className="space-y-2 pt-1 border-t border-border">
            <div className="flex items-center justify-between pt-2">
              <p className="text-[10px] text-muted-foreground uppercase tracking-wide">Add to connection</p>
              <div className="flex rounded border border-border overflow-hidden text-[10px]">
                <button
                  className={`px-2 py-1 ${mode === 'single' ? 'bg-accent font-medium' : 'text-muted-foreground'}`}
                  onClick={() => setMode('single')}
                >
                  Single
                </button>
                <button
                  className={`px-2 py-1 border-l border-border ${mode === 'bulk' ? 'bg-accent font-medium' : 'text-muted-foreground'}`}
                  onClick={() => setMode('bulk')}
                >
                  Multiple
                </button>
              </div>
            </div>

            {mode === 'single' ? (
              <>
                <div className="flex flex-col gap-1">
                  <span className="text-[10px] text-muted-foreground">Connection</span>
                  <select
                    className="h-8 text-xs bg-background border border-border rounded px-2"
                    value={connectionId}
                    onChange={(e) => {
                      setConnectionId(e.target.value ? Number(e.target.value) : '')
                      setGroupId('')
                      setStreamProfileId('')
                      setProfileTouched(false)
                      setProfileMode('all')
                      setSelectedProfileIds([])
                    }}
                  >
                    <option value="">Select connection…</option>
                    {availableConnections.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
                  </select>
                </div>
                <div className="flex flex-col gap-1">
                  <span className="text-[10px] text-muted-foreground">Channel group</span>
                  <select
                    className="h-8 text-xs bg-background border border-border rounded px-2"
                    value={groupId}
                    disabled={connectionId === '' || groupsLoading}
                    onChange={(e) => setGroupId(e.target.value ? Number(e.target.value) : '')}
                  >
                    <option value="">{groupsLoading ? 'Loading…' : 'Select group…'}</option>
                    {(groups ?? []).map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
                  </select>
                </div>
                <div className="flex flex-col gap-1">
                  <span className="text-[10px] text-muted-foreground">Channel name</span>
                  <Input className="h-8 text-xs" value={name} onChange={(e) => setName(e.target.value)} />
                </div>
                <div className="flex flex-col gap-1">
                  <span className="text-[10px] text-muted-foreground">Stream profile</span>
                  <select
                    className="h-8 text-xs bg-background border border-border rounded px-2"
                    value={streamProfileId}
                    disabled={connectionId === ''}
                    onChange={(e) => { setStreamProfileId(e.target.value ? Number(e.target.value) : ''); setProfileTouched(true) }}
                  >
                    <option value="">Connection default</option>
                    {(streamProfiles ?? []).filter((p) => p.is_active).map((p) => (
                      <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                  </select>
                  <span className="text-[10px] text-muted-foreground">
                    "Redirect" (recommended) sends the player straight to our own stream -- no drift, no extra transcode.
                    Needs a real public URL (Settings page), not a private-only address. "Proxy" adds Dispatcharr's own
                    buffering, which caused real multi-hour drift in testing -- better suited to flaky third-party sources.
                  </span>
                </div>
                <div className="flex flex-col gap-1">
                  <span className="text-[10px] text-muted-foreground">Logo URL</span>
                  <Input
                    className="h-8 text-xs" placeholder="http://.../weatherstar/logo.png"
                    value={logoUrl} onChange={(e) => { setLogoUrl(e.target.value); setLogoTouched(true) }}
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <span className="text-[10px] text-muted-foreground">Channel profiles</span>
                  <div className="flex rounded border border-border overflow-hidden text-[10px] w-fit">
                    <button
                      type="button"
                      className={`px-2 py-1 ${profileMode === 'all' ? 'bg-accent font-medium' : 'text-muted-foreground'}`}
                      disabled={connectionId === ''}
                      onClick={() => setProfileMode('all')}
                    >
                      All profiles (default)
                    </button>
                    <button
                      type="button"
                      className={`px-2 py-1 border-l border-border ${profileMode === 'specific' ? 'bg-accent font-medium' : 'text-muted-foreground'}`}
                      disabled={connectionId === ''}
                      onClick={() => setProfileMode('specific')}
                    >
                      Specific profiles
                    </button>
                  </div>
                  {profileMode === 'specific' && (
                    <div className="space-y-1 max-h-28 overflow-y-auto rounded border border-border p-1.5 mt-1">
                      {!channelProfiles?.length && (
                        <p className="text-[10px] text-muted-foreground px-1 py-0.5">
                          {connectionId === '' ? 'Select a connection first…' : 'Loading…'}
                        </p>
                      )}
                      {(channelProfiles ?? []).map((p) => (
                        <label key={p.id} className="flex items-center gap-1.5 text-xs px-1 py-0.5 rounded hover:bg-accent cursor-pointer">
                          <input
                            type="checkbox"
                            checked={selectedProfileIds.includes(p.id)}
                            onChange={() => toggleSelectedProfile(p.id)}
                          />
                          {p.name}
                        </label>
                      ))}
                      {channelProfiles?.length && selectedProfileIds.length === 0 && (
                        <p className="text-[10px] text-amber-600 px-1 py-0.5">
                          None checked -- channel will be created invisible on every profile until assigned.
                        </p>
                      )}
                    </div>
                  )}
                </div>
                <p className="text-[10px] text-muted-foreground">
                  Creates a channel in this group using the next available channel number.
                </p>
                <Button
                  size="sm"
                  className="h-8 text-xs gap-1"
                  disabled={connectionId === '' || groupId === '' || deployMutation.isPending}
                  onClick={() => deployMutation.mutate()}
                >
                  {deployMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <Rocket size={12} />}
                  Deploy
                </Button>
                {deployMutation.isError && (
                  <p className="text-[10px] text-destructive">
                    {(deployMutation.error as any)?.response?.data?.detail ?? 'Deploy failed'}
                  </p>
                )}
              </>
            ) : (
              <>
                <div className="flex flex-col gap-1">
                  <span className="text-[10px] text-muted-foreground">Connections</span>
                  <div className="space-y-1 max-h-28 overflow-y-auto rounded border border-border p-1.5">
                    {availableConnections.length === 0 && (
                      <p className="text-[10px] text-muted-foreground px-1 py-0.5">Already deployed to every connection.</p>
                    )}
                    {availableConnections.map((c) => (
                      <label key={c.id} className="flex items-center gap-1.5 text-xs px-1 py-0.5 rounded hover:bg-accent cursor-pointer">
                        <input
                          type="checkbox"
                          checked={bulkConnectionIds.includes(c.id)}
                          onChange={() => toggleBulkConnection(c.id)}
                        />
                        {c.label}
                      </label>
                    ))}
                  </div>
                </div>
                <div className="flex flex-col gap-1">
                  <span className="text-[10px] text-muted-foreground">Channel group name</span>
                  <Input
                    className="h-8 text-xs" placeholder="e.g. Weather" list="bulk-group-names"
                    value={bulkGroupName} onChange={(e) => setBulkGroupName(e.target.value)}
                  />
                  <datalist id="bulk-group-names">
                    {bulkGroupNames.map((n) => <option key={n} value={n} />)}
                  </datalist>
                  <span className="text-[10px] text-muted-foreground">
                    Matched by name (case-insensitive) on each selected connection -- must already exist there.
                    {bulkConnectionIds.length > 0 && (
                      bulkCommonGroupNames.length > 0
                        ? ` On all ${bulkConnectionIds.length} selected: ${bulkCommonGroupNames.join(', ')}.`
                        : bulkGroupQueries.every((q) => q.isSuccess)
                          ? ' No group name is shared by every selected connection -- check spelling per connection.'
                          : ' Loading group names…'
                    )}
                  </span>
                </div>
                <div className="flex flex-col gap-1">
                  <span className="text-[10px] text-muted-foreground">Channel name</span>
                  <Input className="h-8 text-xs" value={name} onChange={(e) => setName(e.target.value)} />
                </div>
                <div className="flex flex-col gap-1">
                  <span className="text-[10px] text-muted-foreground">Stream profile name</span>
                  <Input
                    className="h-8 text-xs"
                    placeholder={bulkConnectionIds.length === 0 ? 'Select connection(s) first…' : `e.g. ${DEFAULT_STREAM_PROFILE_NAME}`}
                    disabled={bulkConnectionIds.length === 0}
                    list="bulk-profile-names"
                    value={bulkProfileName}
                    onChange={(e) => { setBulkProfileName(e.target.value); setBulkProfileTouched(true) }}
                  />
                  <datalist id="bulk-profile-names">
                    {bulkProfileNames.map((n) => <option key={n} value={n} />)}
                  </datalist>
                  <span className="text-[10px] text-muted-foreground">
                    Matched by name on each connection; leave blank to use each connection's own default. "Redirect"
                    (recommended, pre-filled) sends the player straight to our own stream -- needs a real public URL.
                    {bulkConnectionIds.length > 0 && bulkCommonProfileNames.length > 0 && (
                      ` On all ${bulkConnectionIds.length} selected: ${bulkCommonProfileNames.join(', ')}.`
                    )}
                  </span>
                </div>
                <div className="flex flex-col gap-1">
                  <span className="text-[10px] text-muted-foreground">Logo URL</span>
                  <Input
                    className="h-8 text-xs" placeholder="http://.../weatherstar/logo.png"
                    value={logoUrl} onChange={(e) => { setLogoUrl(e.target.value); setLogoTouched(true) }}
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <span className="text-[10px] text-muted-foreground">Channel profiles</span>
                  <div className="flex rounded border border-border overflow-hidden text-[10px] w-fit">
                    <button
                      type="button"
                      className={`px-2 py-1 ${bulkChannelProfileMode === 'all' ? 'bg-accent font-medium' : 'text-muted-foreground'}`}
                      disabled={bulkConnectionIds.length === 0}
                      onClick={() => setBulkChannelProfileMode('all')}
                    >
                      All profiles (default)
                    </button>
                    <button
                      type="button"
                      className={`px-2 py-1 border-l border-border ${bulkChannelProfileMode === 'specific' ? 'bg-accent font-medium' : 'text-muted-foreground'}`}
                      disabled={bulkConnectionIds.length === 0}
                      onClick={() => setBulkChannelProfileMode('specific')}
                    >
                      Specific profiles
                    </button>
                  </div>
                  {bulkChannelProfileMode === 'specific' && (
                    <div className="space-y-1 max-h-28 overflow-y-auto rounded border border-border p-1.5 mt-1">
                      {bulkConnectionIds.length === 0 ? (
                        <p className="text-[10px] text-muted-foreground px-1 py-0.5">Select connection(s) first…</p>
                      ) : bulkCommonChannelProfileNames.length === 0 ? (
                        <p className="text-[10px] text-muted-foreground px-1 py-0.5">
                          {bulkChannelProfileQueries.every((q) => q.isSuccess) ? 'No profile name is shared by every selected connection.' : 'Loading…'}
                        </p>
                      ) : (
                        bulkCommonChannelProfileNames.map((n) => (
                          <label key={n} className="flex items-center gap-1.5 text-xs px-1 py-0.5 rounded hover:bg-accent cursor-pointer">
                            <input type="checkbox" checked={bulkChannelProfileNames.includes(n)} onChange={() => toggleBulkChannelProfileName(n)} />
                            {n}
                          </label>
                        ))
                      )}
                      <p className="text-[10px] text-muted-foreground px-1 pt-0.5">
                        Only profile names shared by every selected connection are shown.
                      </p>
                    </div>
                  )}
                </div>
                <Button
                  size="sm"
                  className="h-8 text-xs gap-1"
                  disabled={bulkConnectionIds.length === 0 || !bulkGroupName.trim() || bulkDeployMutation.isPending}
                  onClick={() => bulkDeployMutation.mutate()}
                >
                  {bulkDeployMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <Rocket size={12} />}
                  Deploy to {bulkConnectionIds.length || ''} connection{bulkConnectionIds.length === 1 ? '' : 's'}
                </Button>
                {bulkResults && (
                  <div className="space-y-1 pt-1">
                    {bulkResults.map((r) => (
                      <p key={r.connection_id} className={`text-[10px] ${r.ok ? 'text-green-600' : 'text-destructive'}`}>
                        {r.connection_label ?? `connection ${r.connection_id}`}: {r.ok ? 'deployed' : r.error}
                      </p>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
