import type { CrewId, CrewLore } from '@/lib/data/mock/crewLore'
import type { Pose } from './avatar'
import { WAYPOINT_BY_ID, buildDay, type Block, type DayPlan } from './behaviour'
import type { PlacedPoint, Point3 } from './navigation'

/**
 * Where each crew member should be at a simulated minute: the waypoint of the current block of the day plan
 * (`behaviour/buildDay`), placed in the loaded GLB, and the pose there. The walk to it is not here: it runs in real
 * time (`mover.ts`), so the clock can run fast while the avatars walk at a natural pace.
 */

export interface Goal {
  visible: boolean
  /** Waypoint id of the GLB; null when away. */
  waypoint: string | null
  position: Point3
  /** Radians about Y; 0 faces +Z. */
  heading: number
  pose: Pose
}

/**
 * Shortest block, in simulated minutes, worth walking to. The clock runs fast and the avatars walk at a natural pace,
 * so a short block (a coffee, a 30 min stop) would be over before anyone got there: the avatar heads for the next block
 * long enough instead. The day plan itself is unchanged.
 */
export const MIN_VISIT_MINUTES = 90

const HIDDEN: Goal = { visible: false, waypoint: null, position: { x: 0, y: 0, z: 0 }, heading: 0, pose: 'stand' }

/**
 * The pose a place asks for: equipment and water first. A training block at the rowing machine rows, a block in the pool
 * swims, whatever the block's activity says. Only places with no pose of their own fall back to the activity.
 */
const PLACE_POSE: Record<string, Pose> = {
  rowing: 'row',
  running: 'run',
  cycling: 'cycle',
  bouldering: 'climb',
  strength: 'lift',
  dive_entry: 'swim',
  eva_underwater: 'swim',
}

/** The pose of a crew member resting at a block's waypoint. */
function poseFor(block: Block): Pose {
  if (block.activity === 'sleep') return 'lie'
  const point = block.waypoint ? WAYPOINT_BY_ID.get(block.waypoint) : undefined
  const placed = point?.activity ? PLACE_POSE[point.activity] : undefined
  if (placed) return placed
  if (block.activity === 'swim') return 'swim'
  if (block.activity === 'piano' || block.activity === 'radio') return 'sit'
  return point?.kind === 'seat' ? 'sit' : 'stand'
}

export class TrainingSimulation {
  private readonly lore: readonly CrewLore[]
  private readonly points: ReadonlyMap<string, PlacedPoint>
  private readonly plans = new Map<string, DayPlan>()
  private planMonth = -1

  constructor(lore: readonly CrewLore[], points: ReadonlyMap<string, PlacedPoint>) {
    this.lore = lore
    this.points = points
  }

  /** The day plan, cached for the current month only. */
  plan(monthIndex: number, dayIndex: number): DayPlan {
    if (monthIndex !== this.planMonth) {
      this.plans.clear()
      this.planMonth = monthIndex
    }
    const key = `${monthIndex}:${dayIndex}`
    let plan = this.plans.get(key)
    if (!plan) {
      plan = buildDay(this.lore, monthIndex, dayIndex)
      this.plans.set(key, plan)
    }
    return plan
  }

  /**
   * The goal of a crew member at a simulated minute: the current block's waypoint and pose, or, if the current block is
   * shorter than `MIN_VISIT_MINUTES`, the next block of the day that is long enough (the last block if none is).
   */
  goalAt(crewId: CrewId, monthIndex: number, dayIndex: number, minute: number): Goal {
    const blocks = this.plan(monthIndex, dayIndex).crew[crewId]
    let index = blocks.findIndex((b) => minute >= b.from && minute < b.to)
    if (index < 0) index = blocks.length - 1
    while (index < blocks.length - 1) {
      const current = blocks[index] as Block
      if (current.activity === 'away' || current.to - current.from >= MIN_VISIT_MINUTES) break
      index++
    }
    const block = blocks[index]
    if (!block || block.activity === 'away' || !block.waypoint) return HIDDEN
    const target = this.points.get(block.waypoint)
    if (!target) return HIDDEN
    return {
      visible: true,
      waypoint: block.waypoint,
      position: target.position,
      heading: (target.facingDeg * Math.PI) / 180,
      pose: poseFor(block),
    }
  }
}
