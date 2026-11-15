import type { CrewId } from '@/lib/data/mock/crewLore'
import { hm } from './clock'
import type { Activity, WaypointZone } from './types'

/**
 * Personal routines of each crew member, from the lore (`lib/data/mock/crewLore`): avatar behaviour, training profile,
 * tastes and stress responses. Only non-private fields are used here: no relationships, loved ones or notes.
 * The shared programme (work hours by month zone weights), pair sessions and month events are laid over these by
 * `schedule.ts`.
 */

/** A month counts as stressful for the routines at this stress score (0–100) or above. */
export const STRESS_HIGH = 55

export interface DayContext {
  monthIndex: number
  dayIndex: number
  /** 0 Sunday .. 6 Saturday. */
  weekday: number
  weekend: boolean
  /** Stress of the month at or above `STRESS_HIGH`. */
  stressed: boolean
  /** Eats and spends the free time apart (a month event or stress with low sociability). */
  withdrawn: boolean
  /** Minutes: the crew member goes to sleep (from the month's sleep hours and the wake-up time). */
  bedtime: number
}

export interface Slot {
  from: number
  to: number
  zone: WaypointZone
  activity: Activity
}

export interface CrewRoutine {
  /** Wake-up time on working days. */
  wake: number
  /** Wake-up time on weekends. */
  weekendWake: number
  /** Walking pace, for the renderer (lore `walkSpeed`). */
  walkSpeed: 'slow' | 'normal' | 'brisk'
  /** Personal slots of the day: meals, mornings, evenings and weekends. Work hours are added by the schedule. */
  day(ctx: DayContext): Slot[]
}

const slot = (from: number, to: number, zone: WaypointZone, activity: Activity): Slot => ({ from, to, zone, activity })

/** Month 11 (index 10): the ham radio club; from then on the radio desk is his corner in the breaks. */
const RADIO_FROM_MONTH = 10

/**
 * crew_001, Cmdr. Silva. Arrives early, brisk pace, sleeps little (about 6.5 h). Makes coffee for the group, rows (hates
 * the treadmill), stops to talk with anyone on the way. From month 11, the radio desk in the breaks. River swimmer:
 * the pool is his comfort zone, so Saturday mornings are in the pool. Cooks the group's Sunday dinner. Under stress he
 * trains more.
 */
const SILVA: CrewRoutine = {
  wake: hm(5, 45),
  weekendWake: hm(5, 45),
  walkSpeed: 'brisk',
  day(ctx) {
    const radio = ctx.monthIndex >= RADIO_FROM_MONTH
    const breakSpot = (from: number, to: number) =>
      radio ? slot(from, to, 'comms_desk', 'radio') : slot(from, to, 'lounge', 'social')
    const evening = [slot(hm(19), hm(20), 'mess', 'dinner'), slot(hm(20), ctx.bedtime - 30, 'lounge', 'social'), slot(ctx.bedtime - 30, ctx.bedtime, 'quarters', 'desk')]
    if (!ctx.weekend) {
      return [
        slot(hm(5, 45), hm(6, 15), 'mess', 'coffee'),
        slot(hm(6, 15), hm(7), 'gym', 'exercise'),
        slot(hm(7), hm(7, 30), 'mess', 'breakfast'),
        breakSpot(hm(7, 30), hm(8)),
        slot(hm(12), hm(13), 'mess', 'lunch'),
        ctx.stressed ? slot(hm(17, 30), hm(19), 'gym', 'exercise') : breakSpot(hm(17, 30), hm(19)),
        ...evening,
      ]
    }
    const sunday = ctx.weekday === 0
    return [
      slot(hm(5, 45), hm(6, 30), 'mess', 'coffee'),
      slot(hm(6, 30), hm(7, 30), 'gym', 'exercise'),
      slot(hm(7, 30), hm(8, 30), 'mess', 'breakfast'),
      ...(sunday ? [breakSpot(hm(8, 30), hm(12))] : [slot(hm(9), hm(10, 30), 'pool_nbl', 'swim'), breakSpot(hm(10, 30), hm(12))]),
      slot(hm(12), hm(13), 'mess', 'lunch'),
      breakSpot(hm(13), hm(15)),
      slot(hm(15), hm(17, 30), 'lounge', 'social'),
      sunday ? slot(hm(17, 30), hm(19), 'mess', 'cooking') : slot(hm(17, 30), hm(19), 'lounge', 'social'),
      ...evening,
    ]
  },
}

/**
 * crew_002, Dr. Costa. Arrives early; short gym sessions every day at 6 (running and cycling). Checks the medical panel
 * off shift, draws in the corner of the lounge, stops at the garden to look at the plants, plays the keyboard at night.
 * Under stress she stops playing and checks the others' data instead (lore `stressResponse`).
 */
const COSTA: CrewRoutine = {
  wake: hm(5, 30),
  weekendWake: hm(6, 30),
  walkSpeed: 'normal',
  day(ctx) {
    const night = [
      slot(hm(19), hm(20), 'mess', 'dinner'),
      slot(hm(20), hm(21), 'lounge', 'social'),
      ctx.stressed ? slot(hm(21), hm(21, 45), 'medbay', 'review') : slot(hm(21), hm(21, 45), 'quarters', 'piano'),
      slot(hm(21, 45), ctx.bedtime, 'quarters', 'desk'),
    ]
    if (!ctx.weekend) {
      return [
        slot(hm(6), hm(6, 45), 'gym', 'exercise'),
        slot(hm(7), hm(7, 30), 'mess', 'breakfast'),
        slot(hm(7, 30), hm(8), 'medbay', 'review'),
        slot(hm(12), hm(13), 'mess', 'lunch'),
        ctx.stressed ? slot(hm(17, 30), hm(18, 30), 'medbay', 'review') : slot(hm(17, 30), hm(18, 30), 'lounge', 'drawing'),
        slot(hm(18, 30), hm(19), 'garden_lab', 'plant_care'),
        ...night,
      ]
    }
    const sunday = ctx.weekday === 0
    return [
      slot(hm(7), hm(7, 45), 'gym', 'exercise'),
      slot(hm(7, 45), hm(8, 30), 'mess', 'breakfast'),
      slot(hm(8, 30), hm(10, 30), 'lounge', 'drawing'),
      slot(hm(10, 30), hm(12), 'garden_lab', 'plant_care'),
      slot(hm(12), hm(13), 'mess', 'lunch'),
      slot(hm(13), hm(15), 'lounge', 'social'),
      slot(hm(15), hm(17, 30), 'quarters', 'desk'),
      // Sunday: joins the group while Silva cooks.
      sunday ? slot(hm(17, 30), hm(19), 'mess', 'social') : slot(hm(17, 30), hm(19), 'lounge', 'drawing'),
      ...night,
    ]
  },
}

/**
 * crew_003, Eng. Sato. Does not arrive early. Measures the plants in the garden, works at the bench, trains alone at
 * 19:00 when the gym empties (bouldering). Watches from the wall before joining a conversation. Under stress, or when
 * withdrawn, he leaves the mess and eats alone (lore `stressResponse`), and trains more.
 */
const SATO: CrewRoutine = {
  wake: hm(7),
  weekendWake: hm(8),
  walkSpeed: 'normal',
  day(ctx) {
    const meal = (from: number, to: number, activity: 'breakfast' | 'lunch' | 'dinner'): Slot =>
      ctx.withdrawn ? slot(from, to, 'garden_lab', 'solo_meal') : slot(from, to, 'mess', activity)
    if (!ctx.weekend) {
      const tinkering = ctx.weekday === 2 || ctx.weekday === 4 ? slot(hm(17, 30), hm(19), 'workshop', 'bench_work') : slot(hm(17, 30), hm(19), 'garden_lab', 'plant_care')
      return [
        meal(hm(7, 15), hm(7, 45), 'breakfast'),
        slot(hm(7, 45), hm(8), 'garden_lab', 'plant_care'),
        meal(hm(12), hm(13), 'lunch'),
        ctx.stressed || ctx.withdrawn ? slot(hm(17, 30), hm(19), 'gym', 'exercise') : tinkering,
        slot(hm(19), hm(20), 'gym', 'exercise'),
        meal(hm(20), hm(20, 45), 'dinner'),
        slot(hm(20, 45), ctx.bedtime, 'quarters', 'desk'),
      ]
    }
    const sunday = ctx.weekday === 0
    return [
      meal(hm(8, 15), hm(8, 45), 'breakfast'),
      slot(hm(9), hm(11), 'garden_lab', 'plant_care'),
      slot(hm(11), hm(12), 'gym', 'exercise'),
      meal(hm(12), hm(13), 'lunch'),
      slot(hm(13), hm(17), 'workshop', 'bench_work'),
      sunday ? slot(hm(17), hm(19), 'garden_lab', 'plant_care') : slot(hm(17), hm(19), 'gym', 'exercise'),
      meal(hm(19), hm(20), 'dinner'),
      slot(hm(20), ctx.bedtime, 'quarters', 'desk'),
    ]
  },
}

export const ROUTINES: Record<CrewId, CrewRoutine> = {
  crew_001: SILVA,
  crew_002: COSTA,
  crew_003: SATO,
}
