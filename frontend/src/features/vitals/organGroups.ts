import type { Subsystem } from '@/lib/model/live'
import { CO2, HEART_RATE, HRV, POSTURE, RESP_RATE, SEVERITY, SPO2, type VitalSpec } from './vitalSpecs'

export interface GroupChart {
  spec: VitalSpec
  /** Path shape: `smooth` (spline), `linear` (straight segments) or `stepped` (levels and categories). */
  curve: 'smooth' | 'linear' | 'stepped'
  /** How values are labelled: severity levels or the texts of a categorical vital. Omit for numbers. */
  labels?: 'severity' | 'category'
}

export interface OrganGroup {
  /** Token of the series colour shared by every chart of the group. */
  seriesToken: string
  charts: GroupChart[]
}

const severity = (subsystem: Subsystem): GroupChart => ({ spec: SEVERITY[subsystem], curve: 'stepped', labels: 'severity' })

/**
 * Charts per twin marker (`TwinAnchorId`), from the data of `TELEMETRY_FRAME`. A marker without an entry
 * shows no charts. Kidneys use the fluids severity (assumption: the contract has no renal subsystem).
 */
export const ORGAN_GROUPS: Record<string, OrganGroup> = {
  heart: {
    seriesToken: '--organ-blood',
    charts: [
      { spec: HEART_RATE, curve: 'linear' },
      { spec: SPO2, curve: 'smooth' },
      { spec: HRV, curve: 'smooth' },
      severity('CARDIOVASCULAR_FLUIDS'),
    ],
  },
  jugular: {
    seriesToken: '--organ-blood',
    charts: [severity('CARDIOVASCULAR_FLUIDS'), { spec: HEART_RATE, curve: 'linear' }],
  },
  vascular: {
    seriesToken: '--organ-blood',
    charts: [severity('CARDIOVASCULAR_FLUIDS'), { spec: HEART_RATE, curve: 'linear' }],
  },
  lungs: {
    seriesToken: '--organ-lungs',
    charts: [
      { spec: SPO2, curve: 'smooth' },
      { spec: RESP_RATE, curve: 'smooth' },
      { spec: CO2, curve: 'smooth' },
      severity('RESPIRATORY_ATMOSPHERE'),
    ],
  },
  brain: {
    seriesToken: '--organ-neuro',
    charts: [severity('NEURO_OCULAR_SANS'), severity('NEUROBEHAVIORAL_RADIATION'), { spec: HRV, curve: 'smooth' }],
  },
  liver: { seriesToken: '--organ-nutrition', charts: [severity('IMMUNE_HEMATO_NUTRITION')] },
  gut: { seriesToken: '--organ-nutrition', charts: [severity('IMMUNE_HEMATO_NUTRITION')] },
  kidneys: { seriesToken: '--organ-kidneys', charts: [severity('CARDIOVASCULAR_FLUIDS')] },
  spine: {
    seriesToken: '--organ-spine',
    charts: [severity('MUSCULOSKELETAL_POSTURE'), { spec: POSTURE, curve: 'stepped', labels: 'category' }],
  },
}
