import { useStore } from 'zustand'
import { createStore } from 'zustand/vanilla'

export type ConnectionState = 'connecting' | 'live' | 'offline'

interface ConnectionStatusState {
  state: ConnectionState
}

/** Link to the central. Written by LiveSource only; the UI reads it through `useConnection`. */
export const connectionStore = createStore<ConnectionStatusState>(() => ({ state: 'offline' }))

export function useConnection<T>(selector: (state: ConnectionStatusState) => T): T {
  return useStore(connectionStore, selector)
}
