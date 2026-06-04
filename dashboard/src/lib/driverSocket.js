const _base = process.env.NEXT_PUBLIC_ROUTING_API || 'http://localhost:8004'
const WS_BASE = _base.replace(/^http/, 'ws')

const RECONNECT_DELAY_MIN_MS = 1_000
const RECONNECT_DELAY_MAX_MS = 30_000

class DriverSocket {
  constructor() {
    this._ws = null
    this._truckId = null
    this._handlers = {}
    this._reconnectDelay = RECONNECT_DELAY_MIN_MS
    this._reconnectTimer = null
    this._active = false
  }

  connect(truckId) {
    this._truckId = truckId
    this._active = true
    this._reconnectDelay = RECONNECT_DELAY_MIN_MS
    this._open()
  }

  disconnect() {
    this._active = false
    clearTimeout(this._reconnectTimer)
    if (this._ws) {
      this._ws.close(1000, 'shift ended')
      this._ws = null
    }
  }

  on(event, handler) {
    this._handlers[event] = handler
    return () => {
      if (this._handlers[event] === handler) delete this._handlers[event]
    }
  }

  _open() {
    const url = `${WS_BASE}/ws/driver/${this._truckId}`
    try {
      this._ws = new WebSocket(url)
    } catch {
      this._scheduleReconnect()
      return
    }

    this._ws.onopen = () => {
      this._reconnectDelay = RECONNECT_DELAY_MIN_MS
      this._emit('connected', {})
    }

    this._ws.onmessage = ({ data }) => {
      try {
        const msg = JSON.parse(data)
        const type = msg.type ?? msg.event_type
        const payload = msg.payload ?? msg
        this._emit(type, payload)
      } catch {}
    }

    this._ws.onerror = () => this._emit('error', {})

    this._ws.onclose = ({ code }) => {
      this._ws = null
      this._emit('disconnected', { code })
      if (this._active) this._scheduleReconnect()
    }
  }

  _scheduleReconnect() {
    this._reconnectTimer = setTimeout(() => {
      this._reconnectDelay = Math.min(
        this._reconnectDelay * 2,
        RECONNECT_DELAY_MAX_MS,
      )
      this._open()
    }, this._reconnectDelay)
  }

  _emit(event, payload) {
    this._handlers[event]?.(payload)
  }
}

export const driverSocket = new DriverSocket()
