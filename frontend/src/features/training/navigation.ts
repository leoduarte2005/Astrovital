import type { CrewId } from '@/lib/data/mock/crewLore'
import type { WalkGrid } from './walkgrid'
import { WAYPOINTS } from './behaviour'
import type { WaypointZone } from './behaviour'

/**
 * Walking routes between waypoints of the training hangar. The GLB has no navigation mesh, so a route is a polyline
 * through key points: the start, its approach point, the exit of its zone, the east stair when the level changes, the
 * entry of the target zone, the target's approach point and the target. Hall stretches are straight lines between
 * entries. On the ground floor, the stretches between them are walked around the objects (see `walkgrid.ts`).
 */

export interface Point3 {
  x: number
  y: number
  z: number
}

/** A waypoint as placed in the loaded GLB (world position and extras). */
export interface PlacedPoint {
  id: string
  zone: WaypointZone
  level: 0 | 1
  position: Point3
  facingDeg: number
  approach: { x: number; z: number } | null
  crewId: CrewId | null
}

/** The east stair, measured in the GLB: foot on the ground floor, top at the mezzanine landing (y 4.2). */
const STAIR_FOOT: Point3 = { x: 38.6, y: 0, z: 23.4 }
const STAIR_TOP: Point3 = { x: 31.2, y: 4.2, z: 23.4 }

const ENTRIES = WAYPOINTS.filter((w) => w.kind === 'entry')

function nearestEntry(zone: WaypointZone, near: Point3, crewId: CrewId, points: ReadonlyMap<string, PlacedPoint>): Point3 | null {
  let best: Point3 | null = null
  let bestDistance = Infinity
  for (const entry of ENTRIES) {
    if (entry.zone !== zone || (entry.crewId && entry.crewId !== crewId)) continue
    const placed = points.get(entry.id)
    if (!placed) continue
    const d = Math.hypot(placed.position.x - near.x, placed.position.z - near.z)
    if (d < bestDistance) {
      best = placed.position
      bestDistance = d
    }
  }
  return best
}

const approachOf = (p: PlacedPoint): Point3 | null => (p.approach ? { x: p.approach.x, y: p.position.y, z: p.approach.z } : null)

/**
 * Walks the key points of a route. On the ground floor, each stretch between two key points is an A* path over the
 * walkable grid, so the avatar goes around the objects; on the mezzanine, and when no grid is given, it is straight.
 */
function expand(keys: readonly Point3[], grid: WalkGrid | undefined): Point3[] {
  const out: Point3[] = []
  for (let i = 0; i < keys.length; i++) {
    const a = keys[i] as Point3
    const b = keys[i + 1]
    if (i === 0) out.push(a)
    if (!b) break
    const bothGround = a.y < 1 && b.y < 1
    const stretch = grid && bothGround ? grid.findPath(a, b) : null
    if (stretch && stretch.length > 1) out.push(...stretch.slice(1).map((p) => ({ x: p.x, y: a.y, z: p.z })))
    else out.push(b)
  }
  return out
}

/**
 * The route from one waypoint to another, as a polyline (at least one point). The key points are the start, its
 * approach, the exit of its zone, the stair when the level changes, the entry of the target zone, the target's approach
 * and the target; `grid` walks the ground-floor stretches around the objects.
 */
export function route(
  fromId: string,
  toId: string,
  crewId: CrewId,
  points: ReadonlyMap<string, PlacedPoint>,
  grid?: WalkGrid,
): Point3[] {
  const from = points.get(fromId)
  const to = points.get(toId)
  if (!from || !to) return to ? [to.position] : from ? [from.position] : []
  if (fromId === toId) return [to.position]

  const keys: Point3[] = [from.position]
  const push = (p: Point3 | null) => {
    if (p) keys.push(p)
  }
  push(approachOf(from))
  if (from.zone !== to.zone) {
    push(nearestEntry(from.zone, from.position, crewId, points))
    if (from.level === 1 && to.level === 0) {
      push(STAIR_TOP)
      push(STAIR_FOOT)
    } else if (from.level === 0 && to.level === 1) {
      push(STAIR_FOOT)
      push(STAIR_TOP)
    }
    push(nearestEntry(to.zone, to.position, crewId, points))
  }
  push(approachOf(to))
  keys.push(to.position)
  return expand(keys, grid)
}

/** Length of a polyline in metres. */
export function lengthOf(path: readonly Point3[]): number {
  let total = 0
  for (let i = 1; i < path.length; i++) {
    const a = path[i - 1] as Point3
    const b = path[i] as Point3
    total += Math.hypot(b.x - a.x, b.y - a.y, b.z - a.z)
  }
  return total
}

/** The point at `distance` metres along a polyline, and the heading (radians about Y, 0 = +Z) of that stretch. */
export function pointAlong(path: readonly Point3[], distance: number): { point: Point3; heading: number } {
  let left = Math.max(0, distance)
  for (let i = 1; i < path.length; i++) {
    const a = path[i - 1] as Point3
    const b = path[i] as Point3
    const segment = Math.hypot(b.x - a.x, b.y - a.y, b.z - a.z)
    const heading = Math.atan2(b.x - a.x, b.z - a.z)
    if (left <= segment || i === path.length - 1) {
      const t = segment > 0 ? Math.min(1, left / segment) : 1
      return { point: { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t, z: a.z + (b.z - a.z) * t }, heading }
    }
    left -= segment
  }
  const only = path[0] ?? { x: 0, y: 0, z: 0 }
  return { point: only, heading: 0 }
}
