import { Matrix3, Vector3, type BufferGeometry, type Material, type Matrix4, type Mesh } from 'three'
import { DRACOLoader } from 'three/addons/loaders/DRACOLoader.js'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js'
import type { RawMesh } from './astronautModel'

/** Local copy of three's Draco WASM decoder (public/draco). No network. */
const DRACO_DECODER_PATH = './draco/'

export interface AstronautSource {
  /** The suit: the largest mesh, with its own colour texture from the GLB. */
  body: RawMesh
  /** The visor and other small head pieces (the second material). */
  visor: RawMesh | null
  bodyMaterial: Material
  visorMaterial: Material | null
}

const vertexCount = (mesh: Mesh) => mesh.geometry.getAttribute('position')?.count ?? 0

/** The mesh's triangles in world space (the matrix of the node chain, including the root rotation). */
function toWorld(geometry: BufferGeometry, matrix: Matrix4): RawMesh {
  const position = geometry.getAttribute('position')
  const out = new Float32Array(position.count * 3)
  const v = new Vector3()
  for (let i = 0; i < position.count; i++) {
    v.fromBufferAttribute(position, i).applyMatrix4(matrix)
    out[i * 3] = v.x
    out[i * 3 + 1] = v.y
    out[i * 3 + 2] = v.z
  }
  let normal: Float32Array | null = null
  const normals = geometry.getAttribute('normal')
  if (normals) {
    normal = new Float32Array(normals.count * 3)
    const normalMatrix = new Matrix3().getNormalMatrix(matrix)
    for (let i = 0; i < normals.count; i++) {
      v.fromBufferAttribute(normals, i).applyNormalMatrix(normalMatrix)
      normal[i * 3] = v.x
      normal[i * 3 + 1] = v.y
      normal[i * 3 + 2] = v.z
    }
  }
  const uvs = geometry.getAttribute('uv')
  const uv = uvs ? Float32Array.from(uvs.array as ArrayLike<number>) : null
  const index = geometry.index ? (geometry.index.array as ArrayLike<number>) : null
  return { position: out, normal, uv, index }
}

/**
 * Loads the NASA astronaut GLB (Draco, WebP textures) and returns its meshes in world space, with their materials.
 * The colour textures come from the GLB itself.
 */
export async function loadAstronautSource(url: string): Promise<AstronautSource> {
  const draco = new DRACOLoader().setDecoderPath(DRACO_DECODER_PATH)
  try {
    const gltf = await new GLTFLoader().setDRACOLoader(draco).setMeshoptDecoder(MeshoptDecoder).loadAsync(url)
    gltf.scene.updateMatrixWorld(true)
    const meshes: Mesh[] = []
    gltf.scene.traverse((node) => {
      if ((node as Mesh).isMesh) meshes.push(node as Mesh)
    })
    const suitMeshes = [...meshes]
    suitMeshes.sort((a, b) => vertexCount(b) - vertexCount(a))
    const body = suitMeshes[0]
    if (!body) throw new Error('astronaut: the GLB has no mesh')
    const visor = suitMeshes[1] ?? null
    return {
      body: toWorld(body.geometry, body.matrixWorld),
      visor: visor ? toWorld(visor.geometry, visor.matrixWorld) : null,
      bodyMaterial: body.material as Material,
      visorMaterial: visor ? (visor.material as Material) : null,
    }
  } finally {
    draco.dispose()
  }
}
