import type { MessageKey } from '@/lib/i18n'
import type { Severity, Subsystem, TelemetryFramePayload } from '@/lib/model/live'

export interface VitalSpec {
  id: string
  labelKey: MessageKey
  /** Symbol from the central's contract. Not translated (rules/i18n.md). */
  unit: string
  decimals: number
  /** Fixed y scale. Omit to auto-fit, so values outside a "normal" band are never clipped. */
  range?: [number, number]
  /**
   * A number, or a text for categorical values (the feed maps each text to an index). Null, or an empty
   * text, is a gap: no value, never zero.
   */
  read: (frame: TelemetryFramePayload) => number | string | null
}

/**
 * Values that depend on the AI. While `ai_ready` is false the central sends 0 for them: that is a
 * degraded state, so it is read as a gap (null), never plotted as zero.
 */
const needsAi = (frame: TelemetryFramePayload, value: number) => (frame.ai_ready ? value : null)

/** Severity as a level for a line: GREEN 0, YELLOW 1, RED 2. Labels come from the UI, not from the value. */
export const SEVERITY_LEVEL: Record<Severity, number> = { GREEN: 0, YELLOW: 1, RED: 2 }

export const HEART_RATE: VitalSpec = {
  id: 'heartRate',
  labelKey: 'vital.heartRate',
  unit: 'bpm',
  decimals: 0,
  read: (f) => f.vitals.heart_rate_bpm,
}

export const HRV: VitalSpec = {
  id: 'hrv',
  labelKey: 'vital.hrv',
  unit: 'ms',
  decimals: 0,
  read: (f) => needsAi(f, f.vitals.hrv_ms),
}

export const SPO2: VitalSpec = {
  id: 'spo2',
  labelKey: 'vital.spo2',
  unit: '%',
  decimals: 1,
  read: (f) => f.vitals.spo2_pct,
}

export const RESP_RATE: VitalSpec = {
  id: 'respRate',
  labelKey: 'vital.respRate',
  unit: 'rpm',
  decimals: 1,
  read: (f) => needsAi(f, f.vitals.resp_rate_bpm),
}

/** Cabin CO2. The contract files it under the respiratory and atmosphere subsystem. */
export const CO2: VitalSpec = {
  id: 'co2',
  labelKey: 'vital.co2',
  unit: 'ppm',
  decimals: 0,
  read: (f) => f.environment.co2_ppm,
}

/** Cabin temperature (BME280). */
export const TEMP: VitalSpec = {
  id: 'temp',
  labelKey: 'vital.temp',
  unit: '°C',
  decimals: 1,
  read: (f) => f.environment.temp_c,
}

/** Cabin relative humidity (BME280). */
export const HUMIDITY: VitalSpec = {
  id: 'humidity',
  labelKey: 'vital.humidity',
  unit: '%',
  decimals: 0,
  read: (f) => f.environment.humidity_pct,
}

/** Cabin pressure (BME280). */
export const PRESSURE: VitalSpec = {
  id: 'pressure',
  labelKey: 'vital.pressure',
  unit: 'hPa',
  decimals: 0,
  read: (f) => f.environment.pressure_hpa,
}

/** Posture is a text from the central ("" while the AI is not ready, which is a gap). Shown as steps. */
export const POSTURE: VitalSpec = {
  id: 'posture',
  labelKey: 'vital.posture',
  unit: '',
  decimals: 0,
  read: (f) => f.vitals.posture,
}

const SUBSYSTEM_LABEL: Record<Subsystem, MessageKey> = {
  CARDIOVASCULAR_FLUIDS: 'enum.subsystem.CARDIOVASCULAR_FLUIDS',
  RESPIRATORY_ATMOSPHERE: 'enum.subsystem.RESPIRATORY_ATMOSPHERE',
  NEURO_OCULAR_SANS: 'enum.subsystem.NEURO_OCULAR_SANS',
  MUSCULOSKELETAL_POSTURE: 'enum.subsystem.MUSCULOSKELETAL_POSTURE',
  IMMUNE_HEMATO_NUTRITION: 'enum.subsystem.IMMUNE_HEMATO_NUTRITION',
  NEUROBEHAVIORAL_RADIATION: 'enum.subsystem.NEUROBEHAVIORAL_RADIATION',
}

/** One subsystem's severity as a level over time, straight from `subsystems[]` (the UI never computes it). */
function severitySpec(subsystem: Subsystem): VitalSpec {
  return {
    id: `severity.${subsystem}`,
    labelKey: SUBSYSTEM_LABEL[subsystem],
    unit: '',
    decimals: 0,
    range: [0, 2],
    read: (f) => {
      const entry = f.subsystems.find((s) => s.subsystem === subsystem)
      return entry ? SEVERITY_LEVEL[entry.severity] : null
    },
  }
}

export const SEVERITY: Record<Subsystem, VitalSpec> = {
  CARDIOVASCULAR_FLUIDS: severitySpec('CARDIOVASCULAR_FLUIDS'),
  RESPIRATORY_ATMOSPHERE: severitySpec('RESPIRATORY_ATMOSPHERE'),
  NEURO_OCULAR_SANS: severitySpec('NEURO_OCULAR_SANS'),
  MUSCULOSKELETAL_POSTURE: severitySpec('MUSCULOSKELETAL_POSTURE'),
  IMMUNE_HEMATO_NUTRITION: severitySpec('IMMUNE_HEMATO_NUTRITION'),
  NEUROBEHAVIORAL_RADIATION: severitySpec('NEUROBEHAVIORAL_RADIATION'),
}

/** Everything the feed records each frame: what the markers and the side panels of the medical page show. */
export const VITAL_SPECS: VitalSpec[] = [
  HEART_RATE,
  HRV,
  SPO2,
  RESP_RATE,
  CO2,
  TEMP,
  HUMIDITY,
  PRESSURE,
  POSTURE,
  ...Object.values(SEVERITY),
]
