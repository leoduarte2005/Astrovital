/**
 * Behaviour of the crew walkers in the station: they follow the corridors between rooms (module centres), dwell in
 * each room they stop at, and talk when they meet another walker in the same room. Pure logic: no three.js here,
 * so the renderer only places spheres at `pos`.
 */

export interface Point {
  x: number
  y: number
  z: number
}

export interface WalkStop {
  /** Room key: the match string of a station module (see `corridors.ts`). */
  room: string
  /** Meeting point: walkers that arrive here stay longer, to meet each other. */
  meet?: boolean
}

export interface WalkRoute {
  id: string
  /** Visited in order, then the route starts again (loop). */
  stops: readonly WalkStop[]
}

export interface WalkConfig {
  routes: readonly WalkRoute[]
  /** Rooms connected by a corridor (pairs). */
  corridors: readonly (readonly [string, string])[]
  /** Centre of each room, in the same space as the walkers. */
  rooms: Readonly<Record<string, Point>>
  /** Units per second. */
  speed: number
  /**
   * Distance between walkers that share a room, measured along the room's first corridor: they line up on the
   * corridor line itself, so no walker is ever off the path.
   */
  slotStep: number
  dwellMs: number
  meetMs: number
  /** Extra time two walkers spend together when they meet in a room. */
  talkMs: number
}

export interface Walker {
  readonly id: string
  readonly route: WalkRoute
  /** Current position, updated in place. */
  readonly pos: Point
  /** Last room reached. */
  room: string
  /** Rooms still to reach on the way to the next stop. */
  path: string[]
  /** Index of the next stop in `route.stops`. */
  stopIndex: number
  /** Time (ms, same clock as `now`) until which the walker stays in its room. */
  dwellUntil: number
  /** True while the walker waits away from the room centre (sharing the room); it walks back before leaving. */
  displaced: boolean
  /** The room the current leg heads for, and where that leg started: used for the push-off and the braking. */
  legTarget: string | null
  legStart: Point | null
}

/** Slowest speed of a leg, as a fraction of the cruise speed: at the push-off and when braking. Never zero. */
const DRIFT_MIN = 0.2

/** A slot never goes past this fraction of the corridor, so it stays well inside the segment. */
const SLOT_MAX_FRACTION = 0.4

export class Walkers {
  readonly list: Walker[]
  private readonly adjacency = new Map<string, string[]>()
  private readonly config: WalkConfig

  constructor(config: WalkConfig, now: number) {
    this.config = config
    for (const [a, b] of config.corridors) {
      this.link(a, b)
      this.link(b, a)
    }
    this.list = []
    for (const route of config.routes) {
      const first = route.stops[0]
      if (!first || !config.rooms[first.room]) continue
      const start = this.centre(first.room)
      const walker: Walker = {
        id: route.id,
        route,
        pos: { x: start.x, y: start.y, z: start.z },
        room: first.room,
        path: [],
        stopIndex: 0,
        dwellUntil: 0,
        displaced: false,
        legTarget: null,
        legStart: null,
      }
      // Added before arriving, so arrival can meet the walkers already placed.
      this.list.push(walker)
      this.arrive(walker, now)
    }
  }

  /** Advances every walker by `dt` seconds. Walkers that dwell keep their place in the room. */
  update(now: number, dt: number): void {
    for (const walker of this.list) {
      if (now < walker.dwellUntil) {
        this.place(walker, now)
        continue
      }
      // Leaving a waiting slot: first back to the room centre along the same corridor line.
      if (walker.displaced) {
        walker.path.unshift(walker.room)
        walker.displaced = false
      }
      let remaining = this.config.speed * dt * this.driftFactor(walker)
      while (walker.path.length > 0 && remaining > 0) {
        const next = walker.path[0]
        if (next === undefined) break
        const target = this.centre(next)
        const dist = Math.hypot(target.x - walker.pos.x, target.y - walker.pos.y, target.z - walker.pos.z)
        if (dist <= remaining) {
          walker.pos.x = target.x
          walker.pos.y = target.y
          walker.pos.z = target.z
          remaining -= dist
          walker.room = next
          walker.path.shift()
          walker.legTarget = null // the next leg starts here
        } else {
          const k = remaining / dist
          walker.pos.x += (target.x - walker.pos.x) * k
          walker.pos.y += (target.y - walker.pos.y) * k
          walker.pos.z += (target.z - walker.pos.z) * k
          remaining = 0
        }
      }
      if (walker.path.length === 0) this.arrive(walker, now)
    }
  }

  /** True while the walker stays in its room (not walking). */
  isDwelling(walker: Walker, now: number): boolean {
    return now < walker.dwellUntil
  }

  /** Another walker dwelling in the same room, if any: the one this walker talks to. */
  companion(walker: Walker, now: number): Walker | undefined {
    return this.list.find((other) => other !== walker && other.room === walker.room && now < other.dwellUntil)
  }

  /**
   * Speed factor along the current corridor. In zero gravity there is nothing to walk on: the crew pushes off,
   * drifts and slows down to catch hold at the end. A smooth bell over the leg, between DRIFT_MIN and 1.
   */
  private driftFactor(walker: Walker): number {
    const next = walker.path[0]
    if (next === undefined) return 1
    const target = this.centre(next)
    if (walker.legTarget !== next || !walker.legStart) {
      walker.legTarget = next
      walker.legStart = { x: walker.pos.x, y: walker.pos.y, z: walker.pos.z }
    }
    const start = walker.legStart
    const total = Math.hypot(target.x - start.x, target.y - start.y, target.z - start.z)
    const left = Math.hypot(target.x - walker.pos.x, target.y - walker.pos.y, target.z - walker.pos.z)
    const progress = total > 0 ? Math.min(1, Math.max(0, 1 - left / total)) : 1
    return DRIFT_MIN + (1 - DRIFT_MIN) * Math.sin(Math.PI * progress)
  }

  private link(a: string, b: string): void {
    const list = this.adjacency.get(a) ?? []
    list.push(b)
    this.adjacency.set(a, list)
  }

  private centre(room: string): Point {
    const point = this.config.rooms[room]
    if (!point) throw new Error(`walkers: unknown room ${room}`)
    return point
  }

  /** Arrival at the current stop: dwell there, meet anyone already dwelling in the room, and plan the next leg. */
  private arrive(walker: Walker, now: number): void {
    const stop = walker.route.stops[walker.stopIndex]
    if (!stop) return
    walker.room = stop.room
    walker.dwellUntil = now + (stop.meet ? this.config.meetMs : this.config.dwellMs)
    for (const other of this.list) {
      if (other === walker || other.room !== walker.room || now >= other.dwellUntil) continue
      const together = Math.max(walker.dwellUntil, other.dwellUntil) + this.config.talkMs
      walker.dwellUntil = together
      other.dwellUntil = together
    }
    walker.stopIndex = (walker.stopIndex + 1) % walker.route.stops.length
    const next = walker.route.stops[walker.stopIndex]
    walker.path = next ? this.roomPath(walker.room, next.room) : []
  }

  /**
   * Places a dwelling walker at its slot in the room. The first walker stands at the centre; the others stand
   * further along the room's first corridor, on the line itself.
   */
  private place(walker: Walker, now: number): void {
    const others = this.list.filter((other) => other.room === walker.room && now < other.dwellUntil)
    const slot = Math.max(0, others.findIndex((other) => other === walker))
    const centre = this.centre(walker.room)
    const neighbour = this.adjacency.get(walker.room)?.[0]
    let fraction = 0
    let toward = centre
    if (neighbour !== undefined) {
      toward = this.centre(neighbour)
      const length = Math.hypot(toward.x - centre.x, toward.y - centre.y, toward.z - centre.z)
      if (length > 0) fraction = Math.min(slot * this.config.slotStep, length * SLOT_MAX_FRACTION) / length
    }
    walker.pos.x = centre.x + (toward.x - centre.x) * fraction
    walker.pos.y = centre.y + (toward.y - centre.y) * fraction
    walker.pos.z = centre.z + (toward.z - centre.z) * fraction
    walker.displaced = fraction > 0
  }

  /** Shortest chain of rooms from `from` (excluded) to `to` (included), along the corridors. Empty if none. */
  private roomPath(from: string, to: string): string[] {
    if (from === to) return []
    const previous = new Map<string, string>()
    const queue = [from]
    const seen = new Set([from])
    while (queue.length > 0) {
      const room = queue.shift()
      if (room === undefined) break
      for (const next of this.adjacency.get(room) ?? []) {
        if (seen.has(next)) continue
        seen.add(next)
        previous.set(next, room)
        if (next === to) {
          const path: string[] = []
          let step: string | undefined = to
          while (step !== undefined && step !== from) {
            path.unshift(step)
            step = previous.get(step)
          }
          return path
        }
        queue.push(next)
      }
    }
    return []
  }
}
