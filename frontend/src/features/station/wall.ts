import { Vector3 } from 'three'

/** How far inside the wall a device sits, in model units (about 0.1 m at the station's scale). */
export const WALL_INSET = 0.004
/**
 * Half-thickness of the slice along a corridor where the wall is searched, in model units, widened in turn
 * until a wall vertex is found (corridors are short near their ends).
 */
const WALL_BANDS = [0.02, 0.04, 0.08] as const
/**
 * The outer shell counts as wall: candidates closer than this fraction of the outermost radius are skipped. It is
 * relaxed in turn if no free point is left on the outer shell.
 */
const SHELLS = [0.9, 0.75, 0.5] as const
/** Two devices never sit closer than this (model units, about 0.28 m). Used to keep devices apart. */
export const MIN_SEPARATION = 0.01

const rel = new Vector3()
const planar = new Vector3()

/**
 * A point on the outer wall of the hull, in direction `dir` from `at`, that no device already occupies.
 *
 * - With an `axis` (a corridor): the wall is searched in a thin slice across the corridor at `at`. Within the slice,
 *   the outer shell is taken, and the vertex whose direction from the axis is closest to `dir` wins. Different
 *   directions therefore land on different points of the tube.
 * - Without one (a room): the same, on the room's outer surface around `at`.
 * - `taken` holds the points of the devices already placed: a vertex within MIN_SEPARATION of one is skipped.
 *
 * `vertices` are in the model's local coordinates. Returns null when no free vertex qualifies.
 */
export function wallPointAlong(
  vertices: readonly Vector3[],
  at: Vector3,
  axis: Vector3 | null,
  dir: Vector3,
  taken: readonly Vector3[] = [],
): Vector3 | null {
  const across = dir.clone()
  if (axis) across.addScaledVector(axis, -across.dot(axis))
  if (across.lengthSq() < 1e-12) return null
  across.normalize()
  for (const band of axis ? WALL_BANDS : [Infinity]) {
    // Radius of each candidate from the axis (or from `at`), and its direction in the cross-section.
    const candidates: { vertex: Vector3; radius: number; cos: number }[] = []
    let outer = 0
    for (const vertex of vertices) {
      rel.copy(vertex).sub(at)
      if (axis) {
        const along = rel.dot(axis)
        if (Math.abs(along) > band) continue
        planar.copy(rel).addScaledVector(axis, -along)
      } else {
        planar.copy(rel)
      }
      const radius = planar.length()
      if (radius === 0) continue
      outer = Math.max(outer, radius)
      candidates.push({ vertex, radius, cos: planar.dot(across) / radius })
    }
    for (const shell of SHELLS) {
      let best: { vertex: Vector3; cos: number } | null = null
      for (const c of candidates) {
        if (c.radius < shell * outer) continue
        if (taken.some((point) => point.distanceTo(c.vertex) < MIN_SEPARATION)) continue
        if (!best || c.cos > best.cos) best = c
      }
      if (best) return best.vertex.clone().addScaledVector(across, -WALL_INSET)
    }
  }
  return null
}
