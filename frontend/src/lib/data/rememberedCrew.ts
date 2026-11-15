import { getDataSource } from './index'
import { sessionStore } from './session'

/**
 * The last crew member chosen on this device, so a reload goes back to the same member without the crew
 * page. Only the `crew_id` is stored: name, nationality and sharing come from the data source each time
 * (rules/offline-and-privacy.md). Every storage access is guarded: private windows and blocked storage
 * simply mean there is nothing to restore.
 */
const KEY = 'edge-space:crew-id'
/** Startup never waits longer than this for the crew list. */
const RESTORE_TIMEOUT_MS = 3000

export function rememberCrew(crewId: string): void {
  try {
    localStorage.setItem(KEY, crewId)
  } catch {
    // Storage unavailable: the choice is simply not remembered.
  }
}

function readRememberedCrewId(): string | null {
  try {
    return localStorage.getItem(KEY)
  } catch {
    return null
  }
}

/** Selects the remembered member again. Silent on failure: the app then asks for a crew member as usual. */
export async function restoreRememberedCrew(): Promise<void> {
  const crewId = readRememberedCrewId()
  if (!crewId || sessionStore.getState().activeCrew) return
  let timer: number | undefined
  const timeout = new Promise<null>((resolve) => {
    timer = window.setTimeout(() => resolve(null), RESTORE_TIMEOUT_MS)
  })
  try {
    const crew = await Promise.race([getDataSource().listCrew(), timeout])
    const member = crew?.find((candidate) => candidate.crewId === crewId)
    if (member) sessionStore.getState().select(member)
  } catch (error) {
    console.warn('remembered crew not restored', error)
  } finally {
    window.clearTimeout(timer)
  }
}
