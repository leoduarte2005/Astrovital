import { DoubleSide, Mesh, MeshBasicMaterial, type Material } from 'three'

export interface FocusCleanOpacity {
  /** Opacity of the whole station at rest. */
  rest: number
  /** Opacity of the hulls while a section is in focus. */
  focus: number
}

export interface FocusClean {
  /** Switches the station to the focus look (true) or back to the resting look (false). Safe to call repeatedly. */
  apply(focused: boolean): void
  dispose(): void
}

// Duck-typed, as elsewhere: it keeps working if the bundler ends up with two copies of three.
function materialsOf(mesh: Mesh): Material[] {
  return Array.isArray(mesh.material) ? mesh.material : [mesh.material]
}

/**
 * Keeps a translucent station readable while a section is in focus. Two things, only in focus:
 *
 * 1. Everything that is not a pressurised hull (truss, solar arrays, radiators, arms) is hidden.
 * 2. The hulls are drawn with a depth pre-pass. Alpha blending sorts whole objects by their centre, and a module is
 *    several concentric shells with the same centre, so the order is arbitrary and inner layers show over outer ones.
 *    The pre-pass first writes the depth of every hull (no colour); the translucent pass then only draws where its
 *    surface is the nearest one, so each hull shows once, with no layers through each other.
 *
 * Only the given station meshes are touched: the crew and the guide lines, which are added to the model later, are not.
 * If no hull was found, nothing is hidden (the focus view would otherwise be empty) and only the opacity changes.
 */
export function createFocusClean(
  stationMeshes: readonly Mesh[],
  hull: readonly Mesh[],
  opacity: FocusCleanOpacity,
): FocusClean {
  const hullSet = new Set(hull)
  const others = stationMeshes.filter((mesh) => !hullSet.has(mesh))
  const isolate = hull.length > 0

  const materials = new Set<Material>()
  for (const mesh of stationMeshes) for (const material of materialsOf(mesh)) materials.add(material)
  const restDepthWrite = new Map<Material, boolean>([...materials].map((material) => [material, material.depthWrite]))

  // Depth only: no colour, both faces (the nearest one wins), pushed back a little so the translucent pass, which
  // draws the same triangles, passes the depth test instead of fighting with it.
  const prepassMaterial = new MeshBasicMaterial({
    colorWrite: false,
    side: DoubleSide,
    polygonOffset: true,
    polygonOffsetFactor: 1,
    polygonOffsetUnits: 1,
  })
  // A child of each hull mesh with the same geometry: it follows the mesh's transform and adds no geometry memory.
  const prepasses = isolate
    ? hull.map((mesh) => {
        const prepass = new Mesh(mesh.geometry, prepassMaterial)
        prepass.visible = false
        mesh.add(prepass)
        return prepass
      })
    : []

  const apply = (focused: boolean) => {
    const isolated = focused && isolate
    for (const material of materials) {
      material.transparent = true
      material.opacity = focused ? opacity.focus : opacity.rest
      // In focus the pre-pass owns the depth; at rest the materials go back to what the GLB gave them.
      material.depthWrite = isolated ? false : (restDepthWrite.get(material) ?? true)
    }
    for (const mesh of others) mesh.visible = !isolated
    for (const prepass of prepasses) prepass.visible = isolated
  }
  apply(false)

  return {
    apply,
    dispose() {
      for (const prepass of prepasses) prepass.removeFromParent()
      prepassMaterial.dispose()
    },
  }
}
