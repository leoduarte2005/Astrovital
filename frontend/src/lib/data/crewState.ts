import { useStore } from 'zustand'
import { createStore } from 'zustand/vanilla'
import type { MissionMode } from '@/lib/model/live'
import { sessionStore } from './session'

interface CrewStateStore {
  /** Crew confirmed by the central (`CREW_STATE`), or by the mock on switch. */
  crewId: string | null
  missionMode: MissionMode | null
  /** The central refused the switch (`ERROR` `SET_CREW_ERROR`). */
  switchFailed: boolean
  confirm: (crewId: string | null, missionMode: MissionMode | null) => void
  fail: () => void
  clearFailure: () => void
  reset: () => void
}

/** Crew confirmed by the central. The home shows a loading state until it matches the active crew. */
export const crewStateStore = createStore<CrewStateStore>((set) => ({
  crewId: null,
  missionMode: null,
  switchFailed: false,
  confirm: (crewId, missionMode) => set({ crewId, missionMode, switchFailed: false }),
  fail: () => set({ switchFailed: true }),
  clearFailure: () => set({ switchFailed: false }),
  reset: () => set({ crewId: null, missionMode: null, switchFailed: false }),
}))

// Hot-swap isolation: a different crew member starts unconfirmed.
sessionStore.subscribe((state, previous) => {
  if (state.activeCrew?.crewId !== previous.activeCrew?.crewId) crewStateStore.getState().reset()
})

export function useCrewState<T>(selector: (state: CrewStateStore) => T): T {
  return useStore(crewStateStore, selector)
}
