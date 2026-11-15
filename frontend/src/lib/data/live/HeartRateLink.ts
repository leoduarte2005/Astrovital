import type { Envelope, TelemetryFramePayload } from '@/lib/model/live'

const RETRY_MIN_MS = 1000
const RETRY_MAX_MS = 15000

/**
 * One WebSocket for one crew member's heart rate. It reads only the `TELEMETRY_FRAME` whose `crew_id` is its own
 * and sends nothing: a `SET_CREW` from here would change the central's active crew for everyone.
 * Retries with the same backoff as the main link, while open.
 */
export class HeartRateLink {
  private socket: WebSocket | null = null
  private retryMs = RETRY_MIN_MS
  private retryTimer: number | undefined
  private active = false

  constructor(
    private readonly url: string,
    private readonly crewId: string,
    private readonly onBpm: (bpm: number) => void,
  ) {}

  open(): void {
    if (this.active) return
    this.active = true
    this.retryMs = RETRY_MIN_MS
    this.connect()
  }

  close(): void {
    if (!this.active) return
    this.active = false
    window.clearTimeout(this.retryTimer)
    const socket = this.socket
    this.socket = null
    if (!socket) return
    if (socket.readyState === WebSocket.CONNECTING) {
      // Closing while connecting is logged as an error by the browser: close as soon as it opens instead.
      socket.onopen = () => socket.close()
    } else {
      socket.close()
    }
  }

  private connect(): void {
    const socket = new WebSocket(this.url)
    this.socket = socket
    socket.onopen = () => {
      if (this.socket === socket) this.retryMs = RETRY_MIN_MS
    }
    socket.onmessage = (event: MessageEvent<unknown>) => {
      if (this.socket === socket) this.onMessage(event.data)
    }
    socket.onclose = () => {
      if (this.socket !== socket) return
      this.socket = null
      this.scheduleRetry()
    }
  }

  private scheduleRetry(): void {
    if (!this.active) return
    this.retryTimer = window.setTimeout(() => this.connect(), this.retryMs)
    this.retryMs = Math.min(this.retryMs * 2, RETRY_MAX_MS)
  }

  private onMessage(data: unknown): void {
    if (typeof data !== 'string') return
    let envelope: Envelope<TelemetryFramePayload>
    try {
      envelope = JSON.parse(data) as Envelope<TelemetryFramePayload>
    } catch {
      console.warn('live: heart-rate frame is not valid JSON, dropped')
      return
    }
    if (envelope.type !== 'TELEMETRY_FRAME' || envelope.crew_id !== this.crewId) return
    const bpm = envelope.payload?.vitals?.heart_rate_bpm
    if (typeof bpm === 'number') this.onBpm(bpm)
  }
}
