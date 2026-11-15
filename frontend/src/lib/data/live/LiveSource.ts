import type { CrewMember } from '@/lib/model/crew'
import type {
  ChatMsgPayload,
  ChatReplyPayload,
  CrewStatePayload,
  CrewSummary,
  Envelope,
  ErrorPayload,
  SetCrewPayload,
} from '@/lib/model/live'
import { connectionStore } from '../connection'
import { crewStateStore } from '../crewState'
import type { DataSource } from '../source'
import type { BaselineMetricId, BaselineProfile, HistorySeries, HistoryWindow } from '@/lib/model/baseline'
import { baselineProfile, historySeries } from '../mock/baseline'
import { suggestBooks, type Book } from '../mock/bookCatalog'
import { toCrewMember } from './crewMapping'

type Listener = (envelope: Envelope) => void

interface Outgoing {
  type: string
  text: string
}

interface PendingChat {
  resolve: (reply: ChatReplyPayload) => void
  reject: (error: Error) => void
  timer: number
}

const RETRY_MIN_MS = 1000
const RETRY_MAX_MS = 15000
/** Commands kept while the link is down. The oldest is dropped beyond this. */
const OUTBOX_MAX = 50
/** How long a chat message waits for its reply before it fails on the client. */
const CHAT_TIMEOUT_MS = 30000
/** Chat text limit in UTF-8 bytes (guide §5). */
const CHAT_MAX_BYTES = 2000

/**
 * WebSocket link to the central: one connection (`/ws`) for every stream. Consumers take a reference with
 * `open()` (the home, the chat) and release it with `close()`; the link closes with the last one. Every
 * parseable envelope goes to the subscribers of its `type`, unchanged. Commands sent while the link is down
 * wait in a local queue and go out on reconnect.
 */
export class LiveSource implements DataSource {
  readonly kind = 'live' as const
  private socket: WebSocket | null = null
  private readonly listeners = new Map<string, Set<Listener>>()
  private outbox: Outgoing[] = []
  private retryMs = RETRY_MIN_MS
  private retryTimer: number | undefined
  private active = false
  private consumers = 0
  /** Chat messages waiting for a reply, by `client_msg_id`. */
  private readonly pendingChat = new Map<string, PendingChat>()
  /** Same messages in the order they were sent: a `CHAT_REPLY` (no id) pairs with the oldest one. */
  private chatOrder: string[] = []
  private chatSeq = 0
  private stopTimer: number | undefined

  constructor(private readonly url: string) {}

  /** `GET /api/crew` (same origin). Rejects when the central is unreachable or answers with an error. */
  async listCrew(): Promise<CrewMember[]> {
    const response = await fetch(new URL('api/crew', window.location.href).href, {
      headers: { Accept: 'application/json' },
      cache: 'no-store',
    })
    if (!response.ok) throw new Error(`GET /api/crew failed: HTTP ${response.status}`)
    const summaries = (await response.json()) as CrewSummary[]
    return summaries.map(toCrewMember)
  }

  /** The central has no book suggestions yet: the mock catalogue answers until it does. */
  listBookSuggestions(crewId: string): Promise<Book[]> {
    return Promise.resolve(suggestBooks(crewId))
  }

  /** The central does not provide the baseline yet (`/api/crew/{id}/profile`, Leva 2): the mock answers until it does. */
  getBaseline(crewId: string): Promise<BaselineProfile> {
    return Promise.resolve(baselineProfile(crewId, 42, Date.now()))
  }

  /** Same for the time series (`/api/crew/{id}/timeseries`, Leva 2). */
  history(crewId: string, metric: BaselineMetricId, window: HistoryWindow): Promise<HistorySeries> {
    return Promise.resolve(historySeries(crewId, metric, window, 42, Date.now()))
  }

  subscribe(type: string, listener: Listener): () => void {
    const set = this.listeners.get(type) ?? new Set<Listener>()
    set.add(listener)
    this.listeners.set(type, set)
    return () => {
      set.delete(listener)
    }
  }

  /** Takes a reference. The first one opens the link; a stop still pending from a close is cancelled. */
  open(): void {
    this.consumers++
    window.clearTimeout(this.stopTimer)
    this.stopTimer = undefined
    if (this.active) return
    this.active = true
    this.retryMs = RETRY_MIN_MS
    this.connect()
  }

  /**
   * Releases a reference. The last one stops the link on the next tick: React StrictMode closes and reopens
   * at once, and closing a socket that is still connecting makes the browser log a failure.
   */
  close(): void {
    if (this.consumers === 0) return
    this.consumers--
    if (this.consumers > 0) return
    this.stopTimer = window.setTimeout(() => {
      this.stopTimer = undefined
      if (this.consumers === 0) this.stop()
    }, 0)
  }

  setCrew(crewId: string): void {
    // Only the latest switch matters: a queued SET_CREW for another crew is replaced.
    this.outbox = this.outbox.filter((message) => message.type !== 'SET_CREW')
    const payload: SetCrewPayload = { crew_id: crewId }
    this.send('SET_CREW', payload, crewId)
  }

  sendChat(text: string, crewId: string): Promise<ChatReplyPayload> {
    const bytes = new TextEncoder().encode(text).length
    if (bytes === 0 || bytes > CHAT_MAX_BYTES) {
      return Promise.reject(new Error(`chat text must be 1 to ${CHAT_MAX_BYTES} bytes`))
    }
    const clientMsgId = `chat-${++this.chatSeq}`
    return new Promise<ChatReplyPayload>((resolve, reject) => {
      const timer = window.setTimeout(() => {
        this.settleChat(clientMsgId, (pending) => pending.reject(new Error('chat timeout')))
      }, CHAT_TIMEOUT_MS)
      this.pendingChat.set(clientMsgId, { resolve, reject, timer })
      this.chatOrder.push(clientMsgId)
      const payload: ChatMsgPayload = { text }
      this.send('CHAT_MSG', payload, crewId, clientMsgId)
    })
  }

  /** Stops the link, drops queued commands and rejects chat messages still waiting for a reply. */
  private stop(): void {
    this.active = false
    window.clearTimeout(this.retryTimer)
    this.outbox = []
    for (const id of [...this.chatOrder]) {
      this.settleChat(id, (pending) => pending.reject(new Error('link closed')))
    }
    const socket = this.socket
    this.socket = null
    if (socket && socket.readyState === WebSocket.CONNECTING) {
      // Closing while connecting is logged as an error by the browser: close as soon as it opens instead.
      socket.onopen = () => socket.close()
    } else {
      socket?.close()
    }
    connectionStore.setState({ state: 'offline' })
  }

  private send(type: string, payload: unknown, crewId: string | null, clientMsgId?: string): void {
    // Same field order as the guide: v, type, ts_us, crew_id, client_msg_id, payload.
    const envelope: Record<string, unknown> = { v: 1, type, ts_us: Date.now() * 1000, crew_id: crewId }
    if (clientMsgId !== undefined) envelope.client_msg_id = clientMsgId
    envelope.payload = payload
    const text = JSON.stringify(envelope)
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(text)
      return
    }
    if (this.outbox.length >= OUTBOX_MAX) {
      this.outbox.shift()
      console.warn('live: command queue full, oldest dropped')
    }
    this.outbox.push({ type, text })
  }

  /** Removes a pending chat message and runs `action` on it, if it is still waiting. */
  private settleChat(id: string, action: (pending: PendingChat) => void): void {
    const pending = this.pendingChat.get(id)
    if (!pending) return
    window.clearTimeout(pending.timer)
    this.pendingChat.delete(id)
    this.chatOrder = this.chatOrder.filter((other) => other !== id)
    action(pending)
  }

  private connect(): void {
    connectionStore.setState({ state: 'connecting' })
    const socket = new WebSocket(this.url)
    this.socket = socket
    // Handlers ignore sockets that were replaced or closed on purpose (StrictMode reopens quickly).
    socket.onopen = () => {
      if (this.socket !== socket) return
      this.retryMs = RETRY_MIN_MS
      connectionStore.setState({ state: 'live' })
      for (const message of this.outbox) socket.send(message.text)
      this.outbox = []
    }
    socket.onmessage = (event: MessageEvent<unknown>) => {
      if (this.socket === socket) this.onMessage(event.data)
    }
    socket.onclose = () => {
      if (this.socket !== socket) return
      this.socket = null
      connectionStore.setState({ state: 'offline' })
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
    let envelope: Envelope
    try {
      envelope = JSON.parse(data) as Envelope
    } catch {
      console.warn('live: frame is not valid JSON, dropped')
      return
    }
    if (envelope.type === 'CREW_STATE') {
      const payload = envelope.payload as CrewStatePayload
      crewStateStore.getState().confirm(payload.crew_id, payload.mission_mode)
    }
    if (envelope.type === 'ERROR') {
      const payload = envelope.payload as ErrorPayload
      if (payload.code === 'SET_CREW_ERROR') crewStateStore.getState().fail()
      if (payload.code === 'CHAT_ERROR') this.failChat(payload)
    }
    if (envelope.type === 'CHAT_REPLY') this.answerChat(envelope.payload as ChatReplyPayload)
    this.listeners.get(envelope.type)?.forEach((listener) => listener(envelope))
  }

  /** A reply pairs with the oldest message still waiting. */
  private answerChat(reply: ChatReplyPayload): void {
    const oldest = this.chatOrder[0]
    if (oldest === undefined) return
    this.settleChat(oldest, (pending) => pending.resolve(reply))
  }

  /** An error with an id fails that message; without one, it fails the oldest waiting message. */
  private failChat(error: ErrorPayload): void {
    const id = error.client_msg_id ?? this.chatOrder[0]
    if (id === undefined) return
    this.settleChat(id, (pending) => pending.reject(new Error(`${error.code}: ${error.message}`)))
  }
}
