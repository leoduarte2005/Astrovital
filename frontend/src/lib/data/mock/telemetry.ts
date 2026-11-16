import type { Severity, Subsystem, TelemetryFramePayload } from '@/lib/model/live'
import { CREW_LORE, type CrewLore } from './crewLore'

/**
 * Simulated `TELEMETRY_FRAME` payload, shaped like the central's (guide §3). Used by the mock source while the
 * central is not available. Each crew member has their own baseline; the numbers move smoothly over time.
 * Pure: the same crew and time always give the same frame.
 */

const SUBSYSTEMS: Subsystem[] = [
  'CARDIOVASCULAR_FLUIDS',
  'RESPIRATORY_ATMOSPHERE',
  'NEURO_OCULAR_SANS',
  'MUSCULOSKELETAL_POSTURE',
  'IMMUNE_HEMATO_NUTRITION',
  'NEUROBEHAVIORAL_RADIATION',
]

const POSTURES = ['standing', 'sitting', 'prone'] as const

interface FrameBase {
  heartRate: number
  hrv: number
  resp: number
  spo2: number
}

/** SpO2 is not in the crew context: mock values, not measurements. */
const SPO2: Record<string, number> = { crew_001: 98.2, crew_002: 97.6, crew_003: 98.8 }
const DEFAULT_BASE: FrameBase = { heartRate: 66, hrv: 55, resp: 15, spo2: 98 }

/**
 * In flight the readings sit a little off the pre-flight baseline (heart rate up, HRV down, breathing slightly
 * faster), so the assistant has a calm, real-looking difference to explain. Mock factors, not physiology data.
 */
const IN_FLIGHT = { heartRate: 1.08, hrv: 0.9, resp: 1.05 }

/** Centre of the live frames: the crew context's baseline (crewLore), shifted for flight. */
function frameBase(crewId: string): FrameBase {
  const lore = (CREW_LORE as Record<string, CrewLore | undefined>)[crewId]
  if (!lore) return DEFAULT_BASE
  const m = lore.medical
  return {
    heartRate: m.baseline_hr_bpm * IN_FLIGHT.heartRate,
    hrv: m.baseline_hrv_ms * IN_FLIGHT.hrv,
    resp: m.baseline_resp_bpm * IN_FLIGHT.resp,
    spo2: SPO2[crewId] ?? DEFAULT_BASE.spo2,
  }
}

/** FNV-1a: a stable number for a text, used as a seed. */
function hash(text: string): number {
  let h = 0x811c9dc5
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i)
    h = Math.imul(h, 0x01000193)
  }
  return h >>> 0
}

/** mulberry32: a small deterministic random sequence from a seed, in [0, 1). */
function random(seed: number): () => number {
  let state = seed >>> 0
  return () => {
    state = (state + 0x6d2b79f5) >>> 0
    let t = state
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const round = (value: number, decimals: number) => Math.round(value * 10 ** decimals) / 10 ** decimals

export function simulateFrame(crewId: string, nowMs: number): TelemetryFramePayload {
  const base = frameBase(crewId)
  const seed = hash(crewId)
  const noise = random(seed + Math.floor(nowMs / 500))
  const t = nowMs / 1000
  const wave = (period: number, amplitude: number) => amplitude * Math.sin((2 * Math.PI * t) / period)
  // A short yellow window on the cardiovascular subsystem now and then, so the severity chart has a change to show.
  const cardioYellow = Math.floor(t / 90) % 6 === 0 && t % 90 < 12
  const posture = POSTURES[(Math.floor(t / 120) + (seed % 3)) % POSTURES.length] ?? 'standing'

  return {
    vitals: {
      heart_rate_bpm: round(base.heartRate + wave(60, 3) + (noise() - 0.5) * 2, 2),
      hrv_ms: round(base.hrv + wave(90, 4) + (noise() - 0.5) * 3, 2),
      resp_rate_bpm: round(base.resp + wave(30, 1) + (noise() - 0.5) * 0.6, 2),
      spo2_pct: round(Math.min(100, Math.max(90, base.spo2 + (noise() - 0.5) * 0.6)), 2),
      posture,
      confidence_score: round(0.88 + (noise() - 0.5) * 0.06, 2),
    },
    environment: {
      co2_ppm: round(600 + wave(300, 25) + (noise() - 0.5) * 10, 2),
      temp_c: round(22 + wave(600, 0.6), 2),
      humidity_pct: round(45 + wave(400, 2), 2),
      pressure_hpa: round(1013 + wave(900, 0.8), 2),
    },
    subsystems: SUBSYSTEMS.map((subsystem) => ({
      subsystem,
      severity: (subsystem === 'CARDIOVASCULAR_FLUIDS' && cardioYellow ? 'YELLOW' : 'GREEN') as Severity,
      message: '',
    })),
    ai_ready: true,
  }
}
