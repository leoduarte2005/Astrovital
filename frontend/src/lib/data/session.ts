import { useStore } from 'zustand'
import { createStore } from 'zustand/vanilla'
import type { CrewMember } from '@/lib/model/crew'

interface SessionState {
  activeCrew: CrewMember | null
  select: (member: CrewMember) => void
  leave: () => void
}

/** Active crew member. Per-crew stores must reset when this changes (hot-swap isolation). */
export const sessionStore = createStore<SessionState>((set) => ({
  activeCrew: null,
  select: (member) => set({ activeCrew: member }),
  leave: () => set({ activeCrew: null }),
}))

export function useSession<T>(selector: (state: SessionState) => T): T {
  return useStore(sessionStore, selector)
}
