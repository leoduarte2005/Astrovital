/** Behaviour of the crew avatars in the training hangar: pure planning, no rendering. */
export { buildDay, blockAt } from './schedule'
export { DAY_STEP, MINUTES_PER_DAY, SIM_DAY_MS, TRAINING_MONTHS, dateOf, daysInMonth, periodOf, shownDays, simTimeAt } from './clock'
export { ROUTINES } from './profiles'
export { WAYPOINTS, WAYPOINT_BY_ID } from './waypoints'
export type { Waypoint } from './waypoints'
export type { Activity, Block, DayPlan, WaypointZone } from './types'
