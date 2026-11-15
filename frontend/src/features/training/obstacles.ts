import { Mesh, Vector3, type Box3, type Object3D } from 'three'
import type { Obstacle } from './walkgrid'

/**
 * The floor footprints of the hangar, read from the loaded GLB: every mesh that stands on the floor band (its bottom below
 * 2 m and its top above 0.3 m) becomes an axis-aligned rectangle, from its own geometry box scaled by its world scale.
 * This covers the named objects (benches, barbells, the capsule, the kitchen) and the unnamed furniture alike.
 *
 * Not obstacles: the walkable surfaces (floor slabs, mats, grass, anything topping out below 0.3 m), the stairs (their
 * treads are walked), and everything above 2 m (the roof, the mezzanine, the high bays). Rotation is ignored in the
 * footprint: the furniture is axis-aligned in this model; the approximation is an over-estimate for rotated pieces only
 * when they are long and turned, and is kept small by the body clearance in `walkgrid.ts`.
 */

const FLOOR_BAND_TOP_M = 2
const WALKABLE_TOP_M = 0.3
const MIN_HEIGHT_M = 0.05

function underStairs(node: Object3D): boolean {
  for (let n: Object3D | null = node; n; n = n.parent) {
    if (n.name.startsWith('Stair') || n.name.startsWith('Egress')) return true
  }
  return false
}

/** The floor footprints of a loaded hangar scene (call after `updateMatrixWorld`). */
export function obstaclesOf(model: Object3D): Obstacle[] {
  const out: Obstacle[] = []
  const scale = new Vector3()
  model.traverse((node) => {
    if (!(node instanceof Mesh) || underStairs(node)) return
    const geometry = node.geometry
    if (!geometry.boundingBox) geometry.computeBoundingBox()
    const box: Box3 | null = geometry.boundingBox
    if (!box) return
    node.getWorldScale(scale)
    const centre = node.localToWorld(box.getCenter(new Vector3()))
    const half = box.getSize(new Vector3()).multiplyScalar(0.5)
    const hx = half.x * Math.abs(scale.x)
    const hy = half.y * Math.abs(scale.y)
    const hz = half.z * Math.abs(scale.z)
    const bottom = centre.y - hy
    const top = centre.y + hy
    if (bottom >= FLOOR_BAND_TOP_M || top < WALKABLE_TOP_M || top - bottom < MIN_HEIGHT_M) return
    out.push({ x: centre.x, z: centre.z, hx, hz })
  })
  return out
}
