import type { CastId, CrewId, CrewLore, InteractionKind, MonthEntry } from '@/lib/data/mock/crewLore'
import { dateOf, daysInMonth, hm, MINUTES_PER_DAY, TRAINING_MONTHS } from './clock'
import { STAFF_ZONE, dayOverlays, isAway, trainingZone, withdrawalOfMonth } from './events'
import { ROUTINES, STRESS_HIGH, type DayContext, type Slot } from './profiles'
import type { Activity, Block, DayPlan, WaypointZone } from './types'
import { WAYPOINTS, type Waypoint } from './waypoints'

/**
 * The day planner of the training hangar. `buildDay(lore, month, day)` is pure and deterministic: the same month and
 * day always give the same plan, so the month can loop. It lays, in order (each layer over the previous one):
 *   1. sleep, from the month's sleep hours (`wellbeing.sleepH`) and the routine's wake-up time;
 *   2. the personal routine (`profiles.ts`);
 *   3. on weekdays, the programme: 08:00–12:00 and 13:00–18:00 split in half hours by the month's zone weights
 *      (`MonthEntry.zones`, without mess, quarters and lounge, which the routines already cover). Zones follow one
 *      order shared by the crew that day, so people with the same zone meet there; pairs with teamwork, mentoring or
 *      support that month start the day in their common zone on Mondays, Wednesdays and Fridays; on Mondays an extra
 *      practice hour (18:00–19:00) in the month's main zone keeps the month weights closer to the lore;
 *   4. a Wednesday session with the month's staff member (mentor, instructor, psychologist);
 *   5. shared evenings for pairs with a bond or social interaction (Tuesdays and Thursdays), unless they are in friction;
 *   6. the month events of the narratives (`events.ts`), and absences.
 * Then each block gets a waypoint of the GLB: free at that time, the crew member's favoured one first, near or far
 * from the others by sociability, bonds and friction.
 * Uses only non-private lore fields: zones, interactions (kind and who, never the note), wellbeing, avatar behaviour.
 */

const CREW_ORDER: readonly CrewId[] = ['crew_001', 'crew_002', 'crew_003']
const CREW_SET: ReadonlySet<string> = new Set(CREW_ORDER)
const isCrewId = (id: string): id is CrewId => CREW_SET.has(id)

/** Weekday programme: two shifts in half-hour slots (8 + 10). */
const SHIFTS: readonly (readonly [number, number])[] = [
  [hm(8), hm(12)],
  [hm(13), hm(18)],
]
/** Monday: one extra hour of practice in the month's main programme zone (not when withdrawn). */
const EXTRA_PRACTICE_DAY = 1
const EXTRA_PRACTICE: readonly [number, number] = [hm(18), hm(19)]
const SLOT_MIN = 30
/** Zones of the month weights covered by the routines (meals, sleep, social time), not by the programme. */
const NOT_PROGRAMME: ReadonlySet<string> = new Set(['mess', 'quarters', 'lounge'])
const PAIR_WORK_DAYS: ReadonlySet<number> = new Set([1, 3, 5])
const PAIR_EVENING_DAYS: ReadonlySet<number> = new Set([2, 4])
const PAIR_EVENING: readonly [number, number] = [hm(20, 45), hm(21, 30)]
const STAFF_DAY = 3 // Wednesday
const STAFF_SESSION: readonly [number, number] = [hm(15), hm(16)]
/** Generic withdrawal (without a narrative rule): high stress and low sociability (lore `avatar.sociability`). */
const WITHDRAW_STRESS = 60
const WITHDRAW_SOCIABILITY = 0.5
const WORK_KINDS: ReadonlySet<InteractionKind> = new Set(['teamwork', 'mentoring', 'support'])
const EVENING_KINDS: ReadonlySet<InteractionKind> = new Set(['bond', 'social'])
/** Every zone, in a fixed base order; each day shuffles it once for the whole crew. */
const ZONE_BASE: readonly WaypointZone[] = [
  'gym', 'pool_nbl', 'centrifuge', 'sim_cockpit', 'robotics_bay', 'classroom', 'medbay',
  'garden_lab', 'comms_desk', 'workshop', 'lunar_surface', 'mess', 'lounge', 'quarters',
]

// ——— Deterministic randomness ———

function mulberry32(seed: number): () => number {
  let state = seed >>> 0
  return () => {
    state = (state + 0x6d2b79f5) >>> 0
    let t = state
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function seedOf(...parts: number[]): number {
  let hash = 2166136261
  for (const part of parts) {
    hash ^= part
    hash = Math.imul(hash, 16777619)
  }
  return hash >>> 0
}

function shuffled<T>(items: readonly T[], random: () => number): T[] {
  const out = [...items]
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(random() * (i + 1))
    const a = out[i] as T
    out[i] = out[j] as T
    out[j] = a
  }
  return out
}

// ——— Timeline painting ———

/** Paints `slot` over the timeline: what it covers is cut away. The result stays sorted and without overlaps. */
function paint(timeline: Slot[], slot: Slot): Slot[] {
  if (slot.to <= slot.from) return timeline
  const out: Slot[] = []
  for (const current of timeline) {
    if (current.to <= slot.from || current.from >= slot.to) {
      out.push(current)
      continue
    }
    if (current.from < slot.from) out.push({ ...current, to: slot.from })
    if (current.to > slot.to) out.push({ ...current, from: slot.to })
  }
  out.push(slot)
  return out.sort((a, b) => a.from - b.from)
}

/** Covers 0..1440: gaps extend the block before them; equal neighbours merge (no walk between them). */
function normalise(timeline: Slot[]): Slot[] {
  const sorted = timeline
    .map((s) => ({ ...s, from: Math.max(0, s.from), to: Math.min(MINUTES_PER_DAY, s.to) }))
    .filter((s) => s.to > s.from)
    .sort((a, b) => a.from - b.from)
  const out: Slot[] = []
  for (const s of sorted) {
    const last = out[out.length - 1]
    if (!last) {
      out.push({ ...s, from: 0 })
      continue
    }
    if (s.from > last.to) last.to = s.from
    if (last.zone === s.zone && last.activity === s.activity) last.to = s.to
    else out.push({ ...s, from: last.to })
  }
  const last = out[out.length - 1]
  if (last) last.to = MINUTES_PER_DAY
  return out
}

// ——— Month analysis ———

const pairKey = (a: CrewId, b: CrewId): string => (a < b ? `${a}|${b}` : `${b}|${a}`)

interface MonthPairs {
  /** Kinds of interaction of each crew pair this month (from both sides). */
  kinds: Map<string, Set<InteractionKind>>
}

function monthPairs(entries: ReadonlyMap<CrewId, MonthEntry>): MonthPairs {
  const kinds = new Map<string, Set<InteractionKind>>()
  for (const [crewId, entry] of entries) {
    for (const interaction of entry.interactions) {
      if (!isCrewId(interaction.with) || interaction.with === crewId) continue
      const key = pairKey(crewId, interaction.with)
      const set = kinds.get(key) ?? new Set<InteractionKind>()
      set.add(interaction.kind)
      kinds.set(key, set)
    }
  }
  return { kinds }
}

const hasAny = (set: Set<InteractionKind> | undefined, wanted: ReadonlySet<InteractionKind>): boolean =>
  !!set && [...set].some((kind) => wanted.has(kind))

const inFriction = (pairs: MonthPairs, a: CrewId, b: CrewId): boolean => pairs.kinds.get(pairKey(a, b))?.has('friction') ?? false

const bonded = (pairs: MonthPairs, a: CrewId, b: CrewId): boolean => {
  const set = pairs.kinds.get(pairKey(a, b))
  return !inFriction(pairs, a, b) && (hasAny(set, WORK_KINDS) || hasAny(set, EVENING_KINDS))
}

/** The first staff member the crew member works with this month, if any. */
function staffOf(entry: MonthEntry): CastId | null {
  for (const interaction of entry.interactions) {
    if (!isCrewId(interaction.with)) return interaction.with
  }
  return null
}

/** Half-hour counts per programme zone (largest remainder), from the month weights. */
function programmeCounts(entry: MonthEntry, monthIndex: number, slots: number): Map<WaypointZone, number> {
  const weights = (Object.entries(entry.zones) as [WaypointZone, number][])
    .filter(([zone, weight]) => !NOT_PROGRAMME.has(zone) && weight > 0)
    .map(([zone, weight]) => [trainingZone(monthIndex, zone), weight] as const)
  const counts = new Map<WaypointZone, number>()
  const total = weights.reduce((sum, [, weight]) => sum + weight, 0)
  if (total === 0) {
    counts.set('classroom', slots)
    return counts
  }
  const exact = weights.map(([zone, weight]) => ({ zone, value: (weight / total) * slots }))
  let given = 0
  for (const { zone, value } of exact) {
    counts.set(zone, (counts.get(zone) ?? 0) + Math.floor(value))
    given += Math.floor(value)
  }
  const byRemainder = [...exact].sort((a, b) => b.value - Math.floor(b.value) - (a.value - Math.floor(a.value)))
  for (let i = 0; given < slots; i++, given++) {
    const pick = byRemainder[i % byRemainder.length]
    if (pick) counts.set(pick.zone, (counts.get(pick.zone) ?? 0) + 1)
  }
  return counts
}

/** The weekday programme of one crew member, as slots. `first` opens the day (pair sessions). */
function programme(counts: Map<WaypointZone, number>, dayOrder: readonly WaypointZone[], first: WaypointZone | null): Slot[] {
  const order = [...counts.keys()].sort((a, b) => dayOrder.indexOf(a) - dayOrder.indexOf(b))
  if (first && order.includes(first)) {
    order.splice(order.indexOf(first), 1)
    order.unshift(first)
  }
  const sequence: WaypointZone[] = order.flatMap((zone) => Array<WaypointZone>(counts.get(zone) ?? 0).fill(zone))
  const out: Slot[] = []
  let index = 0
  for (const [start, end] of SHIFTS) {
    for (let t = start; t < end; t += SLOT_MIN, index++) {
      const zone = sequence[index] ?? sequence[sequence.length - 1] ?? 'classroom'
      out.push({ from: t, to: t + SLOT_MIN, zone, activity: 'training' })
    }
  }
  return out
}

/** The zone two crew members share most this month (by the smaller weight), if any. */
function sharedZone(a: Map<WaypointZone, number>, b: Map<WaypointZone, number>): WaypointZone | null {
  let best: WaypointZone | null = null
  let bestValue = 0
  for (const [zone, count] of a) {
    const value = Math.min(count, b.get(zone) ?? 0)
    if (value > bestValue) {
      best = zone
      bestValue = value
    }
  }
  return best
}

// ——— Waypoints ———

const EXERCISE_EQUIPMENT: ReadonlySet<string> = new Set(['rowing', 'running', 'cycling', 'bouldering', 'strength'])
const isSeat = (w: Waypoint) => w.kind === 'seat'
const ACTIVITY_MATCH: Partial<Record<Activity, (w: Waypoint) => boolean>> = {
  coffee: (w) => w.role === 'coffee',
  cooking: (w) => w.role === 'coffee',
  breakfast: isSeat,
  lunch: isSeat,
  dinner: isSeat,
  solo_meal: isSeat,
  tutoring: isSeat,
  social: isSeat,
  drawing: isSeat,
  chess: (w) => w.activity === 'chess',
  swim: (w) => w.activity === 'dive_entry' || w.activity === 'eva_underwater',
  plant_care: (w) => w.activity === 'plant_care',
  radio: (w) => w.activity === 'ham_radio',
  review: (w) => w.role === 'point_of_care' || w.role === 'medic',
  bench_work: (w) => w.activity === 'bench_work',
  exercise: (w) => w.activity !== undefined && EXERCISE_EQUIPMENT.has(w.activity),
}

/** Points of the programme's staff (instructors): never taken by the crew. */
const STAFF_ROLES: ReadonlySet<string> = new Set(['instructor', 'dive_instructor'])

/**
 * Every point of a zone the crew member may use: not staff points or other people's quarters. Entries and queues only
 * with `waiting`: there the crew member waits a turn (the centrifuge and the robotic arm have two places each).
 */
function usableIn(zone: WaypointZone, crewId: CrewId, waiting = false): Waypoint[] {
  return WAYPOINTS.filter(
    (w) =>
      w.zone === zone &&
      (waiting || (w.kind !== 'entry' && w.kind !== 'queue')) &&
      !(w.role && STAFF_ROLES.has(w.role)) &&
      (!w.crewId || w.crewId === crewId),
  )
}

/** Waypoints that fit an activity in a zone. Private quarters points belong to their owner only. */
function candidatesFor(zone: WaypointZone, activity: Activity, crewId: CrewId): Waypoint[] {
  const inZone = usableIn(zone, crewId)
  if (zone === 'quarters') {
    const own = inZone.filter((w) => w.crewId === crewId)
    const want = activity === 'sleep' ? 'sleep' : activity === 'piano' ? 'piano' : 'desk'
    const exact = own.filter((w) => w.activity === want)
    return exact.length ? exact : own.length ? own : inZone
  }
  const match = ACTIVITY_MATCH[activity]
  const matched = match ? inZone.filter(match) : inZone
  return matched.length ? matched : inZone
}

const distance = (a: Waypoint, b: Waypoint): number => Math.hypot(a.x - b.x, a.z - b.z) + Math.abs(a.y - b.y) * 4

interface Placed {
  crewId: CrewId
  slot: Slot
  waypoint: Waypoint | null
}

const overlaps = (a: { from: number; to: number }, b: { from: number; to: number }): boolean => a.from < b.to && b.from < a.to

/** Chooses each block's waypoint, in time order across the crew, so later choices see the earlier ones. */
function placeAll(timelines: ReadonlyMap<CrewId, Slot[]>, lore: ReadonlyMap<CrewId, CrewLore>, pairs: MonthPairs, random: () => number): Placed[] {
  const queue: { crewId: CrewId; slot: Slot }[] = []
  for (const crewId of CREW_ORDER) for (const slot of timelines.get(crewId) ?? []) queue.push({ crewId, slot })
  queue.sort((a, b) => a.slot.from - b.slot.from || CREW_ORDER.indexOf(a.crewId) - CREW_ORDER.indexOf(b.crewId))

  const placed: Placed[] = []
  for (const { crewId, slot } of queue) {
    if (slot.activity === 'away') {
      placed.push({ crewId, slot, waypoint: null })
      continue
    }
    const candidates = candidatesFor(slot.zone, slot.activity, crewId)
    const busy = new Set(placed.filter((p) => p.waypoint && overlaps(p.slot, slot)).map((p) => p.waypoint?.id))
    const free = candidates.filter((w) => !busy.has(w.id))
    // All fitting points busy: another free point of the zone (stand nearby), then the queue or the entry (wait a
    // turn), and only then share one.
    const freeInZone = free.length ? free : usableIn(slot.zone, crewId).filter((w) => !busy.has(w.id))
    const waiting = freeInZone.length ? freeInZone : usableIn(slot.zone, crewId, true).filter((w) => !busy.has(w.id))
    let pool = waiting.length ? waiting : candidates
    const favoured = pool.filter((w) => w.favoredBy?.includes(crewId))
    if (favoured.length) pool = favoured

    // Others in the same zone at the same time: sit near them, or keep a distance.
    const others = placed.filter((p) => p.crewId !== crewId && p.waypoint && p.slot.zone === slot.zone && overlaps(p.slot, slot))
    let choice: Waypoint | undefined
    if (others.length && pool.length > 1) {
      const sociable = (lore.get(crewId)?.avatar.sociability ?? 0.5) >= 0.5
      const friction = others.some((p) => inFriction(pairs, crewId, p.crewId))
      const bond = others.some((p) => bonded(pairs, crewId, p.crewId))
      const near = !friction && (bond || sociable)
      const score = (w: Waypoint) => Math.min(...others.map((p) => (p.waypoint ? distance(w, p.waypoint) : Infinity)))
      const scored = pool.map((w) => ({ w, s: score(w) }))
      const best = near ? Math.min(...scored.map((x) => x.s)) : Math.max(...scored.map((x) => x.s))
      const ties = scored.filter((x) => Math.abs(x.s - best) < 0.01).map((x) => x.w)
      choice = ties[Math.floor(random() * ties.length)]
    } else {
      choice = pool[Math.floor(random() * pool.length)]
    }
    placed.push({ crewId, slot, waypoint: choice ?? null })
  }
  return placed
}

// ——— Public API ———

/** The plan of one day of one training month, for the three crew members. `lore` comes from `DataSource.listCrewLore()`. */
export function buildDay(loreList: readonly CrewLore[], monthIndex: number, dayIndex: number): DayPlan {
  if (!Number.isInteger(monthIndex) || monthIndex < 0 || monthIndex >= TRAINING_MONTHS) throw new RangeError(`month index ${monthIndex}`)
  const days = daysInMonth(monthIndex)
  if (!Number.isInteger(dayIndex) || dayIndex < 0 || dayIndex >= days) throw new RangeError(`day index ${dayIndex} of ${days}`)

  const lore = new Map(loreList.map((l) => [l.crewId, l] as const))
  const entries = new Map<CrewId, MonthEntry>()
  for (const crewId of CREW_ORDER) {
    const entry = lore.get(crewId)?.timeline.find((m) => m.month === monthIndex + 1)
    if (!entry) throw new Error(`lore of ${crewId} has no month ${monthIndex + 1}`)
    entries.set(crewId, entry)
  }

  const { date, weekday } = dateOf(monthIndex, dayIndex)
  const weekend = weekday === 0 || weekday === 6
  const pairs = monthPairs(entries)
  const dayOrder = shuffled(ZONE_BASE, mulberry32(seedOf(monthIndex, dayIndex)))
  const slotCount = SHIFTS.reduce((sum, [start, end]) => sum + (end - start) / SLOT_MIN, 0)
  const counts = new Map(CREW_ORDER.map((crewId) => [crewId, programmeCounts(entries.get(crewId) as MonthEntry, monthIndex, slotCount)] as const))
  const overlays = dayOverlays(monthIndex, dayIndex, weekday)

  const timelines = new Map<CrewId, Slot[]>()
  for (const crewId of CREW_ORDER) {
    const entry = entries.get(crewId) as MonthEntry
    const crewLore = lore.get(crewId) as CrewLore
    const routine = ROUTINES[crewId]

    if (isAway(crewId, monthIndex, dayIndex)) {
      timelines.set(crewId, [{ from: 0, to: MINUTES_PER_DAY, zone: 'quarters', activity: 'away' }])
      continue
    }

    const wake = weekend ? routine.weekendWake : routine.wake
    const bedtime = Math.min(MINUTES_PER_DAY, Math.round((wake + MINUTES_PER_DAY - entry.wellbeing.sleepH * 60) / 15) * 15)
    const narrative = withdrawalOfMonth(crewId, monthIndex)
    const withdrawn = narrative
      ? narrative(dayIndex)
      : entry.wellbeing.stress >= WITHDRAW_STRESS && crewLore.avatar.sociability < WITHDRAW_SOCIABILITY
    const ctx: DayContext = { monthIndex, dayIndex, weekday, weekend, stressed: entry.wellbeing.stress >= STRESS_HIGH, withdrawn, bedtime }

    let timeline: Slot[] = []
    timeline = paint(timeline, { from: 0, to: wake, zone: 'quarters', activity: 'sleep' })
    timeline = paint(timeline, { from: bedtime, to: MINUTES_PER_DAY, zone: 'quarters', activity: 'sleep' })
    for (const s of routine.day(ctx)) timeline = paint(timeline, s)

    if (!weekend) {
      // Pair sessions: on Mondays, Wednesdays and Fridays the day opens in the zone shared with the closest partner.
      let first: WaypointZone | null = null
      if (PAIR_WORK_DAYS.has(weekday)) {
        const partners = CREW_ORDER.filter(
          (other) => other !== crewId && !isAway(other, monthIndex, dayIndex) && hasAny(pairs.kinds.get(pairKey(crewId, other)), WORK_KINDS),
        )
        const partner = crewLore.avatar.closestCrew.find((c) => partners.includes(c)) ?? partners[0]
        if (partner) first = sharedZone(counts.get(crewId) ?? new Map(), counts.get(partner) ?? new Map())
      }
      for (const s of programme(counts.get(crewId) ?? new Map(), dayOrder, first)) timeline = paint(timeline, s)

      const crewCounts = counts.get(crewId) ?? new Map<WaypointZone, number>()
      if (weekday === EXTRA_PRACTICE_DAY && !withdrawn) {
        const main = [...crewCounts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0]
        if (main) timeline = paint(timeline, { from: EXTRA_PRACTICE[0], to: EXTRA_PRACTICE[1], zone: main, activity: 'training' })
      }

      const staff = weekday === STAFF_DAY ? staffOf(entry) : null
      if (staff) timeline = paint(timeline, { from: STAFF_SESSION[0], to: STAFF_SESSION[1], zone: STAFF_ZONE[staff], activity: 'staff_session' })
    }

    // Shared evenings with a bond or social pair (not in friction, not withdrawn).
    if (PAIR_EVENING_DAYS.has(weekday) && !withdrawn) {
      const friends = CREW_ORDER.filter(
        (other) =>
          other !== crewId &&
          !isAway(other, monthIndex, dayIndex) &&
          !inFriction(pairs, crewId, other) &&
          hasAny(pairs.kinds.get(pairKey(crewId, other)), EVENING_KINDS),
      )
      if (friends.length) timeline = paint(timeline, { from: PAIR_EVENING[0], to: PAIR_EVENING[1], zone: 'lounge', activity: 'social' })
    }

    for (const overlay of overlays) {
      if (!overlay.crew.includes(crewId)) continue
      if (overlay.crew.some((other) => isAway(other, monthIndex, dayIndex))) continue
      timeline = paint(timeline, { from: overlay.from, to: overlay.to, zone: overlay.zone, activity: overlay.activity })
    }

    timelines.set(crewId, normalise(timeline))
  }

  const placed = placeAll(timelines, lore, pairs, mulberry32(seedOf(monthIndex, dayIndex, 7)))
  const crew = Object.fromEntries(CREW_ORDER.map((crewId) => [crewId, [] as Block[]])) as Record<CrewId, Block[]>
  for (const { crewId, slot, waypoint } of placed) {
    const away = slot.activity === 'away'
    crew[crewId].push({ from: slot.from, to: slot.to, zone: away ? null : slot.zone, waypoint: waypoint?.id ?? null, activity: slot.activity, with: [] })
  }
  // Company: others in the same zone at an overlapping time, both awake and in the hangar. Not the quarters: each crew
  // member is in a private room there.
  const present = (b: Block) => b.zone !== null && b.zone !== 'quarters' && b.activity !== 'sleep' && b.activity !== 'away'
  for (const crewId of CREW_ORDER) {
    crew[crewId].sort((a, b) => a.from - b.from)
    for (const block of crew[crewId]) {
      if (!present(block)) continue
      block.with = CREW_ORDER.filter((other) => other !== crewId && crew[other].some((b) => present(b) && b.zone === block.zone && overlaps(b, block)))
    }
  }
  return { monthIndex, dayIndex, date, weekday, crew }
}

/** The block a crew member is in at a minute of the day (0..1440). */
export function blockAt(blocks: readonly Block[], minute: number): Block | undefined {
  return blocks.find((b) => minute >= b.from && minute < b.to) ?? blocks[blocks.length - 1]
}
