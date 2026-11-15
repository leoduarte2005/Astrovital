import type { CastId, CrewId } from '@/lib/data/mock/crewLore'
import { daysInMonth, dateOf, hm } from './clock'
import type { Activity, WaypointZone } from './types'

/**
 * Month events from the lore narratives (`MonthEntry.narrative`), as overlays on the routines. Month numbers in the
 * comments are the lore's (1 = 2024-10); indices in code are 0-based. Absences say only that the crew member is out of
 * the hangar, never why (the reasons are personal).
 */

export interface Overlay {
  crew: readonly CrewId[]
  from: number
  to: number
  zone: WaypointZone
  activity: Activity
}

/** Day index of the n-th (1-based) weekday of a training month, or -1. */
function nthWeekday(monthIndex: number, weekday: number, n: number): number {
  let seen = 0
  for (let day = 0; day < daysInMonth(monthIndex); day++) {
    if (dateOf(monthIndex, day).weekday === weekday && ++seen === n) return day
  }
  return -1
}

const range = (from: number, to: number): number[] => Array.from({ length: to - from + 1 }, (_, i) => from + i)

/** Days out of the hangar, by month index. */
const AWAY: Partial<Record<CrewId, Partial<Record<number, readonly number[]>>>> = {
  // Month 15: Silva five days in Belém; Sato Christmas in Portland; Costa New Year with her parents.
  crew_001: { 14: range(20, 24) },
  crew_002: { 10: range(11, 13), 14: range(26, 30) }, // month 11: three days off
  crew_003: { 10: [15, 16], 14: range(22, 26) }, // month 11: a weekend away
}

/** Withdrawal: eats apart and trains alone. Month 10 from the third week; month 18 for one week. */
const WITHDRAWN: Partial<Record<CrewId, Partial<Record<number, (day: number) => boolean>>>> = {
  crew_003: { 9: (day) => day >= 14, 17: (day) => day <= 6 },
}

export function isAway(crewId: CrewId, monthIndex: number, dayIndex: number): boolean {
  return AWAY[crewId]?.[monthIndex]?.includes(dayIndex) ?? false
}

/**
 * The narrative's own withdrawal rule for this crew member and month, if it has one. When it exists it wins over the
 * generic stress rule (month 18: stress is high all month, but the narrative says one week).
 */
export function withdrawalOfMonth(crewId: CrewId, monthIndex: number): ((dayIndex: number) => boolean) | undefined {
  return WITHDRAWN[crewId]?.[monthIndex]
}

/** Month 9: field geology happens on the lunar surface (the GLB's alias of the workshop). */
export function trainingZone(monthIndex: number, zone: WaypointZone): WaypointZone {
  return monthIndex === 8 && zone === 'workshop' ? 'lunar_surface' : zone
}

/** Where a staff member of the programme works with the crew (from their role in `program.ts`). */
export const STAFF_ZONE: Record<CastId, WaypointZone> = {
  okafor: 'classroom',
  lindqvist: 'medbay',
  ramirez: 'gym',
  haddad: 'comms_desk', // CAPCOM of the delayed-communication sims
  kowalski: 'comms_desk', // ham radio
  iyer: 'lounge', // behavioural health sessions
  walsh: 'pool_nbl',
  beaumont: 'gym',
  nguyen: 'sim_cockpit',
}

/** Shared moments of the narratives, for one day. */
export function dayOverlays(monthIndex: number, dayIndex: number, weekday: number): Overlay[] {
  const out: Overlay[] = []
  const both = ['crew_001', 'crew_003'] as const
  // Month 2: Sato tutors Silva on life support at the mess whiteboard, Tuesdays and Thursdays after hours.
  if (monthIndex === 1 && (weekday === 2 || weekday === 4)) {
    out.push({ crew: both, from: hm(20), to: hm(21), zone: 'mess', activity: 'tutoring' })
  }
  // Month 5: in the first week, Silva reviews the anti-G technique with Costa in the evening.
  if (monthIndex === 4 && dayIndex <= 6 && weekday >= 1 && weekday <= 5) {
    out.push({ crew: ['crew_001', 'crew_002'], from: hm(20), to: hm(21), zone: 'classroom', activity: 'tutoring' })
  }
  // Month 18: mediation with the behavioural health psychologist, after the week of withdrawal.
  if (monthIndex === 17 && dayIndex === 7) {
    out.push({ crew: ['crew_001', 'crew_002', 'crew_003'], from: hm(10), to: hm(11, 30), zone: 'lounge', activity: 'staff_session' })
  }
  // Month 21: family day in the hangar, on the second Saturday (the families themselves are not shown).
  if (monthIndex === 20 && dayIndex === nthWeekday(monthIndex, 6, 2)) {
    const all = ['crew_001', 'crew_002', 'crew_003'] as const
    out.push({ crew: all, from: hm(13), to: hm(16), zone: 'lounge', activity: 'social' })
    out.push({ crew: all, from: hm(16), to: hm(18), zone: 'garden_lab', activity: 'social' })
  }
  // Month 24: chess every night in quarantine; the last day, Silva and Costa cook the last dinner together.
  if (monthIndex === 23) {
    out.push({ crew: both, from: hm(20, 45), to: hm(21, 45), zone: 'lounge', activity: 'chess' })
    if (dayIndex === daysInMonth(monthIndex) - 1) {
      out.push({ crew: ['crew_001', 'crew_002'], from: hm(17, 30), to: hm(19), zone: 'mess', activity: 'cooking' })
    }
  }
  return out
}
