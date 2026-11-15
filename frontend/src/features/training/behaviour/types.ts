import type { CrewId, HangarZone } from '@/lib/data/mock/crewLore'

/**
 * Zones of the hangar GLB: the lore's `HangarZone`, plus two that only the GLB has. `lunar_surface` is the GLB's alias
 * of `workshop`, used for field geology (month 9); `thermal_vac` is decorative and never planned.
 */
export type WaypointZone = HangarZone | 'lunar_surface' | 'thermal_vac'

/** What a crew member is doing in a block. Labels for the planner and the renderer, not shown text. */
export type Activity =
  | 'sleep'
  | 'desk' // own quarters, desk
  | 'piano' // own quarters (crew_002 only, where the GLB has the keyboard)
  | 'breakfast'
  | 'lunch'
  | 'dinner'
  | 'solo_meal' // eats apart (withdrawal)
  | 'coffee' // prepares coffee for the group (mess station)
  | 'cooking' // Sunday dinner for the group (mess station)
  | 'training' // the month's programme, in the zone the month weights choose
  | 'staff_session' // session with a staff member of the programme (mentor, instructor, psychologist)
  | 'exercise' // personal gym session, on the crew member's favoured equipment
  | 'swim'
  | 'radio'
  | 'chess'
  | 'drawing'
  | 'plant_care'
  | 'bench_work'
  | 'tutoring'
  | 'social'
  | 'review' // checks the medical panel off shift
  | 'away' // out of the hangar (leave); the avatar is hidden

export interface Block {
  /** Minutes from 00:00 of the simulated day, inclusive. */
  from: number
  /** Minutes, exclusive (up to 1440). */
  to: number
  /** Null only when `activity` is `away`. */
  zone: WaypointZone | null
  /** Waypoint id of the GLB (`WP_*`); null only when away. The avatar walks there from `from`. */
  waypoint: string | null
  activity: Activity
  /** Crew members in the same zone at an overlapping time (not while sleeping or away). */
  with: CrewId[]
}

export interface DayPlan {
  /** 0..23: month 1 (2024-10) to month 24 (2026-09). */
  monthIndex: number
  /** 0..(days of the month - 1). */
  dayIndex: number
  /** ISO date of the day. */
  date: string
  /** 0 Sunday .. 6 Saturday. */
  weekday: number
  /** The whole day of each crew member: blocks in order, covering 0..1440 without gaps. */
  crew: Record<CrewId, Block[]>
}
