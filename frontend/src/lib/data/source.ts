import type { CrewMember } from '@/lib/model/crew'
import type { ChatReplyPayload, Envelope } from '@/lib/model/live'
import type { BaselineMetricId, BaselineProfile, HistorySeries, HistoryWindow } from '@/lib/model/baseline'
import type { Book } from './mock/bookCatalog'

/** The only way the UI reads data. MockSource (default) and LiveSource (WebSocket, then HTTP) share this shape. */
export interface DataSource {
  /** 'mock': no central, the chat keeps its scripted replies. 'live': replies come from the central. */
  readonly kind: 'mock' | 'live'
  listCrew(): Promise<CrewMember[]>
  /** Receives every envelope of `type`, as sent. Returns the unsubscribe function. */
  subscribe(type: string, listener: (envelope: Envelope) => void): () => void
  /**
   * Takes a reference on the live link: it opens with the first consumer. Each call needs a matching
   * `close()`. The mock ignores it.
   */
  open(): void
  /** Releases a reference; the link closes with the last one. */
  close(): void
  /** Asks the central to switch to this crew member (`SET_CREW`). The result arrives in `crewStateStore`. */
  setCrew(crewId: string): void
  /** Books suggested for the crew member (leisure). The central does not provide them yet: mock data for now. */
  listBookSuggestions(crewId: string): Promise<Book[]>
  /** The crew member's baseline, learned from the 24 months before the mission. Mock until the central provides it (Leva 2). */
  getBaseline(crewId: string): Promise<BaselineProfile>
  /** One metric over one window, with the corridor of the baseline. Mock until the central provides it (Leva 2). */
  history(crewId: string, metric: BaselineMetricId, window: HistoryWindow): Promise<HistorySeries>
  /**
   * Heart rate (bpm) of one crew member, at each of its telemetry frames. Independent of the session and of
   * the home's link: live opens one link per crew member, closed with the last watcher. Returns the unsubscribe.
   */
  watchHeartRate(crewId: string, listener: (bpm: number) => void): () => void
  /** Sends a chat message (`CHAT_MSG`) for the crew member and resolves with the reply, or rejects. */
  sendChat(text: string, crewId: string): Promise<ChatReplyPayload>
}
