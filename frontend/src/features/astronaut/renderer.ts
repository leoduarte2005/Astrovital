import {
  ACESFilmicToneMapping,
  Box3,
  Color,
  DirectionalLight,
  GridHelper,
  HemisphereLight,
  MathUtils,
  Mesh,
  PerspectiveCamera,
  Scene,
  Texture,
  Vector3,
  WebGLRenderer,
  type LineBasicMaterial,
  type Material,
} from 'three'
import { DRACOLoader } from 'three/addons/loaders/DRACOLoader.js'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js'
import { ASTRONAUT_CAMERA_LIFT, ASTRONAUT_FIT_MARGIN, STUDIO_LIGHT } from '@/lib/model/astronaut/view'

/** Relative path: the central (or the dev middleware) serves `data/models` under `/models`. The model is shown as it is. */
const MODEL_URL = './models/astronaut/Astronaut.glb'
/** Local copy of three's Draco WASM decoder (public/draco). No network. */
const DRACO_DECODER_PATH = './draco/'

const MAX_PIXEL_RATIO = 2
const FOV_DEG = 35
/** The model fills the viewer's height with a small margin; the grid floor sits under the feet. Shared with the twin's intro. */
const FIT_MARGIN = ASTRONAUT_FIT_MARGIN
const CAMERA_LIFT = ASTRONAUT_CAMERA_LIFT
const FLOOR_OPACITY = 0.16
/** Fallback for the `--ink-3` token (see styles/tokens.css). */
const FLOOR_COLOR_FALLBACK = '#adaea9'
const FLOOR_DIVISIONS = 12

/**
 * Mounts the astronaut GLB, as it is, in `host` (a canvas is added to it), and returns its disposer. Static: one frame,
 * drawn again only when the viewer resizes. The model stands at the centre of the box, framed by its height; a narrow
 * viewer frames by width instead.
 */
export async function mountAstronaut(host: HTMLElement): Promise<() => void> {
  const draco = new DRACOLoader().setDecoderPath(DRACO_DECODER_PATH)
  let gltf
  try {
    gltf = await new GLTFLoader().setDRACOLoader(draco).setMeshoptDecoder(MeshoptDecoder).loadAsync(MODEL_URL)
  } finally {
    draco.dispose()
  }

  const model = gltf.scene
  const box = new Box3().setFromObject(model)
  const size = box.getSize(new Vector3())
  model.position.sub(box.getCenter(new Vector3()))

  const scene = new Scene()
  scene.add(model)
  // The studio light of the twin (lib/model/astronaut/view.ts): the suit looks the same in the intro.
  scene.add(new HemisphereLight(STUDIO_LIGHT.paper, STUDIO_LIGHT.ground, STUDIO_LIGHT.hemisphere))
  const key = new DirectionalLight(STUDIO_LIGHT.paper, STUDIO_LIGHT.key)
  key.position.set(...STUDIO_LIGHT.keyFrom)
  const rim = new DirectionalLight(STUDIO_LIGHT.paper, STUDIO_LIGHT.rim)
  rim.position.set(...STUDIO_LIGHT.rimFrom)
  scene.add(key, rim)

  // Grid floor under the feet, in the page's --ink-3 at low opacity (as the twin's floor).
  const pageInk = getComputedStyle(document.documentElement).getPropertyValue('--ink-3').trim()
  const floorColor = new Color(pageInk || FLOOR_COLOR_FALLBACK)
  const floor = new GridHelper(Math.max(size.x, size.z) * 2.4, FLOOR_DIVISIONS, floorColor, floorColor)
  floor.position.y = -size.y / 2
  const floorMaterial = floor.material as LineBasicMaterial
  floorMaterial.transparent = true
  floorMaterial.opacity = FLOOR_OPACITY
  floorMaterial.depthWrite = false
  scene.add(floor)

  const camera = new PerspectiveCamera(FOV_DEG, 1, 0.01, 100)
  // Transparent canvas: the page background (--bg) shows through.
  const renderer = new WebGLRenderer({ antialias: true, alpha: true })
  renderer.toneMapping = ACESFilmicToneMapping
  renderer.toneMappingExposure = STUDIO_LIGHT.exposure
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, MAX_PIXEL_RATIO))
  host.appendChild(renderer.domElement)

  const fit = () => {
    const width = host.clientWidth
    const height = host.clientHeight
    if (!width || !height) return
    renderer.setSize(width, height, false)
    camera.aspect = width / height
    const vfov = MathUtils.degToRad(camera.fov)
    const hfov = 2 * Math.atan(Math.tan(vfov / 2) * camera.aspect)
    const byHeight = (size.y * FIT_MARGIN) / 2 / Math.tan(vfov / 2)
    const byWidth = (size.x * FIT_MARGIN) / 2 / Math.tan(hfov / 2)
    const distance = Math.max(byHeight, byWidth)
    // The GLB is about 74 units tall (its units are not metres): the planes follow the framed distance, or the model is clipped.
    camera.near = distance / 100
    camera.far = distance * 100
    camera.position.set(0, distance * CAMERA_LIFT, distance)
    camera.lookAt(0, 0, 0)
    camera.updateProjectionMatrix()
  }

  const draw = () => renderer.render(scene, camera)
  const observer = new ResizeObserver(() => {
    fit()
    draw()
  })
  observer.observe(host)

  return () => {
    observer.disconnect()
    scene.traverse((node) => {
      if (!(node instanceof Mesh)) return
      node.geometry.dispose()
      const materials = Array.isArray(node.material) ? node.material : [node.material]
      for (const material of materials as Material[]) {
        for (const value of Object.values(material)) {
          if (value instanceof Texture) value.dispose()
        }
        material.dispose()
      }
    })
    floor.geometry.dispose()
    floorMaterial.dispose()
    renderer.dispose()
    renderer.domElement.remove()
  }
}
