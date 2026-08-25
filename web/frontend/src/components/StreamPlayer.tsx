import { useEffect, useRef, useState } from 'react'
import { Loader2, X, XCircle } from 'lucide-react'

// Ported near-verbatim from EDM's frontend/src/components/StreamPlayer.tsx.
interface Props {
  url: string
  name: string
  onClose: () => void
}

export default function StreamPlayer({ url, name, onClose }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const hlsRef = useRef<any>(null)
  const [playerStatus, setPlayerStatus] = useState<'loading' | 'playing' | 'error'>('loading')
  const [errorMsg, setErrorMsg] = useState('')
  const [detectedRes, setDetectedRes] = useState('')

  useEffect(() => {
    const video = videoRef.current
    if (!video || !url) return

    const isHLS = url.toLowerCase().includes('m3u8') || url.toLowerCase().includes('hls')

    const tryNative = () => {
      video.src = url
      video.play().then(() => setPlayerStatus('playing')).catch((e) => {
        setPlayerStatus('error')
        setErrorMsg(e.message || 'Playback failed')
      })
    }

    let cancelled = false
    // A channel's backend stream genuinely restarts mid-playback -- the
    // renderer swaps from its "LOADING" placeholder ffmpeg process to a
    // fresh one once real data/live content is ready (see
    // renderer/on_demand_server.py's "live stream started" log): a brand
    // new ffmpeg process, new HLS segment numbering, no discontinuity tag
    // linking the two. Found live via direct browser testing (console +
    // network tab open through the actual transition): HLS.js does NOT
    // raise a fatal error here -- the <video> element just silently ends
    // up paused at 0:00 with a bogus multi-minute duration and never
    // recovers on its own, which is why closing/reopening the player (a
    // full recreate) was the only thing that fixed it. Two layers below:
    // real fatal HLS.js errors still get HLS.js's own documented recovery
    // (retry network errors, recoverMediaError for media errors, full
    // reattach otherwise); a stall watchdog separately catches this
    // silent-freeze case that raises no error at all, by noticing
    // currentTime stopped advancing and forcing the same full reattach.
    // Both share one restart budget so a genuinely dead stream still
    // surfaces as a real error instead of retrying forever.
    let hls: any = null
    let restartAttempts = 0
    let watchdogInterval: ReturnType<typeof setInterval> | null = null
    let lastCurrentTime = -1
    let stallTicks = 0
    const MAX_RESTARTS = 5
    const STALL_TICKS_BEFORE_RESTART = 3  // ~3 * 4s = 12s of no progress

    const clearWatchdog = () => {
      if (watchdogInterval) {
        clearInterval(watchdogInterval)
        watchdogInterval = null
      }
    }

    const reattach = () => {
      if (restartAttempts >= MAX_RESTARTS) {
        setPlayerStatus('error')
        setErrorMsg('Stream stalled repeatedly')
        return
      }
      restartAttempts += 1
      // Deliberately visible in devtools (not debug-gated) -- lets a user
      // distinguish "the player silently reattached" (would show here, and
      // sound like a brief blip) from unrelated backend audio glitches
      // (see beads C4K-0g0) when reporting playback issues.
      console.warn(`[StreamPlayer] reattaching (attempt ${restartAttempts}/${MAX_RESTARTS})`, url)
      clearWatchdog()
      if (hlsRef.current) {
        hlsRef.current.destroy()
        hlsRef.current = null
      }
      setTimeout(() => { if (!cancelled) attach() }, Math.min(1000 * restartAttempts, 5000))
    }

    const startWatchdog = () => {
      clearWatchdog()
      lastCurrentTime = -1
      stallTicks = 0
      watchdogInterval = setInterval(() => {
        if (cancelled || !hlsRef.current) return
        // readyState >= HAVE_FUTURE_DATA (3) with currentTime frozen and
        // the element paused usually means a deliberate user pause (real
        // buffered data sitting ready) -- don't fight that. Below 3 with
        // no progress is the genuine silent-stall case this watchdog
        // exists for.
        if (video.paused && video.readyState >= 3) { stallTicks = 0; lastCurrentTime = video.currentTime; return }
        if (video.currentTime === lastCurrentTime) {
          stallTicks += 1
          if (stallTicks >= STALL_TICKS_BEFORE_RESTART) {
            stallTicks = 0
            reattach()
          }
        } else {
          stallTicks = 0
        }
        lastCurrentTime = video.currentTime
      }, 4000)
    }

    const attach = () => {
      import('hls.js').then(({ default: Hls }) => {
        if (cancelled) return
        if (Hls.isSupported()) {
          hls = new Hls({ enableWorker: false, lowLatencyMode: true })
          hlsRef.current = hls
          hls.loadSource(url)
          hls.attachMedia(video)
          hls.on(Hls.Events.MANIFEST_PARSED, () => {
            restartAttempts = 0
            video.play().then(() => { setPlayerStatus('playing'); startWatchdog() }).catch(() => {})
          })
          hls.on(Hls.Events.ERROR, (_: any, data: any) => {
            if (!data.fatal) return
            if (data.type === Hls.ErrorTypes.NETWORK_ERROR) {
              hls.startLoad()
              return
            }
            if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
              hls.recoverMediaError()
              return
            }
            reattach()
          })
          hls.on(Hls.Events.LEVEL_LOADED, () => {
            const level = hls.levels[hls.currentLevel]
            if (level?.width && level?.height) {
              setDetectedRes(`${level.width}×${level.height}`)
            }
          })
        } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
          tryNative()
        } else {
          setPlayerStatus('error')
          setErrorMsg('HLS not supported in this browser')
        }
      })
    }

    if (isHLS) {
      attach()
    } else {
      tryNative()
    }

    return () => {
      cancelled = true
      clearWatchdog()
      if (hlsRef.current) {
        hlsRef.current.destroy()
        hlsRef.current = null
      }
      video.src = ''
    }
  }, [url])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70">
      <div className="bg-card border border-border rounded-lg w-full max-w-3xl mx-4 overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-border">
          <div>
            <p className="text-sm font-medium truncate max-w-md">{name}</p>
            {detectedRes && (
              <p className="text-xs text-muted-foreground">{detectedRes}</p>
            )}
          </div>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X size={16} />
          </button>
        </div>

        <div className="relative bg-black aspect-video flex items-center justify-center">
          {playerStatus === 'loading' && (
            <div className="absolute inset-0 flex items-center justify-center">
              <Loader2 size={32} className="animate-spin text-muted-foreground" />
            </div>
          )}
          {playerStatus === 'error' && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-destructive">
              <XCircle size={32} />
              <p className="text-sm">{errorMsg || 'Stream could not be loaded'}</p>
              <p className="text-xs text-muted-foreground max-w-sm text-center break-all">{url}</p>
            </div>
          )}
          <video
            ref={videoRef}
            className="w-full h-full"
            controls
            playsInline
            onPlay={() => setPlayerStatus('playing')}
            onError={() => { setPlayerStatus('error'); setErrorMsg('Video error') }}
          />
        </div>

        <div className="px-4 py-2 text-xs text-muted-foreground truncate border-t border-border">
          {url}
        </div>
      </div>
    </div>
  )
}
