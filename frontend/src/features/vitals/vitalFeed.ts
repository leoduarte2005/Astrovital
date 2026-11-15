import type { DataSource } from '@/lib/data'
import { crewStateStore } from '@/lib/data/crewState'
import type { Envelope, TelemetryFramePayload } from '@/lib/model/live'
import type { ChartFeed, LineSnapshot, OhlcSnapshot } from '@/ui/Chart'
import { VITAL_SPECS, type VitalSpec } from './vitalSpecs'

/** Line samples kept per vital: the expanded view's 20 readings. Older ones are discarded. */
const LINE_POINTS = 20
/** Bucket width of the candles, in seconds. */
export const OHLC_BUCKET_SECONDS = 5
/** 5 min of candles. */
const OHLC_BUCKETS = 60

interface Point {
  x: number
  y: number | null
}

interface Bucket {
  t: number
  open: number
  high: number
  low: number
  close: number
}

/**
 * Keeps the recent vital values for the charts. Fed by `TELEMETRY_FRAME` while the home is mounted, and
 * only for the crew member the central confirmed. Charts read it on animation frames (see ui/Chart).
 */
export class VitalFeed {
  private unsubscribe: (() => void) | null = null
  private readonly listeners = new Set<() => void>()
  private readonly lines = new Map<string, Point[]>()
  private readonly buckets = new Map<string, Bucket[]>()
  private readonly feeds = new Map<string, ChartFeed<unknown>>()
  private readonly snapshots = new Map<string, { version: number; value: unknown }>()
  /** Texts seen per categorical vital (posture), in order of appearance. A text's index is its y value. */
  private readonly categories = new Map<string, string[]>()
  private version = 0
  private frameAt: number | null = null

  /** Starts receiving frames. Idempotent. */
  start(source: DataSource): void {
    if (this.unsubscribe) return
    this.clear()
    this.unsubscribe = source.subscribe('TELEMETRY_FRAME', (envelope) =>
      this.push(envelope as Envelope<TelemetryFramePayload>),
    )
  }

  /** Stops receiving frames and drops the buffers (they belong to the crew member on screen). */
  stop(): void {
    this.unsubscribe?.()
    this.unsubscribe = null
    this.clear()
  }

  /** Epoch ms of the last accepted frame, or null when none arrived since start. */
  lastFrame(): number | null {
    return this.frameAt
  }

  lineFeed(id: string): ChartFeed<LineSnapshot> {
    return this.feed(id, () => this.lineSnapshot(id))
  }

  ohlcFeed(id: string): ChartFeed<OhlcSnapshot> {
    return this.feed(id, () => this.ohlcSnapshot(id))
  }

  private feed<S>(id: string, build: () => S): ChartFeed<S> {
    const existing = this.feeds.get(id)
    if (existing) return existing as ChartFeed<S>
    const feed: ChartFeed<S> = {
      read: () => this.cached(id, build),
      subscribe: (listener) => {
        this.listeners.add(listener)
        return () => {
          this.listeners.delete(listener)
        }
      },
    }
    this.feeds.set(id, feed as ChartFeed<unknown>)
    return feed
  }

  private cached<S>(id: string, build: () => S): S {
    const hit = this.snapshots.get(id)
    if (hit && hit.version === this.version) return hit.value as S
    const value = build()
    this.snapshots.set(id, { version: this.version, value })
    return value
  }

  private push(envelope: Envelope<TelemetryFramePayload>): void {
    const confirmed = crewStateStore.getState().crewId
    if (confirmed === null || envelope.crew_id !== confirmed) return
    const frame = envelope.payload
    if (!frame?.vitals || !frame.environment) return
    const seconds = envelope.ts_us / 1e6
    for (const spec of VITAL_SPECS) {
      const value = this.valueOf(spec, frame)
      if (spec.kind === 'line') this.appendPoint(spec.id, seconds, value)
      else if (value !== null) this.addToBucket(spec.id, seconds, value)
    }
    this.frameAt = Date.now()
    this.bump()
  }

  /** The spec's value as a number: a text becomes its category index; null or an empty text is a gap. */
  private valueOf(spec: VitalSpec, frame: TelemetryFramePayload): number | null {
    const raw = spec.read(frame)
    if (typeof raw !== 'string') return raw
    if (raw === '') return null
    const list = this.categories.get(spec.id) ?? []
    let index = list.indexOf(raw)
    if (index === -1) {
      index = list.length
      list.push(raw)
    }
    this.categories.set(spec.id, list)
    return index
  }

  /** Texts of a categorical vital, indexed by the y value the chart receives. */
  categoriesFor(id: string): readonly string[] {
    return this.categories.get(id) ?? []
  }

  private appendPoint(id: string, x: number, y: number | null): void {
    const points = this.lines.get(id) ?? []
    points.push({ x, y })
    if (points.length > LINE_POINTS) points.splice(0, points.length - LINE_POINTS)
    this.lines.set(id, points)
  }

  private addToBucket(id: string, seconds: number, value: number): void {
    const t = Math.floor(seconds / OHLC_BUCKET_SECONDS) * OHLC_BUCKET_SECONDS
    const list = this.buckets.get(id) ?? []
    const last = list[list.length - 1]
    if (last && last.t === t) {
      last.high = Math.max(last.high, value)
      last.low = Math.min(last.low, value)
      last.close = value
    } else {
      list.push({ t, open: value, high: value, low: value, close: value })
      if (list.length > OHLC_BUCKETS) list.splice(0, list.length - OHLC_BUCKETS)
    }
    this.buckets.set(id, list)
  }

  private lineSnapshot(id: string): LineSnapshot {
    const points = this.lines.get(id) ?? []
    return { x: points.map((p) => p.x), y: points.map((p) => p.y) }
  }

  private ohlcSnapshot(id: string): OhlcSnapshot {
    const list = this.buckets.get(id) ?? []
    return {
      x: list.map((b) => b.t),
      open: list.map((b) => b.open),
      high: list.map((b) => b.high),
      low: list.map((b) => b.low),
      close: list.map((b) => b.close),
    }
  }

  private clear(): void {
    this.lines.clear()
    this.buckets.clear()
    this.categories.clear()
    this.frameAt = null
    this.bump()
  }

  private bump(): void {
    this.version++
    this.listeners.forEach((listener) => listener())
  }
}

export const vitalFeed = new VitalFeed()
