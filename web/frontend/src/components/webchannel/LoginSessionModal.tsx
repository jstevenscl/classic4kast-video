import { useEffect, useRef, useState } from 'react'
import { Loader2, LogIn, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import api from '@/lib/api'
import type { WebChannel } from '@/types'

// The remote viewport size login_session.js hardcodes (webchannel-renderer/
// src/login_session.js's page.setViewport) -- mouse coordinates captured
// against this modal's own (likely smaller/differently-proportioned)
// rendered <img> size have to be scaled back to this before being sent, or
// clicks land on the wrong element server-side.
const REMOTE_WIDTH = 1280
const REMOTE_HEIGHT = 720

type Status = 'connecting' | 'live' | 'error' | 'saving' | 'saved'

// Interactive login-session capture: streams a live CDP screencast of a
// real headless-Chromium page (see webchannel-renderer/src/login_session.js)
// into an <img>, forwards this admin's own mouse/keyboard into that same
// page over the same WebSocket, and once they've logged in for real
// (including clearing any MFA prompt themselves -- this is the whole
// reason session-capture was chosen over scripted credential/form-fill,
// see the plan's Context section) captures the resulting cookies +
// localStorage for the regular capture loop to reuse automatically.
export default function LoginSessionModal({ channel, onClose, onCaptured }: {
  channel: WebChannel; onClose: () => void; onCaptured: () => void
}) {
  const imgRef = useRef<HTMLImageElement>(null)
  const viewportRef = useRef<HTMLDivElement>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const lastMouseSentRef = useRef(0)
  const [status, setStatus] = useState<Status>('connecting')
  const [errorMsg, setErrorMsg] = useState('')
  const [frameSrc, setFrameSrc] = useState<string | null>(null)

  useEffect(() => {
    const token = localStorage.getItem('classic4kast-session') || ''
    const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${scheme}//${window.location.host}/api/webchannels/${channel.id}/login-session/ws?token=${encodeURIComponent(token)}`)
    wsRef.current = ws

    ws.onopen = () => { setStatus('live'); viewportRef.current?.focus() }
    ws.onerror = () => { setStatus('error'); setErrorMsg('Connection failed') }
    ws.onclose = () => setStatus((s) => (s === 'saved' ? s : 'error'))
    ws.onmessage = (evt) => {
      let msg: any
      try { msg = JSON.parse(evt.data) } catch { return }
      if (msg.type === 'frame') {
        setFrameSrc(`data:image/jpeg;base64,${msg.data}`)
      } else if (msg.type === 'captured') {
        setStatus('saving')
        api.post(`/webchannels/${channel.id}/session/`, {
          cookies: msg.cookies,
          local_storage: msg.localStorage || {},
        }).then(() => {
          setStatus('saved')
          onCaptured()
        }).catch((err) => {
          setStatus('error')
          setErrorMsg(err?.response?.data?.detail || 'Failed to save captured session')
        })
      } else if (msg.type === 'error') {
        setStatus('error')
        setErrorMsg(msg.message || 'Login session error')
      }
    }

    return () => { ws.close() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channel.id])

  const sendInput = (event: Record<string, unknown>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'input', ...event }))
    }
  }

  // Scales a click/move position from the <img>'s actual rendered size in
  // this modal to REMOTE_WIDTH x REMOTE_HEIGHT (the real page's viewport)
  // -- the two are very unlikely to match 1:1 once the image is laid out
  // in a fixed-size modal.
  const toRemoteCoords = (e: React.MouseEvent) => {
    const rect = imgRef.current!.getBoundingClientRect()
    const x = ((e.clientX - rect.left) / rect.width) * REMOTE_WIDTH
    const y = ((e.clientY - rect.top) / rect.height) * REMOTE_HEIGHT
    return { x: Math.round(x), y: Math.round(y) }
  }

  const onMouseMove = (e: React.MouseEvent) => {
    const now = Date.now()
    if (now - lastMouseSentRef.current < 33) return // ~30/s cap -- CDP mousemove doesn't need every pixel
    lastMouseSentRef.current = now
    sendInput({ inputType: 'mousemove', ...toRemoteCoords(e) })
  }
  const onMouseDown = (e: React.MouseEvent) => {
    // The <img> itself isn't focusable, so a click on it never moves DOM
    // focus to the wrapping tabIndex div that owns onKeyDown/onKeyUp --
    // found live: mouse-driving the remote page worked fine, but typing
    // never did anything because keydown events simply never fired.
    // Focusing the wrapper explicitly on every mousedown fixes that.
    viewportRef.current?.focus()
    sendInput({ inputType: 'mousedown', ...toRemoteCoords(e), button: 'left' })
  }
  const onMouseUp = (e: React.MouseEvent) => sendInput({ inputType: 'mouseup', ...toRemoteCoords(e), button: 'left' })
  const onWheel = (e: React.WheelEvent) => sendInput({ inputType: 'wheel', ...toRemoteCoords(e as unknown as React.MouseEvent), deltaX: e.deltaX, deltaY: e.deltaY })

  const onKeyDown = (e: React.KeyboardEvent) => {
    e.preventDefault()
    sendInput({ inputType: 'keydown', key: e.key, code: e.code, keyCode: e.keyCode, text: e.key.length === 1 ? e.key : '' })
  }
  const onKeyUp = (e: React.KeyboardEvent) => {
    e.preventDefault()
    sendInput({ inputType: 'keyup', key: e.key, code: e.code, keyCode: e.keyCode })
  }

  const capture = () => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'capture' }))
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-3xl rounded-lg border border-border bg-card shadow-xl p-4 space-y-3">
        <div className="flex items-center justify-between">
          <p className="text-sm font-medium">Log in to "{channel.channel_name}"</p>
          <button className="p-1 rounded hover:bg-accent text-muted-foreground" onClick={onClose}><X size={14} /></button>
        </div>
        <p className="text-[10px] text-muted-foreground">
          This is the real page, live -- click and type into it below exactly like a normal browser tab (including any
          login form or MFA prompt). Once you've reached the logged-in dashboard, click "Capture session".
        </p>

        <div
          ref={viewportRef}
          className="relative bg-black rounded overflow-hidden mx-auto focus:outline focus:outline-2 focus:outline-primary"
          style={{ width: '100%', aspectRatio: `${REMOTE_WIDTH} / ${REMOTE_HEIGHT}`, cursor: status === 'live' ? 'default' : 'wait' }}
          tabIndex={0}
          onKeyDown={onKeyDown}
          onKeyUp={onKeyUp}
        >
          {frameSrc ? (
            // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
            <img
              ref={imgRef}
              src={frameSrc}
              alt="Live remote page"
              className="w-full h-full select-none"
              draggable={false}
              onMouseMove={onMouseMove}
              onMouseDown={onMouseDown}
              onMouseUp={onMouseUp}
              onWheel={onWheel}
              onContextMenu={(e) => e.preventDefault()}
            />
          ) : (
            <div className="absolute inset-0 flex items-center justify-center text-muted-foreground text-xs gap-2">
              <Loader2 size={14} className="animate-spin" /> Connecting…
            </div>
          )}
        </div>

        {status === 'error' && (
          <p className="text-xs text-destructive">{errorMsg || 'Something went wrong'}</p>
        )}
        {status === 'saved' && (
          <p className="text-xs text-success">Session captured and saved -- future renders will reuse it.</p>
        )}

        <div className="flex gap-2">
          <Button
            size="sm" className="h-8 text-xs gap-1"
            disabled={status !== 'live'}
            onClick={capture}
          >
            {status === 'saving' ? <Loader2 size={12} className="animate-spin" /> : <LogIn size={12} />}
            Capture session
          </Button>
          <Button size="sm" variant="outline" className="h-8 text-xs" onClick={onClose}>
            {status === 'saved' ? 'Close' : 'Cancel'}
          </Button>
        </div>
      </div>
    </div>
  )
}
