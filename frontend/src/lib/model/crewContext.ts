/**
 * Everything the UI and the on-board assistant know about one crew member: the individual baseline, what the AI
 * learned in the 24 months of training, wellbeing and preferences. Built from the crew lore (mock until the
 * central serves profiles), already filtered by consent: private fields (orientation, relationship) never get here.
 * Free text comes from the source in its own language and is never translated.
 */

/** 1 = least, 5 = most. */
export type ContextRating = 1 | 2 | 3 | 4 | 5

export type MissionPhase = 'preflight' | 'flight'

/** Individual clinical baseline, learned before the mission (Contract 1, `CONTEXT_SWITCH`). */
export interface ContextBaseline {
  hrBpm: number
  hrvMs: number
  respBpm: number
  bpSys: number
  bpDia: number
  sleepH: number
  bloodType: string
}

/** One of the 24 training months and what the assistant learned in it. */
export interface LearnedMonth {
  month: number
  /** YYYY-MM. */
  period: string
  /** Programme phase of the month (e.g. "Centrifuge"). */
  phase: string
  title: string
  notes: string[]
}

/** Self-reported wellbeing of one training month. */
export interface WellbeingMonth {
  month: number
  period: string
  mood: ContextRating
  sleepH: number
  /** 0–100. */
  stress: number
}

/** Titles and the genres they belong to, as the profile names them. */
export interface CrewTastes {
  hobbies: string[]
  games: string[]
  gameGenres: string[]
  books: string[]
  bookGenres: string[]
  music: string[]
  musicGenres: string[]
  films: string[]
  filmGenres: string[]
}

export interface TrainingSkill {
  rating: ContextRating
  note: string
}

export interface CrewContext {
  crewId: string
  displayName: string
  pronouns: string
  agency: string
  languages: string[]
  greeting: string
  tone: 'direct' | 'warm' | 'technical'
  density: 'compact' | 'comfortable' | 'detailed'
  baseline: ContextBaseline
  /** Known conditions and habits that change how readings are read. Shown only to the crew member. */
  particularities: string[]
  /** What the assistant watches more closely for this person. */
  watchlist: string[]
  training: Record<'gym' | 'centrifuge' | 'swimming' | 'simulations' | 'communication', TrainingSkill>
  /** How this person reacts under stress, and the early sign of it. */
  stressSigns: string
  learned: LearnedMonth[]
  wellbeing: WellbeingMonth[]
  chatSuggestions: string[]
  /** Activities, music and books that help this person recover: the companion's suggestions. */
  comfort: { activities: string[]; music: string[]; books: string[] }
  /** What the person likes, from their profile (not private): the personal space is arranged from it. */
  tastes: CrewTastes
  /** Only with consent (the polaroid was authorised), and only people marked as featurable. */
  lovedOnes: { id: string; name: string; relation: string }[]
  /**
   * Guidance for the assistant only: never rendered. How the person reports symptoms, topics not to raise
   * unprompted, and the nudges the assistant may use.
   */
  assistant: { reportingStyle: string; avoidTopics: string[]; nudges: string[] }
}

/** Mission phase from the mission day of the central: no day (or day 0) is still before launch. */
export function missionPhase(missionDay: number | null): MissionPhase {
  return missionDay !== null && missionDay > 0 ? 'flight' : 'preflight'
}

/**
 * How the station senses and keeps data, the same for every crew member: presence and breathing by passive
 * Wi-Fi sensing (CSI), camera off, everything on the local network, data scoped to the active crew member.
 */
export const STATION_PRIVACY = {
  sensing: 'rfPassive',
  camera: 'off',
  network: 'localOnly',
  isolation: 'perCrew',
} as const
