import type { CrewId } from '@/lib/data/mock/crewLore'
import type { Pose } from './avatar'
import { route, type PlacedPoint, type Point3 } from './navigation'
import type { WalkGrid } from './walkgrid'
import type { Goal } from './simulation'

/**
 * Real-time walking of one avatar. The simulated clock runs fast and changes the goal (`simulation.ts`); the avatar
 * walks toward it at a natural pace, in real seconds. If the goal changes before it arrives, it turns toward the new
 * goal from where it is (as in life-simulation games): the clock never waits for the walk.
 */

/** Walking speeds in m/s, by the lore's `walkSpeed`. */
const SPEED_MPS = { slow: 1.0, normal: 1.3, brisk: 1.55 } as const
/**
 * On-screen pace as a multiple of the real walking speed. 1 would be realistic but leaves the crew mostly in transit
 * on a 120 m floor while a simulated day lasts 90 s; 2.5 reads as an unhurried walk at this distance.
 */
const PACE = 2.5
/** Metres per leg cycle: the walk animation follows the distance, so the legs match the pace. */
const STRIDE_M = 1.4

export type WalkSpeed = keyof typeof SPEED_MPS

export interface Placement {
  visible: boolean
  position: Point3
  heading: number
  pose: Pose
  /** Leg cycle phase, in radians (only meaningful while walking). */
  walkPhase: number
}

const distance = (a: Point3, b: Point3) => Math.hypot(b.x - a.x, b.y - a.y, b.z - a.z)

export class Mover {
  private readonly crewId: CrewId
  private readonly points: ReadonlyMap<string, PlacedPoint>
  private readonly grid: WalkGrid | undefined
  private readonly speed: number
  private at: Point3 | null = null
  private heading = 0
  /** The last waypoint reached: routes start from it. */
  private from: string | null = null
  private goalId: string | null = null
  private path: Point3[] = []
  private walked = 0

  constructor(crewId: CrewId, points: ReadonlyMap<string, PlacedPoint>, walkSpeed: WalkSpeed, grid?: WalkGrid) {
    this.crewId = crewId
    this.points = points
    this.grid = grid
    this.speed = SPEED_MPS[walkSpeed] * PACE
  }

  /** Forgets the walk: the next update places the avatar at its goal (month change, return from leave). */
  reset(): void {
    this.at = null
    this.from = null
    this.goalId = null
    this.path = []
  }

  /** Advances the walk by `seconds` of real time (0 while paused) toward `goal`. */
  update(goal: Goal, seconds: number): Placement {
    if (!goal.visible || !goal.waypoint) {
      this.reset()
      return { visible: false, position: goal.position, heading: 0, pose: 'stand', walkPhase: 0 }
    }
    if (!this.at) {
      this.at = { ...goal.position }
      this.from = goal.waypoint
      this.goalId = goal.waypoint
    }
    if (goal.waypoint !== this.goalId) {
      // New goal: the route from the last waypoint reached, without its start (the avatar is there or on its way).
      const next = route(this.from ?? goal.waypoint, goal.waypoint, this.crewId, this.points, this.grid)
      this.path = next.slice(1)
      this.goalId = goal.waypoint
    }

    let left = this.speed * Math.max(0, seconds)
    while (left > 0 && this.path.length) {
      const next = this.path[0] as Point3
      const gap = distance(this.at, next)
      if (gap > 1e-6) this.heading = Math.atan2(next.x - this.at.x, next.z - this.at.z)
      if (gap <= left) {
        this.at = { ...next }
        this.path.shift()
        left -= gap
        this.walked += gap
      } else {
        const t = left / gap
        this.at = { x: this.at.x + (next.x - this.at.x) * t, y: this.at.y + (next.y - this.at.y) * t, z: this.at.z + (next.z - this.at.z) * t }
        this.walked += left
        left = 0
      }
    }
    if (this.path.length) {
      return { visible: true, position: this.at, heading: this.heading, pose: 'walk', walkPhase: (this.walked / STRIDE_M) * Math.PI * 2 }
    }
    this.from = this.goalId
    return { visible: true, position: goal.position, heading: goal.heading, pose: goal.pose, walkPhase: 0 }
  }
}
