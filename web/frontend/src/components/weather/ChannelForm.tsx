import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import type { Country, RenderMode } from '@/types'
import {
  COUNTRY_OPTIONS, DEFAULT_SCREENS, NOT_IMPLEMENTED_SCREEN_KEYS, RENDER_MODE_OPTIONS,
  SCREEN_KEYS, SCREEN_LABEL, US_ONLY_SCREEN_KEYS,
  applyCountryScreenSupport, geocode,
} from './channelConstants'

export interface ChannelFormState {
  slug: string
  city_name: string
  location_query: string
  lat: string
  lon: string
  units: 'imperial' | 'metric'
  enabled: boolean
  render_mode: RenderMode
  country: Country
  ec_city_id: string
  screens: Record<string, boolean>
}

function ScreensGrid({ screens, onChange, country }: { screens: Record<string, boolean>; onChange: (screens: Record<string, boolean>) => void; country: Country }) {
  return (
    <div>
      <p className="text-xs font-medium mb-1">Screens</p>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-1 border border-border rounded p-2">
        {SCREEN_KEYS.map((key) => {
          const notBuilt = NOT_IMPLEMENTED_SCREEN_KEYS.has(key)
          const countryUnsupported = !notBuilt && country !== 'US' && US_ONLY_SCREEN_KEYS.has(key)
          const unsupported = notBuilt || countryUnsupported
          const reason = notBuilt
            ? 'Not built yet -- this screen has no renderer at all, enabling it does nothing'
            : countryUnsupported
              ? `No ${country === 'CA' ? 'Environment Canada' : 'Open-Meteo'} equivalent -- this screen would be empty`
              : undefined
          return (
            <label
              key={key}
              className={`flex items-center gap-1.5 text-xs ${unsupported ? 'text-muted-foreground/40 cursor-not-allowed' : 'cursor-pointer'}`}
              title={reason}
            >
              <input
                type="checkbox"
                disabled={unsupported}
                checked={!unsupported && !!screens[key]}
                onChange={(e) => onChange({ ...screens, [key]: e.target.checked })}
              />
              {SCREEN_LABEL[key]}
            </label>
          )
        })}
      </div>
    </div>
  )
}

// Ported from EDM's WeatherStar.tsx ChannelForm -- slug/city/units/country/
// render-mode/location-query+geocode/lat-lon/screens grid, unchanged in
// substance (no Dispatcharr concept lives in this component at all, so
// nothing here needed the instance -> connection rename).
export default function ChannelForm({ form, setForm, isEdit }: { form: ChannelFormState; setForm: (f: ChannelFormState) => void; isEdit: boolean }) {
  const [geocoding, setGeocoding] = useState(false)
  const [geocodeError, setGeocodeError] = useState('')

  const handleLookup = async () => {
    if (!form.location_query.trim()) return
    setGeocoding(true)
    setGeocodeError('')
    try {
      const result = await geocode(form.location_query)
      if (result) {
        setForm({ ...form, lat: String(result.lat), lon: String(result.lon) })
      } else {
        setGeocodeError('No results found for that location')
      }
    } catch {
      setGeocodeError('Lookup failed -- enter coordinates manually')
    } finally {
      setGeocoding(false)
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex flex-col gap-1">
          <span className="text-[10px] text-muted-foreground">Slug</span>
          <Input
            className="h-8 text-xs w-40"
            placeholder="e.g. austin-tx"
            value={form.slug}
            disabled={isEdit}
            onChange={(e) => setForm({ ...form, slug: e.target.value })}
          />
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-[10px] text-muted-foreground">City name</span>
          <Input
            className="h-8 text-xs w-48"
            placeholder="e.g. Austin, TX"
            value={form.city_name}
            onChange={(e) => setForm({ ...form, city_name: e.target.value })}
          />
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-[10px] text-muted-foreground">Units</span>
          <select
            className="h-8 text-xs bg-background border border-border rounded px-2"
            value={form.units}
            onChange={(e) => setForm({ ...form, units: e.target.value as 'imperial' | 'metric' })}
          >
            <option value="imperial">Imperial</option>
            <option value="metric">Metric</option>
          </select>
        </div>
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer mt-4">
          <input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} />
          Enabled
        </label>
      </div>

      <div className="flex flex-wrap items-end gap-2">
        <div className="flex flex-col gap-1">
          <span className="text-[10px] text-muted-foreground">Country / data source</span>
          <select
            className="h-8 text-xs bg-background border border-border rounded px-2"
            value={form.country}
            onChange={(e) => {
              const country = e.target.value as Country
              setForm({ ...form, country, screens: applyCountryScreenSupport(form.screens, country) })
            }}
          >
            {COUNTRY_OPTIONS.map((opt) => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
          </select>
        </div>
        {form.country === 'CA' && (
          <div className="flex flex-col gap-1">
            <span className="text-[10px] text-muted-foreground">Environment Canada city ID</span>
            <Input
              className="h-8 text-xs w-40"
              placeholder="e.g. on-143"
              value={form.ec_city_id}
              onChange={(e) => setForm({ ...form, ec_city_id: e.target.value })}
            />
          </div>
        )}
      </div>
      {form.country !== 'US' && (
        <p className="text-[10px] text-muted-foreground max-w-md">
          {form.country === 'CA'
            ? 'Environment Canada has no equivalent for Hazards, Regional Observations, Travel Forecast, Regional Map, or Radar -- those are greyed out below.'
            : 'Open-Meteo has no equivalent for Hazards, Regional Observations, Travel Forecast, Regional Map, or Radar -- those are greyed out below.'}
        </p>
      )}

      <div className="flex flex-col gap-1">
        <span className="text-[10px] text-muted-foreground">Render mode</span>
        <select
          className="h-8 text-xs bg-background border border-border rounded px-2 w-full max-w-xs"
          value={form.render_mode}
          onChange={(e) => setForm({ ...form, render_mode: e.target.value as RenderMode })}
        >
          {RENDER_MODE_OPTIONS.map((opt) => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
        </select>
        <p className="text-[10px] text-muted-foreground max-w-md">
          {RENDER_MODE_OPTIONS.find((opt) => opt.value === form.render_mode)?.description}
        </p>
      </div>

      <div className="flex flex-col gap-1">
        <span className="text-[10px] text-muted-foreground">Location query</span>
        <div className="flex items-center gap-2">
          <Input
            className="h-8 text-xs"
            placeholder="City, State or ZIP"
            value={form.location_query}
            onChange={(e) => setForm({ ...form, location_query: e.target.value })}
          />
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-8 text-xs shrink-0"
            disabled={!form.location_query.trim() || geocoding}
            onClick={handleLookup}
          >
            {geocoding ? <Loader2 size={12} className="animate-spin" /> : 'Look up lat/lon'}
          </Button>
        </div>
        {geocodeError && <p className="text-[10px] text-destructive">{geocodeError}</p>}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex flex-col gap-1">
          <span className="text-[10px] text-muted-foreground">Latitude</span>
          <input
            type="number"
            step="any"
            className="h-8 text-xs bg-background border border-border rounded px-2 w-32"
            value={form.lat}
            onChange={(e) => setForm({ ...form, lat: e.target.value })}
          />
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-[10px] text-muted-foreground">Longitude</span>
          <input
            type="number"
            step="any"
            className="h-8 text-xs bg-background border border-border rounded px-2 w-32"
            value={form.lon}
            onChange={(e) => setForm({ ...form, lon: e.target.value })}
          />
        </div>
      </div>

      <ScreensGrid screens={form.screens} onChange={(screens) => setForm({ ...form, screens })} country={form.country} />
    </div>
  )
}

export function emptyForm(): ChannelFormState {
  return {
    slug: '',
    city_name: '',
    location_query: '',
    lat: '',
    lon: '',
    units: 'imperial',
    enabled: true,
    render_mode: 'on_demand',
    country: 'US',
    ec_city_id: '',
    screens: { ...DEFAULT_SCREENS },
  }
}
