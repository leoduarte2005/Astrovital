import { SILVA } from './crew-001-silva'
import { COSTA } from './crew-002-costa'
import { SATO } from './crew-003-sato'
import type { CrewId, CrewLore, HangarZone, MonthEntry, TrainingMonth } from './types'

export * from './types'
export { CAST, PROGRAM, LAUNCH_DATE } from './program'

export const CREW_LORE: Record<CrewId, CrewLore> = {
  crew_001: SILVA,
  crew_002: COSTA,
  crew_003: SATO,
}

export function getLore(crewId: CrewId): CrewLore {
  return CREW_LORE[crewId]
}

export function getMonth(crewId: CrewId, month: TrainingMonth): MonthEntry {
  const entry = CREW_LORE[crewId].timeline.find((m) => m.month === month)
  if (!entry) throw new Error(`Mês ${month} ausente na lore de ${crewId}`)
  return entry
}

/** Payload no formato do Contrato 1 (CONTEXT_SWITCH) para o worker de IA. */
export function toContextSwitch(crewId: CrewId) {
  const lore = CREW_LORE[crewId]
  const m = lore.medical
  return {
    event: 'CONTEXT_SWITCH' as const,
    active_crew_id: crewId,
    profile: {
      full_name: lore.identity.displayName,
      baseline_hr_bpm: m.baseline_hr_bpm,
      baseline_resp_bpm: m.baseline_resp_bpm,
      baseline_bp_sys: m.baseline_bp_sys,
      baseline_bp_dia: m.baseline_bp_dia,
      particularities: m.particularities,
    },
  }
}

/** Linhas para `crew_ai_memory`, uma por nota mensal. */
export function toAiMemory(crewId: CrewId) {
  return CREW_LORE[crewId].timeline.flatMap((m) =>
    m.aiNotes.map((fact) => ({
      crew_id: crewId,
      category: 'habit' as const,
      fact_text: `[M${String(m.month).padStart(2, '0')} ${m.period}] ${fact}`,
      confidence: 1.0,
    })),
  )
}

/**
 * Visão segura para a UI: remove o que não tem consentimento.
 * Orientação sexual e estado civil nunca saem daqui; entes queridos só se a polaroid foi autorizada.
 */
export function toUiProfile(crewId: CrewId) {
  const lore = CREW_LORE[crewId]
  const consented = lore.ui.polaroid.enabled
  return {
    crewId,
    displayName: lore.identity.displayName,
    pronouns: lore.identity.pronouns,
    greeting: lore.ui.greeting,
    tone: lore.ui.tone,
    density: lore.ui.density,
    polaroid: consented ? lore.ui.polaroid : null,
    lovedOnes: consented ? lore.lovedOnes.filter((p) => p.featurable).map(({ id, name, relation }) => ({ id, name, relation })) : [],
    chatSuggestions: lore.ui.chatSuggestions,
    contentFilters: lore.ui.contentFilters,
    homeWidgets: lore.ui.homeWidgets,
  }
}

/** Sorteia uma zona do galpão conforme o peso do mês; `rand` deve vir do PRNG com seed do mock. */
export function pickZone(crewId: CrewId, month: TrainingMonth, rand: () => number): HangarZone {
  const zones = Object.entries(getMonth(crewId, month).zones) as [HangarZone, number][]
  const total = zones.reduce((s, [, w]) => s + w, 0)
  let r = rand() * total
  for (const [zone, w] of zones) {
    r -= w
    if (r <= 0) return zone
  }
  const last = zones[zones.length - 1]
  if (!last) throw new Error(`Mês ${month} sem zonas na lore de ${crewId}`)
  return last[0]
}
