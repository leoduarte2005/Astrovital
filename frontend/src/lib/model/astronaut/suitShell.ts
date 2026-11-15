import { BufferAttribute, BufferGeometry, Box3, DoubleSide, Group, Mesh, MathUtils, Vector3, type Material, type Texture } from 'three'
import { loadAstronautSource, type AstronautSource } from './astronautLoader'
import { splitAstronaut } from './astronautModel'

/**
 * The astronaut suit as a shell around the digital twin. It starts in the GLB's T-pose, the arms come down to rest
 * beside the body (as the skin model), then the suit is cut at the waist by a straight plane. The upper half lifts and
 * the lower half drops, linearly, like an egg opening, and the body inside shows. The cut is clipped, not split by
 * centroid, so the edge is straight. No physics. The caller owns the scene, the clock and `dispose()`.
 */

/**
 * Shoulder pivots in the suit's world units, measured from the suit mesh (Draco decoded, read only): the arm's axis at
 * its inner end, where the tube is about 3.5 units in radius. Not the joints of `astronautModel.ts` (used by the station).
 */
const SHOULDER: Record<'armLeft' | 'armRight', Vector3> = {
  armLeft: new Vector3(-13.5, 17.7, 3.4),
  armRight: new Vector3(13.5, 17.7, 3.4),
}

/** Waist, in the suit's units, relative to its centre. Estimated between the shoulder joints (y 14) and the hip joints (y -14): check visually. */
const WAIST_Y = -4
/** Arms lowered: 20 degrees from the vertical, outward, as the skin model. Positive turns the left arm (-X) down, negative the right (+X). */
const LEFT_ARM_LOWERED = MathUtils.degToRad(70)
const RIGHT_ARM_LOWERED = MathUtils.degToRad(-70)
/** Split: the upper half rises and the lower half drops, by these fractions of the suit's height, at the end. */
const TOP_RISE = 0.3
const BOTTOM_DROP = 0.1
/** The halves fade out over the last part of the split, so they do not pop out of sight. */
const FADE_FROM = 0.7

export interface SuitShell {
  /** Suit units, centred on the origin, front on +Z. Scale it to the body, then add it to the scene. */
  group: Group
  /** Height of the whole suit in its own units. */
  height: number
  /** `arms` 0..1 lowers the arms (eased); `split` 0..1 parts the halves (linear). */
  update(arms: number, split: number): void
  dispose(): void
}

/** Flat triangle soup: 9 position numbers per triangle, 9 normal and 6 uv when present. */
interface Soup {
  position: number[]
  normal: number[] | null
  uv: number[] | null
}

interface MeshLike {
  position: ArrayLike<number>
  normal?: ArrayLike<number> | null
  uv?: ArrayLike<number> | null
  index?: ArrayLike<number> | null
}

function flatten(mesh: MeshLike): Soup {
  const index = mesh.index ?? null
  const count = index ? index.length : mesh.position.length / 3
  const hasNormal = !!mesh.normal && mesh.normal.length > 0
  const hasUv = !!mesh.uv && mesh.uv.length > 0
  const soup: Soup = { position: [], normal: hasNormal ? [] : null, uv: hasUv ? [] : null }
  for (let k = 0; k < count; k++) {
    const v = index ? (index[k] ?? 0) : k
    soup.position.push(mesh.position[v * 3] ?? 0, mesh.position[v * 3 + 1] ?? 0, mesh.position[v * 3 + 2] ?? 0)
    if (soup.normal && mesh.normal) soup.normal.push(mesh.normal[v * 3] ?? 0, mesh.normal[v * 3 + 1] ?? 0, mesh.normal[v * 3 + 2] ?? 0)
    if (soup.uv && mesh.uv) soup.uv.push(mesh.uv[v * 2] ?? 0, mesh.uv[v * 2 + 1] ?? 0)
  }
  return soup
}

function emptySoup(like: Soup): Soup {
  return { position: [], normal: like.normal ? [] : null, uv: like.uv ? [] : null }
}

/** A vertex of a clipped polygon: position, and its normal and uv interpolated along the cut. */
interface Vert {
  p: number[]
  n: number[] | null
  uv: number[] | null
}

function lerpArray(a: number[], b: number[], t: number): number[] {
  return a.map((x, i) => x + ((b[i] ?? x) - x) * t)
}

function lerpVert(a: Vert, b: Vert, t: number): Vert {
  return {
    p: lerpArray(a.p, b.p, t),
    n: a.n && b.n ? lerpArray(a.n, b.n, t) : null,
    uv: a.uv && b.uv ? lerpArray(a.uv, b.uv, t) : null,
  }
}

/** Sutherland-Hodgman against the half-space above (or below) the plane y = height. */
function clipPolygon(poly: Vert[], height: number, above: boolean): Vert[] {
  const side = (v: Vert) => (above ? v.p[1]! - height : height - v.p[1]!)
  const out: Vert[] = []
  for (let i = 0; i < poly.length; i++) {
    const a = poly[i]!
    const b = poly[(i + 1) % poly.length]!
    const da = side(a)
    const db = side(b)
    if (da >= 0) out.push(a)
    if ((da >= 0) !== (db >= 0)) out.push(lerpVert(a, b, da / (da - db)))
  }
  return out
}

function vertAt(soup: Soup, i: number): Vert {
  return {
    p: [soup.position[i * 3] ?? 0, soup.position[i * 3 + 1] ?? 0, soup.position[i * 3 + 2] ?? 0],
    n: soup.normal ? [soup.normal[i * 3] ?? 0, soup.normal[i * 3 + 1] ?? 0, soup.normal[i * 3 + 2] ?? 0] : null,
    uv: soup.uv ? [soup.uv[i * 2] ?? 0, soup.uv[i * 2 + 1] ?? 0] : null,
  }
}

/** Fan-triangulates a clipped polygon into `out`. */
function emit(out: Soup, poly: Vert[]): void {
  for (let k = 1; k + 1 < poly.length; k++) {
    for (const v of [poly[0]!, poly[k]!, poly[k + 1]!]) {
      out.position.push(...v.p)
      if (out.normal && v.n) out.normal.push(...v.n)
      if (out.uv && v.uv) out.uv.push(...v.uv)
    }
  }
}

/** Cuts a soup by the plane y = height: triangles crossing it are clipped, so the edge is straight. */
function cutAt(soup: Soup, height: number): { above: Soup; below: Soup } {
  const above = emptySoup(soup)
  const below = emptySoup(soup)
  for (let t = 0; t < soup.position.length / 9; t++) {
    const tri = [vertAt(soup, t * 3), vertAt(soup, t * 3 + 1), vertAt(soup, t * 3 + 2)]
    emit(above, clipPolygon(tri, height, true))
    emit(below, clipPolygon(tri, height, false))
  }
  return { above, below }
}

function appendSoup(target: Soup, extra: Soup): void {
  target.position.push(...extra.position)
  if (target.normal && extra.normal) target.normal.push(...extra.normal)
  if (target.uv && extra.uv) target.uv.push(...extra.uv)
}

function toGeometry(soup: Soup, offset: Vector3 = new Vector3()): BufferGeometry {
  const geometry = new BufferGeometry()
  geometry.setAttribute('position', new BufferAttribute(new Float32Array(soup.position), 3))
  if (soup.normal) geometry.setAttribute('normal', new BufferAttribute(new Float32Array(soup.normal), 3))
  if (soup.uv) geometry.setAttribute('uv', new BufferAttribute(new Float32Array(soup.uv), 2))
  geometry.translate(-offset.x, -offset.y, -offset.z)
  return geometry
}

function boundsOf(mesh: MeshLike): Box3 {
  const soup = flatten(mesh)
  const box = new Box3()
  const v = new Vector3()
  for (let i = 0; i < soup.position.length; i += 3) {
    box.expandByPoint(v.set(soup.position[i] ?? 0, soup.position[i + 1] ?? 0, soup.position[i + 2] ?? 0))
  }
  return box
}

function build(source: AstronautSource): SuitShell {
  const bounds = boundsOf(source.body)
  const centre = bounds.getCenter(new Vector3())
  const height = bounds.getSize(new Vector3()).y
  const cutY = centre.y + WAIST_Y

  // Materials: the halves are open, so both faces draw.
  const bodyMaterial = source.bodyMaterial.clone()
  bodyMaterial.side = DoubleSide
  const materials: Material[] = [bodyMaterial]
  let visorMaterial: Material | null = null
  if (source.visorMaterial) {
    visorMaterial = source.visorMaterial.clone()
    visorMaterial.side = DoubleSide
    materials.push(visorMaterial)
  }

  const top = new Group()
  const bottom = new Group()
  const root = new Group()
  root.position.copy(centre).multiplyScalar(-1)
  root.add(top, bottom)

  // Body torso and pelvis: cut at the waist. Legs lie below it, so they go to the lower half.
  const parts = splitAstronaut(source.body)
  const upperSoup: Soup = { position: [], normal: parts.body?.normal?.length ? [] : null, uv: parts.body?.uv?.length ? [] : null }
  const lowerSoup: Soup = { position: [], normal: upperSoup.normal ? [] : null, uv: upperSoup.uv ? [] : null }
  if (parts.body) {
    const cut = cutAt(flatten(parts.body), cutY)
    appendSoup(upperSoup, cut.above)
    appendSoup(lowerSoup, cut.below)
  }
  for (const leg of ['legLeft', 'legRight'] as const) {
    const data = parts[leg]
    if (!data) continue
    const cut = cutAt(flatten(data), cutY)
    appendSoup(upperSoup, cut.above)
    appendSoup(lowerSoup, cut.below)
  }
  if (upperSoup.position.length) top.add(new Mesh(toGeometry(upperSoup), bodyMaterial))
  if (lowerSoup.position.length) bottom.add(new Mesh(toGeometry(lowerSoup), bodyMaterial))

  // Visor: on the head, above the waist; cut anyway, in case the GLB differs.
  if (source.visor && visorMaterial) {
    const cut = cutAt(flatten(source.visor), cutY)
    if (cut.above.position.length) top.add(new Mesh(toGeometry(cut.above), visorMaterial))
    if (cut.below.position.length) bottom.add(new Mesh(toGeometry(cut.below), visorMaterial))
  }

  // Arms: rigid parts that turn about the shoulders, so they stay with the upper half.
  const arm = (part: 'armLeft' | 'armRight', target: number) => {
    const data = parts[part]
    if (!data) return null
    const joint = SHOULDER[part]
    // The pivot sits at the shoulder, in the suit's own frame (the root only applies the centring).
    const pivot = new Group()
    pivot.position.copy(joint)
    const mesh = new Mesh(toGeometry(flatten(data), joint), bodyMaterial)
    pivot.add(mesh)
    // The shoulder filler of this side is centred on the joint, so it stays in place while the arm turns and covers the opening.
    for (const shoulder of source.shoulders) {
      const centreX = boundsOf(shoulder).getCenter(new Vector3()).x
      if (Math.sign(centreX) === Math.sign(joint.x)) pivot.add(new Mesh(toGeometry(flatten(shoulder), joint), bodyMaterial))
    }
    top.add(pivot)
    return { pivot, target }
  }
  const arms = [arm('armLeft', LEFT_ARM_LOWERED), arm('armRight', RIGHT_ARM_LOWERED)].filter(
    (value): value is { pivot: Group; target: number } => value !== null,
  )

  const update = (armsT: number, split: number) => {
    const eased = 1 - (1 - MathUtils.clamp(armsT, 0, 1)) ** 3 // ease-out cubic for the arms
    for (const { pivot, target } of arms) pivot.rotation.z = target * eased
    const s = MathUtils.clamp(split, 0, 1) // linear for the split
    top.position.y = TOP_RISE * height * s
    bottom.position.y = -BOTTOM_DROP * height * s
    const opacity = 1 - MathUtils.smoothstep(s, FADE_FROM, 1)
    for (const material of materials) {
      material.transparent = opacity < 1
      material.opacity = opacity
      material.depthWrite = opacity >= 1
    }
  }
  update(0, 0)

  return {
    group: root,
    height,
    update,
    dispose() {
      root.traverse((node) => {
        if (node instanceof Mesh) node.geometry.dispose()
      })
      for (const material of [bodyMaterial, visorMaterial, source.bodyMaterial, source.visorMaterial]) {
        if (!material) continue
        for (const value of Object.values(material)) {
          // Duck-typed: it keeps working if the bundler ends up with two copies of three.
          if (typeof value === 'object' && value !== null && 'isTexture' in value) (value as Texture).dispose()
        }
        material.dispose()
      }
    },
  }
}

/** Loads the suit GLB (Draco, local decoder) and prepares its two halves. Rejects if the file cannot be loaded. */
export async function loadSuitShell(url: string): Promise<SuitShell> {
  return build(await loadAstronautSource(url))
}
