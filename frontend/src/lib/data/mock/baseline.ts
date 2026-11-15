import type { BaselineMetricId, BaselineProfile, Corridor, HistorySeries, HistoryWindow } from '@/lib/model/baseline'
import { BASELINE_METRICS } from '@/lib/model/baseline'

/**
 * Simulated baseline and history. The central does not provide them yet, so the mock "trains" on 24 months
 * (730 days) before the mission for each crew member and then continues through the mission days. Pure and
 * deterministic: the same crew, metric and time always give the same numbers. Values are invented, not measured.
 */

const DAY_MS = 86_400_000
const HOUR_MS = 3_600_000
export const TRAINING_DAYS = 730
const MODEL = 'EDGESPACE-AI-V1 (mock)'
/** Share of training days that have no data, so the coverage is not a perfect 100%. */
const MISSING_SHARE = 0.03
/** Half-width of the corridor, in standard deviations of the training period. */
const CORRIDOR_SD = 1.5

interface Params {
  /** Typical value before the mission. */
  base: number
  /** Day-to-day spread. */
  sd: number
  /** Yearly swing. */
  annual: number
  /** Change per mission day: how the measure moves away from the baseline in flight. */
  drift: number
}

const p = (base: number, sd: number, annual: number, drift: number): Params => ({ base, sd, annual, drift })
type CrewParams = Record<BaselineMetricId, Params>

/** Opposite profiles on purpose (rules/crew.md): a low resting heart rate and high HRV, and the reverse. */
const CREW_PARAMS: Record<string, CrewParams> = {
  crew_001: { heartRate: p(58, 2.2, 1.2, 0.14), hrv: p(74, 6, 3, -0.3), respRate: p(14.5, 0.6, 0.2, 0.02), spo2: p(98.4, 0.35, 0.1, -0.01), sleep: p(91, 3, 1, -0.1) },
  crew_002: { heartRate: p(66, 2.2, 1, 0.03), hrv: p(58, 5, 2.5, -0.05), respRate: p(15.5, 0.6, 0.2, 0), spo2: p(97.8, 0.4, 0.1, 0), sleep: p(88, 3, 1, -0.03) },
  crew_003: { heartRate: p(70, 2.4, 1.2, 0.05), hrv: p(52, 5, 2.5, -0.1), respRate: p(16, 0.7, 0.2, 0.03), spo2: p(98.1, 0.4, 0.1, -0.02), sleep: p(85, 3.5, 1.2, -0.15) },
}
const DEFAULT_PARAMS: CrewParams = {
  heartRate: p(66, 2.2, 1, 0.03),
  hrv: p(58, 5, 2.5, -0.05),
  respRate: p(15.5, 0.6, 0.2, 0),
  spo2: p(97.8, 0.4, 0.1, 0),
  sleep: p(88, 3, 1, -0.03),
}

function hash(text: string): number {
  let h = 0x811c9dc5
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i)
    h = Math.imul(h, 0x01000193)
  }
  h ^= h >>> 16
  h = Math.imul(h, 0x45d9f3b)
  h ^= h >>> 16
  return h >>> 0
}

/** A stable number in [0, 1) for a key. */
const unit = (key: string) => hash(key) / 4294967296
/** A stable, roughly normal number (sum of three uniforms) with spread 1. */
const gaussian = (key: string) => (unit(`${key}a`) + unit(`${key}b`) + unit(`${key}c`) - 1.5) * 2

/** Daily rhythm, only for the 24 h window: the heart rate is lower at night, the HRV higher. */
function circadian(metric: BaselineMetricId, hour: number): number {
  const phase = Math.sin((2 * Math.PI * (hour - 9)) / 24)
  if (metric === 'heartRate') return 5 * phase
  if (metric === 'hrv') return -6 * phase
  if (metric === 'respRate') return 0.8 * phase
  return 0
}

const round = (value: number, decimals = 2) => Math.round(value * 10 ** decimals) / 10 ** decimals

/**
 * One value. `dayIndex` counts days from the mission start (negative before it). `hour` is set only for the hourly
 * window; `key` makes the noise stable for that day or hour.
 */
function sample(crewId: string, metric: BaselineMetricId, dayIndex: number, hour: number | null, key: string): number {
  const params = (CREW_PARAMS[crewId] ?? DEFAULT_PARAMS)[metric]
  const annual = params.annual * Math.sin((2 * Math.PI * dayIndex) / 365)
  const weekly = params.sd * 0.15 * Math.sin((2 * Math.PI * dayIndex) / 7)
  const drift = dayIndex >= 0 ? params.drift * dayIndex : 0
  const circ = hour === null ? 0 : circadian(metric, hour)
  const value = params.base + annual + weekly + drift + circ + params.sd * gaussian(`${crewId}|${metric}|${key}`)
  const limit = metric === 'spo2' || metric === 'sleep' ? 100 : Infinity
  return round(Math.min(limit, Math.max(0, value)))
}

interface Training {
  days: number[]
  corridors: Record<BaselineMetricId, Corridor>
}
const trainingCache = new Map<string, Training>()

/** The 24 months before the mission: which days have data, and the corridor learned from them. */
function training(crewId: string): Training {
  const cached = trainingCache.get(crewId)
  if (cached) return cached
  const days: number[] = []
  for (let d = -TRAINING_DAYS; d < 0; d++) {
    if (unit(`${crewId}|missing|${d}`) >= MISSING_SHARE) days.push(d)
  }
  const corridors = {} as Record<BaselineMetricId, Corridor>
  for (const { id } of BASELINE_METRICS) {
    const values = days.map((d) => sample(crewId, id, d, null, `d${d}`))
    const mean = values.reduce((sum, v) => sum + v, 0) / values.length
    const sd = Math.sqrt(values.reduce((sum, v) => sum + (v - mean) ** 2, 0) / values.length)
    corridors[id] = { mean: round(mean), low: round(mean - CORRIDOR_SD * sd), high: round(mean + CORRIDOR_SD * sd) }
  }
  const result = { days, corridors }
  trainingCache.set(crewId, result)
  return result
}

export function baselineProfile(crewId: string, missionDay: number, nowMs: number): BaselineProfile {
  const missionStart = nowMs - missionDay * DAY_MS
  const { days, corridors } = training(crewId)
  return {
    crewId,
    training: {
      trainedFrom: missionStart - TRAINING_DAYS * DAY_MS,
      trainedTo: missionStart - DAY_MS,
      days: days.length,
      expectedDays: TRAINING_DAYS,
      model: MODEL,
    },
    corridors,
  }
}

export function historySeries(
  crewId: string,
  metric: BaselineMetricId,
  window: HistoryWindow,
  missionDay: number,
  nowMs: number,
): HistorySeries {
  const corridor = training(crewId).corridors[metric]
  const missionStart = nowMs - missionDay * DAY_MS
  // Sleep is one value per night: its 24 h window shows the last seven nights instead.
  const effective = metric === 'sleep' && window === 'day' ? 'week' : window
  const x: number[] = []
  const y: number[] = []
  const push = (t: number, value: number) => {
    x.push(t / 1000)
    y.push(value)
  }

  if (effective === 'day') {
    for (let i = 0; i < 24; i++) {
      const t = nowMs - (23 - i) * HOUR_MS
      push(t, sample(crewId, metric, (t - missionStart) / DAY_MS, new Date(t).getUTCHours(), `h${Math.floor(t / HOUR_MS)}`))
    }
  } else if (effective === 'week') {
    for (let i = 0; i < 7; i++) {
      const t = nowMs - (6 - i) * DAY_MS
      const d = Math.floor((t - missionStart) / DAY_MS)
      push(t, sample(crewId, metric, d, null, `d${d}`))
    }
  } else if (effective === 'mission') {
    for (let d = 1; d <= missionDay; d++) push(missionStart + d * DAY_MS, sample(crewId, metric, d, null, `d${d}`))
  } else {
    for (const d of training(crewId).days) push(missionStart + d * DAY_MS, sample(crewId, metric, d, null, `d${d}`))
  }
  return { metric, window, x, y, corridor }
}
