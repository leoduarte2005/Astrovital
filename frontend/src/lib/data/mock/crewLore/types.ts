/**
 * Astro Vital — crew lore (MOCK, FICTIONAL). Written in English, the assistant's default language.
 *
 * Everything here is invented for the mock phase. No data belongs to a real person.
 * The lore feeds three consumers:
 *   1. the training hangar simulation (avatars over the 24 months before launch);
 *   2. the on-board AI's individual context (Contract 1, `particularities` field);
 *   3. the UI's personalisation (polaroid, content filters, chat suggestions, personal space).
 *
 * Privacy (rules/offline-and-privacy.md): fields typed `Private<T>` may only be shown with the
 * crew member's explicit consent (`visibleInUi`). Sexual orientation and health notes NEVER
 * change clinical thresholds nor appear outside the crew member's own profile.
 */

export type CrewId = 'crew_001' | 'crew_002' | 'crew_003'

/** Training period: M01 = 2024-10 … M24 = 2026-09. Launch on 2026-10-05 (mission day 1). */
export type TrainingMonth =
  | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12
  | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 | 21 | 22 | 23 | 24

/** Training hangar zones used by the avatar simulation. */
export type HangarZone =
  | 'gym'            // ASCR gym (strength, rowing, treadmill)
  | 'pool_nbl'       // neutral buoyancy pool (EVA)
  | 'centrifuge'     // centrifuge (launch and re-entry profiles)
  | 'sim_cockpit'    // cabin simulator
  | 'robotics_bay'   // robotic arm station
  | 'classroom'      // systems classes
  | 'medbay'         // medical cross-training
  | 'garden_lab'     // plant-growth lab
  | 'mess'           // mess
  | 'lounge'         // lounge
  | 'comms_desk'     // radio desk and delayed communication
  | 'workshop'       // workshop and bench
  | 'quarters'       // quarters

/** Sensitive data: shown in the UI only when `visibleInUi` is true by consent. */
export interface Private<T> {
  value: T
  visibleInUi: boolean
}

export type CastId =
  | 'okafor' | 'lindqvist' | 'ramirez' | 'haddad' | 'kowalski'
  | 'iyer' | 'walsh' | 'beaumont' | 'nguyen'

export interface LovedOne {
  id: string
  name: string
  relation: string
  age?: number
  location: string
  note: string
  /** May appear on the polaroid or in reminders, if consent allows. */
  featurable: boolean
}

export interface Identity {
  givenName: string
  familyName: string
  displayName: string        // same as the API's `fullName`
  pronouns: string
  birthDate: string          // ISO
  ageAtLaunch: number
  birthplace: string
  nationality: string        // ISO 3166-1 alpha-2, same as the API
  languages: string[]
  sexualOrientation: Private<string>
  relationshipStatus: Private<string>
  agency: string
}

export interface Background {
  childhood: string
  education: string[]
  career: string[]
  whySpace: string
  personality: string[]
  values: string[]
}

export interface Tastes {
  hobbies: string[]
  hobbyGenres: string[]
  books: string[]
  bookGenres: string[]
  films: string[]
  filmGenres: string[]
  music: string[]
  musicGenres: string[]
  games: string[]
  gameGenres: string[]
  food: string[]
  /** Activities possible on board that suit the crew member. */
  spaceActivities: string[]
  /** Topics the AI must not raise on its own. */
  avoidTopics: string[]
}

export type Rating = 1 | 2 | 3 | 4 | 5

export interface TrainingProfile {
  gym: { rating: Rating; style: string }
  centrifuge: { rating: Rating; note: string }
  swimming: { rating: Rating; note: string }
  simulations: { rating: Rating; note: string }
  communication: { rating: Rating; note: string }
  stressResponse: string
}

/** Individual clinical baseline, in the Contract 1 shape (CONTEXT_SWITCH). */
export interface MedicalBaseline {
  baseline_hr_bpm: number
  baseline_hrv_ms: number
  baseline_resp_bpm: number
  baseline_bp_sys: number
  baseline_bp_dia: number
  baseline_sleep_h: number
  blood_type: string
  particularities: string[]
  /** How the crew member tends to report symptoms; guides the AI, not the diagnosis. */
  reportingStyle: string
  watchlist: string[]
}

export interface AvatarBehavior {
  preferredZones: HangarZone[]
  /** 0 = always alone, 1 = always in a group. */
  sociability: number
  /** Preferred conversation distance, in metres. */
  personalSpaceM: number
  walkSpeed: 'slow' | 'normal' | 'brisk'
  idleBehaviors: string[]
  arrivesEarly: boolean
  closestCrew: CrewId[]
  closestCast: CastId[]
}

export interface UiAdaptation {
  polaroid: {
    enabled: boolean
    /** Path served under /media/ (outside the build). In the mock, an anonymous placeholder. */
    imageRef: string
    caption: string
    clip: 'top-left' | 'top-right'
    rotationDeg: number
    consentNote: string
  }
  tone: 'direct' | 'warm' | 'technical'
  density: 'compact' | 'comfortable' | 'detailed'
  greeting: string
  chatSuggestions: string[]
  nudges: string[]
  homeWidgets: string[]
  contentFilters: {
    books: string[]
    films: string[]
    music: string[]
    games: string[]
  }
}

export type InteractionKind = 'bond' | 'mentoring' | 'friction' | 'support' | 'teamwork' | 'social'

export interface Interaction {
  with: CrewId | CastId
  kind: InteractionKind
  note: string
}

export interface MonthEntry {
  month: TrainingMonth
  period: string            // YYYY-MM
  title: string
  narrative: string
  interactions: Interaction[]
  /** 0–100; absent when the activity was not assessed that month. */
  performance: Partial<Record<'gym' | 'centrifuge' | 'pool' | 'simulations' | 'social', number>>
  wellbeing: { mood: Rating; sleepH: number; stress: number }
  /** Relative share of time per zone in the month (sum ≈ 1), for the simulation. */
  zones: Partial<Record<HangarZone, number>>
  /** What the AI learned that month. Becomes `crew_ai_memory` in the mock. */
  aiNotes: string[]
}

export interface CrewLore {
  crewId: CrewId
  identity: Identity
  background: Background
  lovedOnes: LovedOne[]
  tastes: Tastes
  training: TrainingProfile
  medical: MedicalBaseline
  avatar: AvatarBehavior
  ui: UiAdaptation
  timeline: MonthEntry[]
}

export interface ProgramMonth {
  month: TrainingMonth
  period: string
  phase: string
  location: string
  summary: string
}

export interface CastMember {
  id: CastId
  name: string
  role: string
  agency: string
  hint: string
}
