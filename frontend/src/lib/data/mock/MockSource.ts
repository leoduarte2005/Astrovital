import type { ChatReplyPayload, CrewStatePayload, Envelope } from '@/lib/model/live'
import { connectionStore } from '../connection'
import { crewStateStore } from '../crewState'
import type { DataSource } from '../source'
import { pickMockReply } from './chatReplies'
import type { BaselineMetricId, BaselineProfile, HistorySeries, HistoryWindow } from '@/lib/model/baseline'
import { baselineProfile, historySeries } from './baseline'
import { suggestBooks, type Book } from './bookCatalog'
import { MOCK_CREW } from './crew'
import { simulateFrame } from './telemetry'

/**
 * Simulated central, used while the real one is not available. It behaves like the live source: the link is
 * "open" while a consumer holds it, telemetry arrives at 2 Hz for the confirmed crew member, and chat replies
 * come back after a short delay. Runs on the main thread with a plain timer.
 */

/** 2 Hz, the central's default telemetry rate. */
const TELEMETRY_PERIOD_MS = 500
/** Simulated time the central takes to answer a chat message. */
const CHAT_DELAY_MS = 900

type Listener = (envelope: Envelope) => void

/** Mission day of the crew member, from the mock crew list. */
const missionDayOf = (crewId: string) => MOCK_CREW.find((member) => member.crewId === crewId)?.missionDay ?? 42

export class MockSource implements DataSource {
  readonly kind = 'mock' as const
  private readonly listeners = new Map<string, Set<Listener>>()
  private readonly heartWatchers = new Map<string, Set<(bpm: number) => void>>()
  private heartTimer: number | undefined
  private references = 0
  private timer: number | undefined

  listCrew() {
    return Promise.resolve(MOCK_CREW)
  }

  subscribe(type: string, listener: Listener): () => void {
    const set = this.listeners.get(type) ?? new Set<Listener>()
    set.add(listener)
    this.listeners.set(type, set)
    return () => {
      set.delete(listener)
    }
  }

  /** Takes a reference. The first one starts the simulated telemetry. */
  open(): void {
    this.references++
    if (this.references > 1) return
    connectionStore.setState({ state: 'live' })
    this.timer = window.setInterval(() => this.tick(), TELEMETRY_PERIOD_MS)
  }

  /** Releases a reference. The last one stops the simulation. */
  close(): void {
    if (this.references === 0) return
    this.references--
    if (this.references > 0) return
    window.clearInterval(this.timer)
    this.timer = undefined
    connectionStore.setState({ state: 'offline' })
  }

  /** Simulated heart rate per crew member: one shared timer for every watched crew member. */
  watchHeartRate(crewId: string, listener: (bpm: number) => void): () => void {
    const listeners = this.heartWatchers.get(crewId) ?? new Set<(bpm: number) => void>()
    listeners.add(listener)
    this.heartWatchers.set(crewId, listeners)
    this.heartTimer ??= window.setInterval(() => this.tickHeartRate(), TELEMETRY_PERIOD_MS)
    return () => {
      this.heartWatchers.get(crewId)?.delete(listener)
      if (this.heartWatchers.get(crewId)?.size === 0) this.heartWatchers.delete(crewId)
      if (this.heartWatchers.size === 0) {
        window.clearInterval(this.heartTimer)
        this.heartTimer = undefined
      }
    }
  }

  /** Confirms the crew member at once, as the central would after `SET_CREW`, and announces it. */
  setCrew(crewId: string): void {
    const mode = 'MODE_REST_VITALS' as const
    crewStateStore.getState().confirm(crewId, mode)
    const payload: CrewStatePayload = {
      crew_id: crewId,
      mission_mode: mode,
      ai_ready: true,
      calibration_required: MOCK_CREW.find((member) => member.crewId === crewId)?.calibrationRequired ?? false,
    }
    this.emit({ v: 1, type: 'CREW_STATE', ts_us: Date.now() * 1000, crew_id: crewId, payload })
  }

  /** Answers after a short delay with a scripted reply, in the same shape as the central's. */
  sendChat(text: string): Promise<ChatReplyPayload> {
    if (text.trim() === '') return Promise.reject(new Error('empty chat text'))
    return new Promise((resolve) => {
      window.setTimeout(
        () =>
          resolve({
            text: pickMockReply(),
            evidence: [],
            countermeasures: [],
            source_ids: [],
            escalation: 'LOCAL',
            disclaimer: 'Resposta simulada; não substitui avaliação médica.',
          }),
        CHAT_DELAY_MS,
      )
    })
  }

  listBookSuggestions(crewId: string): Promise<Book[]> {
    return Promise.resolve(suggestBooks(crewId))
  }

  getBaseline(crewId: string): Promise<BaselineProfile> {
    return Promise.resolve(baselineProfile(crewId, missionDayOf(crewId), Date.now()))
  }

  history(crewId: string, metric: BaselineMetricId, window: HistoryWindow): Promise<HistorySeries> {
    return Promise.resolve(historySeries(crewId, metric, window, missionDayOf(crewId), Date.now()))
  }

  private tickHeartRate(): void {
    const now = Date.now()
    for (const [crewId, listeners] of this.heartWatchers) {
      const bpm = simulateFrame(crewId, now).vitals.heart_rate_bpm
      listeners.forEach((listener) => listener(bpm))
    }
  }

  private tick(): void {
    const crewId = crewStateStore.getState().crewId
    if (crewId === null) return
    const now = Date.now()
    this.emit({
      v: 1,
      type: 'TELEMETRY_FRAME',
      ts_us: now * 1000,
      crew_id: crewId,
      payload: simulateFrame(crewId, now),
    })
  }

  private emit(envelope: Envelope): void {
    this.listeners.get(envelope.type)?.forEach((listener) => listener(envelope))
  }
}
