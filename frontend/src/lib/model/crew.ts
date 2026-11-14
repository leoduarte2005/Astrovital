export type CrewRole = 'COMMANDER' | 'FLIGHT_ENGINEER' | 'MISSION_SPECIALIST' | 'CMO'

/** What a crew member has opted in to share with the rest of the crew. Empty = nothing. */
export type ShareScope = 'activity' | 'garden'

export interface CrewMember {
  crewId: string
  fullName: string
  role: CrewRole
  accent: string
  /** Skin colour of the digital twin (CSS hex). Personal data: never leaves the device. */
  skinTone: string
  shares: ShareScope[]
}
