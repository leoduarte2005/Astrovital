import { useStore } from 'zustand'
import { createStore } from 'zustand/vanilla'
import type { ChatReplyPayload, Escalation } from '@/lib/model/live'
import { getDataSource } from './index'
import { sessionStore } from './session'

/** What the assistant's reply carries besides its text: shown as the report rows of the clinical log. */
export interface ChatReplyDetail {
  /** Sensor readings the reply rests on, as the central words them. */
  evidence: string[]
  countermeasures: string[]
  sources: string[]
  escalation: Escalation
  disclaimer: string
}

export interface ChatMessage {
  id: number
  role: 'user' | 'assistant'
  text: string
  /** Epoch ms when the entry was added. */
  at: number
  /** Assistant replies only. */
  reply?: ChatReplyDetail
}

function detailOf(reply: ChatReplyPayload): ChatReplyDetail {
  return {
    evidence: reply.evidence,
    countermeasures: reply.countermeasures,
    sources: reply.source_ids,
    escalation: reply.escalation,
    disclaimer: reply.disclaimer,
  }
}

interface ChatState {
  messages: ChatMessage[]
  /** Id of the message waiting for the central's reply, or null. While set, sending is blocked. */
  pendingId: number | null
  /** Adds the user's message. The reply is the `text` of the central, or of the simulated central (mock). */
  send: (text: string) => void
  reset: () => void
}

let nextId = 1

/**
 * Sends the message to the central (`CHAT_MSG`). The reply's `text` becomes the assistant's message, shown
 * only while the same crew member is active. A failed message adds no assistant text: nothing is invented.
 * The reply is also logged to the console.
 */
async function askCentral(text: string, crewId: string, messageId: number): Promise<void> {
  try {
    const reply = await getDataSource().sendChat(text, crewId)
    console.log('[chat] CHAT_REPLY', reply)
    if (sessionStore.getState().activeCrew?.crewId !== crewId) return
    const message: ChatMessage = { id: nextId++, role: 'assistant', text: reply.text, at: Date.now(), reply: detailOf(reply) }
    chatStore.setState({ messages: [...chatStore.getState().messages, message] })
  } catch (error) {
    console.warn('[chat] not answered by the central', error)
  } finally {
    // Only the message that is still pending releases the input: a late answer from another crew does not.
    if (chatStore.getState().pendingId === messageId) chatStore.setState({ pendingId: null })
  }
}

/** Conversation of the active crew member. Cleared on crew change (hot-swap isolation). */
export const chatStore = createStore<ChatState>((set, get) => ({
  messages: [],
  pendingId: null,
  send: (text) => {
    const clean = text.trim()
    console.log('[chat:diag] store.send', { length: clean.length, pendingId: get().pendingId, crew: sessionStore.getState().activeCrew?.crewId ?? null })
    if (!clean || get().pendingId !== null) return
    const user: ChatMessage = { id: nextId++, role: 'user', text: clean, at: Date.now() }
    set({ messages: [...get().messages, user] })
    const crewId = sessionStore.getState().activeCrew?.crewId
    if (!crewId) return
    set({ pendingId: user.id })
    void askCentral(clean, crewId, user.id)
  },
  reset: () => set({ messages: [], pendingId: null }),
}))

sessionStore.subscribe((state, previous) => {
  if (state.activeCrew?.crewId !== previous.activeCrew?.crewId) chatStore.getState().reset()
})

export function useChat<T>(selector: (state: ChatState) => T): T {
  return useStore(chatStore, selector)
}
