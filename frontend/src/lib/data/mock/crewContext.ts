import type { CrewContext } from '@/lib/model/crewContext'
import { CREW_LORE, PROGRAM, type CrewId } from './crewLore'

function isCrewId(crewId: string): crewId is CrewId {
  return crewId in CREW_LORE
}

/**
 * The crew member's context, from the lore. Consent is applied here, once: private identity fields are left
 * out, and loved ones appear only when the crew member authorised the polaroid.
 */
export function buildCrewContext(crewId: string): CrewContext {
  if (!isCrewId(crewId)) throw new Error(`no crew context for ${crewId}`)
  const lore = CREW_LORE[crewId]
  const { identity, medical, training, tastes, ui } = lore
  const phaseOf = (month: number) => PROGRAM.find((entry) => entry.month === month)?.phase ?? ''

  return {
    crewId,
    displayName: identity.displayName,
    pronouns: identity.pronouns,
    agency: identity.agency,
    languages: identity.languages,
    greeting: ui.greeting,
    tone: ui.tone,
    density: ui.density,
    baseline: {
      hrBpm: medical.baseline_hr_bpm,
      hrvMs: medical.baseline_hrv_ms,
      respBpm: medical.baseline_resp_bpm,
      bpSys: medical.baseline_bp_sys,
      bpDia: medical.baseline_bp_dia,
      sleepH: medical.baseline_sleep_h,
      bloodType: medical.blood_type,
    },
    particularities: medical.particularities,
    watchlist: medical.watchlist,
    training: {
      gym: { rating: training.gym.rating, note: training.gym.style },
      centrifuge: training.centrifuge,
      swimming: training.swimming,
      simulations: training.simulations,
      communication: training.communication,
    },
    stressSigns: training.stressResponse,
    learned: lore.timeline.map((entry) => ({
      month: entry.month,
      period: entry.period,
      phase: phaseOf(entry.month),
      title: entry.title,
      notes: entry.aiNotes,
    })),
    wellbeing: lore.timeline.map((entry) => ({
      month: entry.month,
      period: entry.period,
      mood: entry.wellbeing.mood,
      sleepH: entry.wellbeing.sleepH,
      stress: entry.wellbeing.stress,
    })),
    chatSuggestions: ui.chatSuggestions,
    comfort: { activities: tastes.spaceActivities, music: tastes.music, books: tastes.books },
    // Food is left out: it carries health notes (intolerances), which belong to the clinical side.
    tastes: {
      hobbies: tastes.hobbies,
      games: tastes.games,
      gameGenres: tastes.gameGenres,
      books: tastes.books,
      bookGenres: tastes.bookGenres,
      music: tastes.music,
      musicGenres: tastes.musicGenres,
      films: tastes.films,
      filmGenres: tastes.filmGenres,
    },
    lovedOnes: ui.polaroid.enabled
      ? lore.lovedOnes.filter((person) => person.featurable).map(({ id, name, relation }) => ({ id, name, relation }))
      : [],
    assistant: { reportingStyle: medical.reportingStyle, avoidTopics: tastes.avoidTopics, nudges: ui.nudges },
  }
}
