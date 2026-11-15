export type CrewRole = 'COMMANDER' | 'FLIGHT_ENGINEER' | 'FLIGHT_SURGEON' | 'MISSION_SPECIALIST' | 'CMO'

/** What a crew member has opted in to share with the rest of the crew. Empty = nothing. */
export type ShareScope = 'activity' | 'garden'

/** Countries with a reference male height (see `stature.ts`). */
export type Nationality = 'BR' | 'JP' | 'US' | 'SN' | 'PL'

export interface CrewMember {
  crewId: string
  fullName: string
  role: CrewRole
  accent: string
  /** Skin colour of the digital twin (CSS hex). Personal data: never leaves the device. */
  skinTone: string
  shares: ShareScope[]
  /** Personal data: drives the stature of the digital twin. Never leaves the device. */
  nationality: Nationality
  /** Mission day from the central (`GET /api/crew`). Null when the central sends none. */
  missionDay: number | null
  /** The central asks for a calibration before this member's baseline is used. */
  calibrationRequired: boolean
}
