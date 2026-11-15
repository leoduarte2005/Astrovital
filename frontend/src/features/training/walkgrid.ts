/**
 * Walkable grid of the hangar floor, built from the GLB's own object markers (see `obstacles.ts`). Each object blocks a disc
 * around its centre, enlarged by the body radius of an avatar, so a route never passes through it. Routes are A* paths
 * over the grid, smoothed to straight lines where the way is clear. Pure math: no three.js.
 */

export interface Obstacle {
  /** Centre of the footprint, metres. */
  x: number
  z: number
  /** Half sizes of the axis-aligned footprint, metres. */
  hx: number
  hz: number
}

export interface Bounds {
  x0: number
  x1: number
  z0: number
  z1: number
}

export interface Spot {
  x: number
  z: number
}

/** Cell size, metres. Small enough to pass between two benches, large enough to keep the grid light. */
const CELL = 0.5
/** Clearance kept from every object: the avatar's body radius. */
const BODY_M = 0.35
/** Distance from the hangar walls a route keeps. */
const WALL_M = 0.5
/** How far a blocked start or goal is searched for a free cell. */
const SEARCH_M = 3

export class WalkGrid {
  readonly nx: number
  readonly nz: number
  private readonly x0: number
  private readonly z0: number
  private readonly blocked: Uint8Array

  constructor(obstacles: readonly Obstacle[], bounds: Bounds) {
    this.x0 = bounds.x0
    this.z0 = bounds.z0
    this.nx = Math.ceil((bounds.x1 - bounds.x0) / CELL)
    this.nz = Math.ceil((bounds.z1 - bounds.z0) / CELL)
    this.blocked = new Uint8Array(this.nx * this.nz)

    // Walls: the outer ring of cells, and everything within WALL_M of the walls.
    for (let j = 0; j < this.nz; j++) {
      for (let i = 0; i < this.nx; i++) {
        const { x, z } = this.centreOf(i, j)
        const edge = Math.min(x - bounds.x0, bounds.x1 - x, z - bounds.z0, bounds.z1 - z)
        if (edge < WALL_M) this.blocked[j * this.nx + i] = 1
      }
    }
    // Objects: each footprint, grown by the body clearance on every side.
    for (const o of obstacles) {
      const hx = o.hx + BODY_M
      const hz = o.hz + BODY_M
      const i0 = Math.max(0, Math.floor((o.x - hx - this.x0) / CELL))
      const i1 = Math.min(this.nx - 1, Math.floor((o.x + hx - this.x0) / CELL))
      const j0 = Math.max(0, Math.floor((o.z - hz - this.z0) / CELL))
      const j1 = Math.min(this.nz - 1, Math.floor((o.z + hz - this.z0) / CELL))
      for (let j = j0; j <= j1; j++) {
        for (let i = i0; i <= i1; i++) {
          const { x, z } = this.centreOf(i, j)
          if (Math.abs(x - o.x) < hx && Math.abs(z - o.z) < hz) this.blocked[j * this.nx + i] = 1
        }
      }
    }
  }

  private centreOf(i: number, j: number): Spot {
    return { x: this.x0 + (i + 0.5) * CELL, z: this.z0 + (j + 0.5) * CELL }
  }

  private cellOf(p: Spot): { i: number; j: number } {
    return { i: Math.floor((p.x - this.x0) / CELL), j: Math.floor((p.z - this.z0) / CELL) }
  }

  private isFree(i: number, j: number): boolean {
    return i >= 0 && j >= 0 && i < this.nx && j < this.nz && this.blocked[j * this.nx + i] === 0
  }

  /** The nearest free cell to a point (the point itself when free). Null when none is within SEARCH_M. */
  nearestFree(p: Spot): Spot | null {
    const { i, j } = this.cellOf(p)
    if (this.isFree(i, j)) return this.centreOf(i, j)
    const reach = Math.ceil(SEARCH_M / CELL)
    let best: Spot | null = null
    let bestD = Infinity
    for (let dj = -reach; dj <= reach; dj++) {
      for (let di = -reach; di <= reach; di++) {
        if (!this.isFree(i + di, j + dj)) continue
        const c = this.centreOf(i + di, j + dj)
        const d = Math.hypot(c.x - p.x, c.z - p.z)
        if (d < bestD) {
          bestD = d
          best = c
        }
      }
    }
    return best
  }

  /** True when the straight line between two points crosses no blocked cell. */
  clear(a: Spot, b: Spot): boolean {
    const steps = Math.ceil(Math.hypot(b.x - a.x, b.z - a.z) / (CELL / 2))
    for (let s = 0; s <= steps; s++) {
      const t = steps ? s / steps : 0
      const { i, j } = this.cellOf({ x: a.x + (b.x - a.x) * t, z: a.z + (b.z - a.z) * t })
      if (!this.isFree(i, j)) return false
    }
    return true
  }

  /**
   * Shortest walk from `from` to `to` over free cells, as points (start and end included). The start and the end are
   * moved to the nearest free cell when they sit inside an object (a seat on equipment is the goal of a walk), and the
   * last stretch goes straight to the exact point. Null when no route exists.
   */
  findPath(from: Spot, to: Spot): Spot[] | null {
    const start = this.nearestFree(from)
    const goal = this.nearestFree(to)
    if (!start || !goal) return null
    const cells = this.astar(start, goal)
    if (!cells) return null
    const smooth = this.prune(cells)
    const out: Spot[] = [from, ...smooth.slice(1, -1)]
    if (smooth.length > 1) out.push(smooth[smooth.length - 1] as Spot)
    out.push(to)
    return out
  }

  /** A* over the 8-connected grid, octile distance. Returns the cell centres from start to goal. */
  private astar(start: Spot, goal: Spot): Spot[] | null {
    const s = this.cellOf(start)
    const g = this.cellOf(goal)
    const total = this.nx * this.nz
    const startIdx = s.j * this.nx + s.i
    const goalIdx = g.j * this.nx + g.i
    const gScore = new Float64Array(total).fill(Infinity)
    const came = new Int32Array(total).fill(-1)
    const closed = new Uint8Array(total)
    const heap = new MinHeap()
    gScore[startIdx] = 0
    heap.push(startIdx, this.octile(s.i, s.j, g.i, g.j))

    const DIRS = [
      [1, 0, 1], [-1, 0, 1], [0, 1, 1], [0, -1, 1],
      [1, 1, Math.SQRT2], [1, -1, Math.SQRT2], [-1, 1, Math.SQRT2], [-1, -1, Math.SQRT2],
    ] as const
    while (heap.size) {
      const current = heap.pop()
      if (current === goalIdx) break
      if (closed[current]) continue
      closed[current] = 1
      const ci = current % this.nx
      const cj = (current - ci) / this.nx
      for (const [di, dj, cost] of DIRS) {
        const ni = ci + di
        const nj = cj + dj
        if (!this.isFree(ni, nj)) continue
        // A diagonal step needs both side cells free, so the route never squeezes past a corner.
        if (di && dj && (!this.isFree(ci + di, cj) || !this.isFree(ci, cj + dj))) continue
        const n = nj * this.nx + ni
        if (closed[n]) continue
        const tentative = (gScore[current] ?? Infinity) + cost
        if (tentative < (gScore[n] ?? Infinity)) {
          gScore[n] = tentative
          came[n] = current
          heap.push(n, tentative + this.octile(ni, nj, g.i, g.j))
        }
      }
    }
    if (came[goalIdx] === -1 && goalIdx !== startIdx) return null
    const path: Spot[] = []
    for (let at = goalIdx; at !== -1; at = came[at] ?? -1) {
      const i = at % this.nx
      const j = (at - i) / this.nx
      path.push(this.centreOf(i, j))
      if (at === startIdx) break
    }
    return path.reverse()
  }

  private octile(i: number, j: number, gi: number, gj: number): number {
    const dx = Math.abs(i - gi)
    const dz = Math.abs(j - gj)
    return Math.max(dx, dz) + (Math.SQRT2 - 1) * Math.min(dx, dz)
  }

  /** Drops the cell centres that a straight line makes unnecessary (greedy line of sight). */
  private prune(path: Spot[]): Spot[] {
    if (path.length <= 2) return path
    const out: Spot[] = [path[0] as Spot]
    let anchor = 0
    while (anchor < path.length - 1) {
      let next = anchor + 1
      for (let k = path.length - 1; k > anchor + 1; k--) {
        if (this.clear(path[anchor] as Spot, path[k] as Spot)) {
          next = k
          break
        }
      }
      out.push(path[next] as Spot)
      anchor = next
    }
    return out
  }
}

/** Binary min-heap of (index, priority), for A*. */
class MinHeap {
  private readonly items: { node: number; priority: number }[] = []

  get size(): number {
    return this.items.length
  }

  push(node: number, priority: number): void {
    this.items.push({ node, priority })
    let i = this.items.length - 1
    while (i > 0) {
      const parent = (i - 1) >> 1
      if ((this.items[parent] as { priority: number }).priority <= (this.items[i] as { priority: number }).priority) break
      ;[this.items[parent], this.items[i]] = [this.items[i] as never, this.items[parent] as never]
      i = parent
    }
  }

  pop(): number {
    const top = this.items[0] as { node: number; priority: number }
    const last = this.items.pop() as { node: number; priority: number }
    if (this.items.length) {
      this.items[0] = last
      let i = 0
      for (;;) {
        const l = 2 * i + 1
        const r = l + 1
        let smallest = i
        if (l < this.items.length && (this.items[l] as { priority: number }).priority < (this.items[smallest] as { priority: number }).priority) smallest = l
        if (r < this.items.length && (this.items[r] as { priority: number }).priority < (this.items[smallest] as { priority: number }).priority) smallest = r
        if (smallest === i) break
        ;[this.items[smallest], this.items[i]] = [this.items[i] as never, this.items[smallest] as never]
        i = smallest
      }
    }
    return top.node
  }
}
