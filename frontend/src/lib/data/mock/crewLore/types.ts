/**
 * Astro Vital — lore dos tripulantes (MOCK, FICTÍCIO).
 *
 * Tudo aqui é inventado para a fase de mock. Nenhum dado corresponde a pessoa real.
 * A lore alimenta três consumidores:
 *   1. a simulação do galpão de treino (avatares nos 24 meses antes do lançamento);
 *   2. o contexto individual da IA a bordo (Contrato 1, campo `particularities`);
 *   3. a personalização da UI (polaroid, filtros de conteúdo, sugestões no chat).
 *
 * Privacidade (rules/offline-and-privacy.md): campos marcados como `Private<T>` só podem ser
 * exibidos com consentimento explícito do tripulante (ver `consent`). Orientação sexual
 * e notas de saúde NUNCA mudam limiares clínicos nem aparecem fora do perfil do próprio
 * tripulante.
 */

export type CrewId = 'crew_001' | 'crew_002' | 'crew_003'

/** Período de treino: M01 = 2024-10 … M24 = 2026-09. Lançamento em 2026-10-05 (dia de missão 1). */
export type TrainingMonth =
  | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12
  | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 | 21 | 22 | 23 | 24

/** Zonas do galpão de treino usadas pela simulação de avatares. */
export type HangarZone =
  | 'gym'            // academia ASCR (força, remo, esteira)
  | 'pool_nbl'       // piscina de flutuabilidade neutra (EVA)
  | 'centrifuge'     // centrífuga (perfis de lançamento e reentrada)
  | 'sim_cockpit'    // simulador da cabine
  | 'robotics_bay'   // estação do braço robótico
  | 'classroom'      // aulas de sistemas
  | 'medbay'         // treino médico cruzado
  | 'garden_lab'     // laboratório de cultivo
  | 'mess'           // refeitório
  | 'lounge'         // sala de convivência
  | 'comms_desk'     // mesa de rádio e comunicação com atraso
  | 'workshop'       // oficina e bancada
  | 'quarters'       // alojamento

/** Dado sensível: só aparece na UI se `visibleInUi` for true por consentimento. */
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
  /** Pode aparecer na polaroid ou em lembretes, se o consentimento permitir. */
  featurable: boolean
}

export interface Identity {
  givenName: string
  familyName: string
  displayName: string        // igual ao `fullName` da API
  pronouns: string
  birthDate: string          // ISO
  ageAtLaunch: number
  birthplace: string
  nationality: string        // ISO 3166-1 alfa-2, igual à API
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
  /** Atividades possíveis a bordo que combinam com o tripulante. */
  spaceActivities: string[]
  /** Temas que a IA não deve puxar por conta própria. */
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

/** Base clínica individual, no formato do Contrato 1 (CONTEXT_SWITCH). */
export interface MedicalBaseline {
  baseline_hr_bpm: number
  baseline_hrv_ms: number
  baseline_resp_bpm: number
  baseline_bp_sys: number
  baseline_bp_dia: number
  baseline_sleep_h: number
  blood_type: string
  particularities: string[]
  /** Como o tripulante tende a relatar sintomas; orienta a IA, não o diagnóstico. */
  reportingStyle: string
  watchlist: string[]
}

export interface AvatarBehavior {
  preferredZones: HangarZone[]
  /** 0 = sempre sozinho, 1 = sempre em grupo. */
  sociability: number
  /** Distância de conversa preferida, em metros. */
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
    /** Caminho servido em /media/ (fora do build). No mock, placeholder anônimo. */
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
  period: string            // AAAA-MM
  title: string
  narrative: string
  interactions: Interaction[]
  /** 0–100; ausente quando a atividade não foi avaliada no mês. */
  performance: Partial<Record<'gym' | 'centrifuge' | 'pool' | 'simulations' | 'social', number>>
  wellbeing: { mood: Rating; sleepH: number; stress: number }
  /** Peso relativo de tempo por zona no mês (soma ≈ 1), para a simulação. */
  zones: Partial<Record<HangarZone, number>>
  /** O que a IA aprendeu no mês. Vira `crew_ai_memory` no mock. */
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
