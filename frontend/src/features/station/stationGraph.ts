import { Box3, Vector3, type Mesh, type Object3D } from 'three'
import { STATION_MODULES } from './corridors'

/** Compares names ignoring spaces, underscores and case: three sanitises GLB node names (spaces become underscores). */
const normalizeName = (name: string) => name.replace(/[\s_]/g, '').toLowerCase()

/** The first node (parents before children) whose name contains `match`. */
export function findNode(root: Object3D, match: string): Object3D | null {
  const wanted = normalizeName(match)
  let found: Object3D | null = null
  root.traverse((node) => {
    if (!found && normalizeName(node.name).includes(wanted)) found = node
  })
  return found
}

/** Visits the vertices (world units) of the meshes directly under a node: the module's own hull. */
function forEachHullVertex(node: Object3D, visit: (point: Vector3) => void): number {
  const point = new Vector3()
  let count = 0
  for (const child of node.children) {
    const mesh = child as Mesh
    if (!mesh.isMesh) continue
    const position = mesh.geometry.getAttribute('position')
    for (let i = 0; i < position.count; i++) visit(point.fromBufferAttribute(position, i).applyMatrix4(mesh.matrixWorld))
    count += position.count
  }
  return count
}

/**
 * Centre of a module's hull, in world units: the mean of the vertices of the meshes directly under its node.
 * In the GLB the modules hang from each other, so the bounding box of a node also covers everything attached
 * to it (Unity's would be the whole station); its own meshes are the hull. Null if it has none.
 */
export function hullCentre(node: Object3D): Vector3 | null {
  const sum = new Vector3()
  const count = forEachHullVertex(node, (point) => sum.add(point))
  return count > 0 ? sum.divideScalar(count) : null
}

/** Extent of a module's hull along each given unit axis. Null if it has no hull. */
function hullExtents(node: Object3D, axes: readonly Vector3[]): number[] | null {
  const lo = axes.map(() => Infinity)
  const hi = axes.map(() => -Infinity)
  const count = forEachHullVertex(node, (point) => {
    axes.forEach((axis, i) => {
      const t = point.dot(axis)
      lo[i] = Math.min(lo[i] ?? Infinity, t)
      hi[i] = Math.max(hi[i] ?? -Infinity, t)
    })
  })
  return count > 0 ? axes.map((_, i) => (hi[i] ?? 0) - (lo[i] ?? 0)) : null
}

/** Centre of a section by node name: its hull, or the bounding box of the node when it has no meshes of its own. */
export function nodeCentre(root: Object3D, match: string): Vector3 | null {
  const node = findNode(root, match)
  if (!node) return null
  const hull = hullCentre(node)
  if (hull) return hull
  const box = new Box3().setFromObject(node)
  return box.isEmpty() ? null : box.getCenter(new Vector3())
}

/**
 * The station's own axes, read from the GLB. The model is not aligned to the world: the station is tilted about
 * its long axis (about 22 degrees in the current GLB), so crew must be oriented by these axes, not by world Y.
 */
export interface StationFrame {
  /** Along the main spine, Zvezda (aft) to Harmony (fore). */
  forward: Vector3
  /** Across the station, Columbus to Kibo. */
  lateral: Vector3
  /** The station's "up" (zenith): forward x lateral. */
  up: Vector3
}

export interface StationGraph {
  /** Room centres by module name, in the model's local coordinates. */
  rooms: Record<string, Vector3>
  /** Corridors: the module and the module it hangs from in the GLB, parent first. */
  corridors: [string, string][]
  frame: StationFrame
  /** Real metres per model unit, from the diameter of the nodes (Unity and Harmony are about 4.5 m across). */
  metresPerUnit: number
  /** The meshes of the pressurised modules' own hulls (the meshes directly under each module node). */
  hull: Mesh[]
  /** The same hull meshes, by module name. */
  hullByModule: Record<string, Mesh[]>
}

const KIBO = 'Kibo Space Laboratory (PSM) Pressurized Module'
/** Real diameter of the station's nodes (Unity 4.57 m, Harmony 4.48 m). */
const NODE_DIAMETER_M = 4.5
/** Used only if the GLB lacks the modules the frame and the scale are read from. */
const FALLBACK_METRES_PER_UNIT = 28

/**
 * Rooms and corridors of the station, read from the GLB: a room is a module's hull centre, and a corridor joins a
 * module to the nearest module above it in the node hierarchy (its assembly parent). The frame and the scale come
 * from the same hull data. The model's world matrices must be up to date.
 */
export function buildStationGraph(model: Object3D): StationGraph {
  model.updateMatrixWorld(true)
  const nodes = new Map<Object3D, string>()
  for (const key of STATION_MODULES) {
    const node = findNode(model, key)
    if (node) nodes.set(node, key)
  }
  const rooms: Record<string, Vector3> = {}
  for (const [node, key] of nodes) {
    const centre = hullCentre(node)
    if (centre) rooms[key] = model.worldToLocal(centre)
  }
  const corridors: [string, string][] = []
  for (const [node, key] of nodes) {
    if (!rooms[key]) continue
    let ancestor = node.parent
    while (ancestor && !nodes.has(ancestor)) ancestor = ancestor.parent
    const parentKey = ancestor ? nodes.get(ancestor) : undefined
    if (parentKey && rooms[parentKey]) corridors.push([parentKey, key])
  }

  // Frame: forward from the spine (Zvezda to Harmony); lateral from the two port-starboard pairs through the hubs
  // (Columbus to Kibo through Harmony, Quest to Tranquility through Unity), made perpendicular to forward.
  let frame: StationFrame = { forward: new Vector3(0, 0, 1), lateral: new Vector3(1, 0, 0), up: new Vector3(0, 1, 0) }
  const zvezda = rooms['Zvezda (SM)']
  const harmony = rooms['Harmony Node']
  const columbus = rooms['Columbus Space Laboratory']
  const kibo = rooms[KIBO]
  const quest = rooms['Quest Airlock']
  const tranquility = rooms['Tranquility Node']
  if (zvezda && harmony && columbus && kibo && quest && tranquility) {
    const forward = harmony.clone().sub(zvezda).normalize()
    const lateral = kibo.clone().sub(columbus).normalize().add(tranquility.clone().sub(quest).normalize()).normalize()
    lateral.addScaledVector(forward, -lateral.dot(forward)).normalize()
    frame = { forward, lateral, up: forward.clone().cross(lateral).normalize() }
  }

  // Scale: the nodes' diameter, measured across the station axis, is about 4.5 m.
  let metresPerUnit = FALLBACK_METRES_PER_UNIT
  const diameters: number[] = []
  for (const key of ['Unity Node', 'Harmony Node']) {
    const node = findNode(model, key)
    const extents = node ? hullExtents(node, [frame.lateral, frame.up]) : null
    if (extents) diameters.push(...extents)
  }
  if (diameters.length > 0) {
    metresPerUnit = NODE_DIAMETER_M / (diameters.reduce((sum, d) => sum + d, 0) / diameters.length)
  }

  const hull: Mesh[] = []
  const hullByModule: Record<string, Mesh[]> = {}
  for (const [node, key] of nodes) {
    const meshes = node.children.filter((child): child is Mesh => (child as Mesh).isMesh)
    hullByModule[key] = meshes
    hull.push(...meshes)
  }

  return { rooms, corridors, frame, metresPerUnit, hull, hullByModule }
}
