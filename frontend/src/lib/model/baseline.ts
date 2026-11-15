import type { MessageKey } from '@/lib/i18n/types'

/**
 * The crew member's own baseline: what the AI learned about them in the 24 months before the mission. Every
 * measure is compared with this corridor, never with a population average (rules/charts.md). Draft shapes:
 * the central's profile and time series (`GET /api/crew/{id}/profile`, `.../timeseries`) are Leva 2.
 */
export type BaselineMetricId = 'heartRate' | 'hrv' | 'respRate' | 'spo2' | 'sleep'

/** Time windows of the longitudinal charts. `preflight` is the 24 months the baseline was learned from. */
export type HistoryWindow = 'day' | 'week' | 'mission' | 'preflight'

/** The crew member's normal range for a metric: the mean and the band around it. */
export interface Corridor {
  mean: number
  low: number
  high: number
}

export interface BaselineMetricSpec {
  id: BaselineMetricId
  labelKey: MessageKey
  /** Symbol, not translated (rules/i18n.md). */
  unit: string
  decimals: number
}

export const BASELINE_METRICS: BaselineMetricSpec[] = [
  { id: 'heartRate', labelKey: 'vital.heartRate', unit: 'bpm', decimals: 0 },
  { id: 'hrv', labelKey: 'vital.hrv', unit: 'ms', decimals: 0 },
  { id: 'respRate', labelKey: 'vital.respRate', unit: 'rpm', decimals: 1 },
  { id: 'spo2', labelKey: 'vital.spo2', unit: '%', decimals: 1 },
  { id: 'sleep', labelKey: 'vital.sleep', unit: '%', decimals: 0 },
]

export interface BaselineTraining {
  /** Epoch ms of the first and last day the baseline was learned from. */
  trainedFrom: number
  trainedTo: number
  /** Days that had data, out of `expectedDays` (24 months). */
  days: number
  expectedDays: number
  model: string
}

export interface BaselineProfile {
  crewId: string
  training: BaselineTraining
  corridors: Record<BaselineMetricId, Corridor>
}

/** One metric over one window. `x` is in seconds (uPlot time scale). */
export interface HistorySeries {
  metric: BaselineMetricId
  window: HistoryWindow
  x: number[]
  y: number[]
  corridor: Corridor
}

export type CorridorState = 'inside' | 'below' | 'above'

export function corridorState(value: number, corridor: Corridor): CorridorState {
  if (value < corridor.low) return 'below'
  if (value > corridor.high) return 'above'
  return 'inside'
}

/** How far outside the corridor a value is, as a percentage of the nearest edge. Zero when inside. */
export function deviationPercent(value: number, corridor: Corridor): number {
  if (value < corridor.low) return ((corridor.low - value) / corridor.low) * 100
  if (value > corridor.high) return ((value - corridor.high) / corridor.high) * 100
  return 0
}
