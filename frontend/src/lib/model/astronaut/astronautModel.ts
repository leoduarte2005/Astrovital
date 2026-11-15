import { BufferAttribute, BufferGeometry, Box3, Matrix4, Vector3 } from 'three'

/**
 * The NASA astronaut model (data/models/astronaut/Astronaut.glb) has no skeleton: its suit is one mesh. To pose it
 * (arms and legs moving, as the crew avatars do), the mesh is cut into body, two arms and two legs, each limb baked
 * to hang from its joint. Pure geometry, no WebGL: the loader feeds it the mesh in world space.
 *
 * World space of the model after its root rotation: +Y up, +Z front (the visor is at +Z), the origin at the centre
 * of the body. The arms are stretched out sideways (T-pose); the legs hang from the hips.
 */

export type LimbPart = 'armLeft' | 'armRight' | 'legLeft' | 'legRight'
export type AstronautPart = 'body' | LimbPart

/** Triangles of one mesh, in world space. `index` is null for non-indexed geometry. */
export interface RawMesh {
  position: Float32Array
  normal: Float32Array | null
  uv: Float32Array | null
  index: ArrayLike<number> | null
}

/** Joints in the model's own units, before scaling: where each limb meets the torso. */
export const JOINTS: Record<LimbPart, Vector3> = {
  armLeft: new Vector3(-13.5, 14, 0),
  armRight: new Vector3(13.5, 14, 0),
  legLeft: new Vector3(-7, -14, 0),
  legRight: new Vector3(7, -14, 0),
}

/** Beyond this distance from the centre, sideways, is an arm: the torso stays inside it. */
const ARM_REACH = 13.5
/** Below this height is a leg: the pelvis stays above it. */
const LEG_BELOW = -15.5

/** Which part a point belongs to, by its position. */
export function partOf(x: number, y: number): AstronautPart {
  if (x < -ARM_REACH) return 'armLeft'
  if (x > ARM_REACH) return 'armRight'
  if (y < LEG_BELOW) return x < 0 ? 'legLeft' : 'legRight'
  return 'body'
}

interface PartData {
  position: number[]
  normal: number[]
  uv: number[]
}

/**
 * Splits a mesh triangle by triangle: each triangle goes to the part of its centroid, so no triangle is cut.
 * Returns non-indexed data per part.
 */
export function splitAstronaut(mesh: RawMesh): Partial<Record<AstronautPart, PartData>> {
  const out: Partial<Record<AstronautPart, PartData>> = {}
  const triangles = mesh.index ? mesh.index.length / 3 : mesh.position.length / 9
  for (let t = 0; t < triangles; t++) {
    const corners = [0, 1, 2].map((k) => (mesh.index ? mesh.index[t * 3 + k] : t * 3 + k) ?? 0)
    let cx = 0
    let cy = 0
    for (const c of corners) {
      cx += mesh.position[c * 3] ?? 0
      cy += mesh.position[c * 3 + 1] ?? 0
    }
    const part = partOf(cx / 3, cy / 3)
    const data = (out[part] ??= { position: [], normal: [], uv: [] })
    for (const c of corners) {
      data.position.push(mesh.position[c * 3] ?? 0, mesh.position[c * 3 + 1] ?? 0, mesh.position[c * 3 + 2] ?? 0)
      if (mesh.normal) data.normal.push(mesh.normal[c * 3] ?? 0, mesh.normal[c * 3 + 1] ?? 0, mesh.normal[c * 3 + 2] ?? 0)
      if (mesh.uv) data.uv.push(mesh.uv[c * 2] ?? 0, mesh.uv[c * 2 + 1] ?? 0)
    }
  }
  return out
}

function toGeometry(data: PartData): BufferGeometry {
  const geometry = new BufferGeometry()
  geometry.setAttribute('position', new BufferAttribute(new Float32Array(data.position), 3))
  if (data.normal.length > 0) geometry.setAttribute('normal', new BufferAttribute(new Float32Array(data.normal), 3))
  if (data.uv.length > 0) geometry.setAttribute('uv', new BufferAttribute(new Float32Array(data.uv), 2))
  return geometry
}

export interface BakedAstronaut {
  body: BufferGeometry
  /** The visor and other head pieces of the second material: they stay with the body. */
  visor: BufferGeometry | null
  /** Each limb, relative to its joint, hanging down from it (arms rotated from the T-pose). */
  limbs: Record<LimbPart, BufferGeometry>
  /** Joints in scaled units, in the body's space. */
  joints: Record<LimbPart, Vector3>
  /** Length of each limb in scaled units, from the joint to its end. */
  limbLength: Record<LimbPart, number>
  /** Overall height in scaled units (the boot soles to the top of the helmet). */
  height: number
}

/**
 * Scales the model to `height` (scaled units) and bakes each limb relative to its joint. The arms are turned from the
 * T-pose so they hang straight down from the shoulder; the poses then swing them as on any hanging arm.
 */
export function bakeAstronaut(
  split: Partial<Record<AstronautPart, PartData>>,
  visorMesh: RawMesh | null,
  height: number,
): BakedAstronaut {
  // Overall extent in model units, from every part, to get the scale.
  const box = new Box3()
  for (const data of Object.values(split)) {
    if (!data) continue
    for (let k = 0; k < data.position.length; k += 3) box.expandByPoint(new Vector3(data.position[k], data.position[k + 1], data.position[k + 2]))
  }
  const modelHeight = box.max.y - box.min.y
  const scale = height / modelHeight
  const bodyData = split.body
  if (!bodyData) throw new Error('astronaut: no body triangles')

  const body = toGeometry(bodyData).scale(scale, scale, scale)
  const visor = visorMesh
    ? toGeometry({
        position: Array.from(visorMesh.position),
        normal: visorMesh.normal ? Array.from(visorMesh.normal) : [],
        uv: visorMesh.uv ? Array.from(visorMesh.uv) : [],
      }).scale(scale, scale, scale)
    : null

  const limbs = {} as Record<LimbPart, BufferGeometry>
  const joints = {} as Record<LimbPart, Vector3>
  const limbLength = {} as Record<LimbPart, number>
  const turn = new Matrix4()
  for (const part of ['armLeft', 'armRight', 'legLeft', 'legRight'] as const) {
    const data = split[part]
    if (!data) throw new Error(`astronaut: no ${part} triangles`)
    const joint = JOINTS[part]
    const geometry = toGeometry(data)
    // Relative to the joint, then turned so an outstretched arm points down: left arm (-X) quarter turn +90 about Z,
    // right arm (+X) -90. Legs already hang down.
    geometry.translate(-joint.x, -joint.y, -joint.z)
    if (part === 'armLeft') geometry.applyMatrix4(turn.makeRotationZ(Math.PI / 2))
    if (part === 'armRight') geometry.applyMatrix4(turn.makeRotationZ(-Math.PI / 2))
    geometry.scale(scale, scale, scale)
    limbs[part] = geometry
    joints[part] = joint.clone().multiplyScalar(scale)
    geometry.computeBoundingBox()
    limbLength[part] = -(geometry.boundingBox?.min.y ?? 0)
  }

  return { body, visor, limbs, joints, limbLength, height }
}
