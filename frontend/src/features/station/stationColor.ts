import { CanvasTexture, RepeatWrapping, SRGBColorSpace, type Material, type Mesh, type MeshStandardMaterial, type Object3D } from 'three'

/**
 * Colour for the station's surfaces. The GLB's own colour maps are kept; a surface without one gets this procedural
 * texture: light grey panels, slightly different in tone, with seams and rivets. Drawn on a canvas, so it needs no
 * file, no network, and no decoding. Generated once and shared by every surface.
 */

const SIZE = 512
const CELLS = 4

/** Deterministic tone per panel, so the texture is the same on every load. */
function toneOf(i: number, j: number): number {
  const h = Math.sin((i * 12.9898 + j * 78.233) * 43758.5453)
  return h - Math.floor(h) // 0..1
}

/** A light grey panel texture, or null when no canvas is available. */
export function createPanelTexture(): CanvasTexture | null {
  if (typeof document === 'undefined') return null
  const canvas = document.createElement('canvas')
  canvas.width = SIZE
  canvas.height = SIZE
  const ctx = canvas.getContext('2d')
  if (!ctx) return null
  const cell = SIZE / CELLS
  for (let i = 0; i < CELLS; i++) {
    for (let j = 0; j < CELLS; j++) {
      const v = Math.round(206 + toneOf(i, j) * 24) // 206..230
      ctx.fillStyle = `rgb(${v}, ${v + 4}, ${v + 10})`
      ctx.fillRect(i * cell, j * cell, cell, cell)
    }
  }
  ctx.strokeStyle = '#7f8995'
  ctx.lineWidth = 2
  for (let k = 0; k <= CELLS; k++) {
    ctx.beginPath()
    ctx.moveTo(k * cell, 0)
    ctx.lineTo(k * cell, SIZE)
    ctx.moveTo(0, k * cell)
    ctx.lineTo(SIZE, k * cell)
    ctx.stroke()
  }
  ctx.fillStyle = '#6b7580'
  for (let i = 0; i < CELLS; i++) {
    for (let j = 0; j < CELLS; j++) {
      for (const [dx, dy] of [[0.12, 0.12], [0.88, 0.12], [0.12, 0.88], [0.88, 0.88]] as const) {
        ctx.beginPath()
        ctx.arc((i + dx) * cell, (j + dy) * cell, 3, 0, Math.PI * 2)
        ctx.fill()
      }
    }
  }
  const texture = new CanvasTexture(canvas)
  texture.colorSpace = SRGBColorSpace
  texture.wrapS = RepeatWrapping
  texture.wrapT = RepeatWrapping
  return texture
}

/** Gives the texture to every standard material of the meshes that has no colour map of its own. */
export function applyPanelTexture(meshes: readonly Object3D[], texture: CanvasTexture): void {
  const seen = new Set<Material>()
  for (const node of meshes) {
    const mesh = node as Mesh
    if (!mesh.isMesh) continue
    for (const material of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) {
      if (seen.has(material)) continue
      seen.add(material)
      const standard = material as MeshStandardMaterial
      if (!standard.isMeshStandardMaterial || standard.map) continue
      standard.map = texture
      standard.needsUpdate = true
    }
  }
}
