/**
 * Draft envelope of the central's WebSocket (handoff of 2026-11-14, `central/internal/contracts/`).
 * Not a closed contract: divergences go to `docs/contract-notes.md`. Payloads stay `unknown` until
 * the frames are confirmed in DevTools.
 */
export interface Envelope<P = unknown> {
  v: number
  /** Message type as sent by the central (e.g. TELEMETRY_FRAME, CLUSTER_STATUS). Not filtered by the UI layer. */
  type: string
  /** Microseconds since epoch. */
  ts_us: number
  crew_id: string | null
  client_msg_id?: string
  payload: P
}

/** Server to client types announced by the handoff. Used for documentation; unknown types still pass through. */
export type ServerMessageType =
  | 'TELEMETRY_FRAME'
  | 'CREW_STATE'
  | 'CLUSTER_STATUS'
  | 'ALERT_EVENT'
  | 'CHAT_REPLY'
  | 'CALIBRATION_FEEDBACK'
  | 'ERROR'

/** `GET /api/crew` item: `CrewSummary` in central/internal/contracts/types.go. */
export interface CrewSummary {
  crew_id: string
  name: string
  /** Free text from the central (e.g. "Commander", "Flight Surgeon"). */
  role?: string
  mission_day?: number
  calibration_required: boolean
}

/** Severity as sent by the central. The UI shows it with a label or icon, never colour alone. */
export type Severity = 'GREEN' | 'YELLOW' | 'RED'

/** Subsystems of `TELEMETRY_FRAME` and `ALERT_EVENT` (guide §3, central contracts). */
export type Subsystem =
  | 'CARDIOVASCULAR_FLUIDS'
  | 'RESPIRATORY_ATMOSPHERE'
  | 'NEURO_OCULAR_SANS'
  | 'MUSCULOSKELETAL_POSTURE'
  | 'IMMUNE_HEMATO_NUTRITION'
  | 'NEUROBEHAVIORAL_RADIATION'

export type MissionMode =
  | 'MODE_CABIN_TOMOGRAPHY'
  | 'MODE_REST_VITALS'
  | 'MODE_COUNTERMEASURE_EXERCISE'
  | 'MODE_RADIATION_ALERT'

/** `CREW_STATE` payload. `profile` is not used yet (see docs/contract-notes.md). */
export interface CrewStatePayload {
  crew_id: string | null
  profile?: CrewSummary
  mission_mode: MissionMode
  ai_ready: boolean
  calibration_required: boolean
}

/** `ERROR` payload. */
export interface ErrorPayload {
  code: string
  message: string
  client_msg_id?: string
}

/** `SET_CREW` payload (client to central). */
export interface SetCrewPayload {
  crew_id: string
}

/** `TELEMETRY_FRAME` payload (server to client, ~2 Hz). Checked against a live sample. */
export interface TelemetryFramePayload {
  vitals: {
    heart_rate_bpm: number
    hrv_ms: number
    resp_rate_bpm: number
    spo2_pct: number
    posture: string
    confidence_score: number
  }
  environment: {
    co2_ppm: number
    temp_c: number
    humidity_pct: number
    pressure_hpa: number
  }
  /** `message` is absent in the live sample; the guide shows it as "". */
  subsystems: { subsystem: Subsystem; severity: Severity; message?: string }[]
  /** When false, `hrv_ms`, `resp_rate_bpm` and `confidence_score` arrive as 0 and `posture` as "": degraded state, not an error. */
  ai_ready: boolean
}

export type PeripheralName = 'MAX30102' | 'BME280' | 'SCD40'

export type NodeState = 'DISCOVERED' | 'SYNCING' | 'ACTIVE' | 'SUSPECT' | 'LOST'

export interface ClusterNode {
  node_id: number
  mac: string
  state: NodeState
  slot: number
  peripherals: PeripheralName[]
  last_seen_us: number
  rssi_dbm: number
}

/** `CLUSTER_STATUS` payload (server to client). Always `crew_id: null` in the envelope. */
export interface ClusterStatusPayload {
  nodes: ClusterNode[]
  active_links: number
  total_links: number
  ai_link: 'online' | 'degraded' | 'offline'
  dropped_frames: number
  dropped_ctrl: number
  dropped_windows: number
}

/** `CHAT_MSG` payload (client to central). Text is 1 to 2000 bytes. */
export interface ChatMsgPayload {
  text: string
}

/** Escalation levels of a chat reply. */
export type Escalation = 'LOCAL' | 'CREW' | 'STORE_AND_FORWARD'

/**
 * `CHAT_REPLY` payload (server to client). Field names and types confirmed by a real reply (2026-11-15).
 * It has no `client_msg_id`: replies pair with sent messages in the order they were sent.
 * `disambiguation_question` appears when the central needs more detail; `text` is what the chat shows.
 */
export interface ChatReplyPayload {
  text: string
  evidence: string[]
  countermeasures: string[]
  source_ids: string[]
  escalation: Escalation
  disclaimer: string
  disambiguation_question?: string
}
