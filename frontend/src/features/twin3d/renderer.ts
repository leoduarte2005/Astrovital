import {
  ACESFilmicToneMapping,
  Box3,
  DirectionalLight,
  Group,
  HemisphereLight,
  MathUtils,
  PerspectiveCamera,
  Scene,
  Vector3,
  WebGLRenderer,
  type Material,
  type Mesh,
  type MeshStandardMaterial,
  Object3D,
  type Texture,
} from 'three'
import { GLTFLoader, type GLTF } from 'three/addons/loaders/GLTFLoader.js'
import { DRACOLoader } from 'three/addons/loaders/DRACOLoader.js'
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js'
import { placeMarker } from '@/ui/Marker/placeMarker'
import { setMarkerActive } from '@/ui/Marker/setMarkerActive'
import { DEFAULT_TWIN_LAYERS, TWIN_ANCHORS, TWIN_LAYER_IDS, type TwinAnchorId, type TwinLayerId } from './anchors'

/** Relative paths: the central (or the dev middleware) serves `data/models` under `/models`. */
const LAYER_URLS: Record<TwinLayerId, string> = {
  skin: './models/anatomy/skin.glb',
  bones: './models/anatomy/bones-compressed.glb', // Draco
  organs: './models/anatomy/organs.glb', // loaded on demand, when a marker selects it
  heart: './models/reduced/heart.glb', // meshopt; same body origin, no repositioning
  brain: './models/reduced/brain.glb', // meshopt
  lungs: './models/reduced/lungs.glb', // meshopt
}
/** Local copy of three's Draco WASM decoder (public/draco). No network. */
const DRACO_DECODER_PATH = './draco/'

async function loadGltf(url: string): Promise<GLTF> {
  const draco = new DRACOLoader().setDecoderPath(DRACO_DECODER_PATH)
  try {
    return await new GLTFLoader().setDRACOLoader(draco).setMeshoptDecoder(MeshoptDecoder).loadAsync(url)
  } finally {
    draco.dispose()
  }
}

const FRAME_MS = 1000 / 30 // fixed 30 fps target (see performance.md)
const MAX_PIXEL_RATIO = 2
const SPIN_RAD_PER_SECOND = 0.2 // ~31 s per turn, around the vertical axis
const FIT_MARGIN = 1.08
const ZOOM_DISTANCE = 0.25 // camera distance at the end of the zoom, as a fraction of the framed distance
const ZOOM_MS = 450
// Body turn during a zoom, seen from above: -20 is clockwise (three.js counts positive Y as counter-clockwise).
const ZOOM_TURN_DEG = -20
const DRAG_RAD_PER_PX = 0.01
const DRAG_MAX_TILT_RAD = Math.PI / 2 // vertical drag tilts up to 90 degrees, so the body never flips
const DOUBLE_TAP_MS = 300
const TAP_SLOP_PX = 8 // movement beyond this is a drag, not a tap
/** Base colour per layer, applied only to materials without a texture (a texture keeps its own colours). */
const LAYER_TINTS: Partial<Record<TwinLayerId, string>> = {
  heart: '#c8283f',
  brain: '#ffc0cb',
  lungs: '#d4a5a0',
}
/** Skin opacity while an organ is selected: a ghost that keeps the body outline over the organ. */
const SKIN_GHOST_OPACITY = 0.1

// Studio lights (scene values, not UI tokens).
const LIGHT_PAPER = 0xf9f8f2
const LIGHT_GROUND = 0x353a3e

export interface TwinOptions {
  /** CSS hex applied to the skin materials. Nails and ligaments keep their own colours. */
  skinTone: string
  /** Aborted by the caller when this mount is stale; checked before any GL object is created. */
  signal: AbortSignal
  /** HTML markers by anchor id; moved each frame by projection, never by React state. */
  markers: Partial<Record<TwinAnchorId, HTMLElement>>
}

export interface TwinRenderer {
  dispose(): void
}

// Duck-typed checks (`isMesh`, `isTexture`...): they keep working even if the bundler ends up
// with two copies of three, where `instanceof` would silently fail.
function isTexture(value: unknown): value is Texture {
  return typeof value === 'object' && value !== null && 'isTexture' in value
}

function meshMaterials(node: Object3D): Material[] | null {
  const mesh = node as Mesh
  if (!mesh.isMesh) return null
  return Array.isArray(mesh.material) ? mesh.material : [mesh.material]
}

function disposeObject(root: Object3D): void {
  root.traverse((node) => {
    const materials = meshMaterials(node)
    if (!materials) return
    ;(node as Mesh).geometry.dispose()
    for (const material of materials) {
      for (const value of Object.values(material)) {
        if (isTexture(value)) value.dispose()
      }
      material.dispose()
    }
  })
}

/** The skin materials ship with emissive = 1, which would render the body flat white. */
function neutralizeEmissive(root: Object3D): void {
  root.traverse((node) => {
    for (const material of meshMaterials(node) ?? []) {
      const standard = material as MeshStandardMaterial
      if (standard.isMeshStandardMaterial) {
        standard.emissive.setScalar(0)
        standard.emissiveIntensity = 0
      }
    }
  })
}

function tintUntextured(root: Object3D, color: string): void {
  root.traverse((node) => {
    for (const material of meshMaterials(node) ?? []) {
      const standard = material as MeshStandardMaterial
      if (standard.isMeshStandardMaterial && !standard.map) standard.color.set(color)
    }
  })
}

/** Fades every material of a layer. Faded materials stop writing depth, so what lies behind them still draws. */
function setLayerOpacity(root: Object3D, opacity: number): void {
  root.traverse((node) => {
    for (const material of meshMaterials(node) ?? []) {
      material.transparent = opacity < 1
      material.opacity = opacity
      material.depthWrite = opacity >= 1
    }
  })
}

function applySkinTone(root: Object3D, skinTone: string): void {
  root.traverse((node) => {
    for (const material of meshMaterials(node) ?? []) {
      const standard = material as MeshStandardMaterial
      if (standard.isMeshStandardMaterial && material.name.startsWith('Skin')) {
        standard.color.set(skinTone)
      }
    }
  })
}

/**
 * Showroom turntable of the body: no user input, slow rotation around Y.
 * Resolves once the default layers are loaded and framed; the caller owns `dispose()`.
 */
export async function mount(canvas: HTMLCanvasElement, options: TwinOptions): Promise<TwinRenderer> {
  const [skinGltf, bonesGltf] = await Promise.all([new GLTFLoader().loadAsync(LAYER_URLS.skin), loadGltf(LAYER_URLS.bones)])
  // Every layer is a child of `body`: they share one coordinate space, transform and centring.
  const body = new Group()
  const layers: Partial<Record<TwinLayerId, Object3D>> = { skin: skinGltf.scene, bones: bonesGltf.scene }
  body.add(skinGltf.scene, bonesGltf.scene)
  let disposed = false
  if (options.signal.aborted) {
    disposeObject(body)
    throw new DOMException('Twin mount aborted', 'AbortError')
  }

  let renderer: WebGLRenderer | null = null
  try {
    neutralizeEmissive(body)
    applySkinTone(body, options.skinTone)

    const box = new Box3().setFromObject(body)
    const size = box.getSize(new Vector3())
    const center = box.getCenter(new Vector3())
    // Anchors are children of the body, so they turn with it. Set in model units before the
    // re-centring below: after `body.position.sub(center)` the GLB middle is the canvas origin.
    const anchors = TWIN_ANCHORS.flatMap((anchor) => {
      const element = options.markers[anchor.id]
      if (!element) return []
      const object = new Object3D()
      object.name = `anchor-${anchor.id}`
      object.position.set(center.x + anchor.offset.x, center.y + anchor.offset.y, center.z + anchor.offset.z)
      body.add(object)
      return [{ object, element, layerIds: anchor.layers }]
    })
    body.position.sub(center)
    // Radius of the horizontal footprint: worst case while the body turns.
    const radius = Math.hypot(size.x, size.z) / 2

    const pivot = new Group()
    pivot.add(body)
    const scene = new Scene()
    scene.add(pivot)
    scene.add(new HemisphereLight(LIGHT_PAPER, LIGHT_GROUND, 0.35))
    const key = new DirectionalLight(LIGHT_PAPER, 1.1)
    key.position.set(2, 3, 4)
    const rim = new DirectionalLight(LIGHT_PAPER, 0.7)
    rim.position.set(-3, 2, -3)
    scene.add(key, rim)

    const camera = new PerspectiveCamera(30, 1, 0.1, 50)
    const webgl = new WebGLRenderer({ canvas, antialias: true })
    renderer = webgl
    // Opaque background taken from the page token, so it never depends on alpha compositing.
    const pageBg = getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()
    webgl.setClearColor(pageBg || LIGHT_GROUND, 1)
    webgl.toneMapping = ACESFilmicToneMapping
    webgl.toneMappingExposure = 0.8

    // Layers: show the ones of the selected marker. Missing ones load first; until then the current ones stay.
    const applyLayers = (ids: readonly TwinLayerId[]) => {
      for (const id of TWIN_LAYER_IDS) {
        const root = layers[id]
        if (!root) continue
        if (id === 'skin') {
          // The skin never hides: with an organ selected it fades to a ghost instead.
          root.visible = true
          setLayerOpacity(root, ids.includes('skin') ? 1 : SKIN_GHOST_OPACITY)
        } else {
          root.visible = ids.includes(id)
        }
      }
    }
    const loadLayer = async (id: TwinLayerId) => {
      if (layers[id]) return
      const gltf = await loadGltf(LAYER_URLS[id])
      if (disposed) {
        disposeObject(gltf.scene)
        return
      }
      neutralizeEmissive(gltf.scene)
      const tint = LAYER_TINTS[id]
      if (tint) tintUntextured(gltf.scene, tint)
      gltf.scene.visible = false
      body.add(gltf.scene)
      layers[id] = gltf.scene
    }
    applyLayers(DEFAULT_TWIN_LAYERS)

    const halfFov = MathUtils.degToRad(camera.fov) / 2
    let framedDistance = 0
    const fitCamera = () => {
      const fromHeight = size.y / 2 / Math.tan(halfFov) + radius
      const fromWidth = radius / (Math.tan(halfFov) * camera.aspect) + radius
      framedDistance = Math.max(fromHeight, fromWidth) * FIT_MARGIN
    }

    // Click on a marker: the camera moves towards it and the view centres on it. The turntable turns to ZOOM_TURN_DEG and stops.
    // Camera blend: 0 = framed view, 1 = zoomed in. It eases from `blendFrom` to `blendTo` starting at `zoomStartedAt`.
    let zoomAnchor: Object3D | null = null // selected marker; null when nothing is selected
    let viewAnchor: Object3D | null = null // the view centres on it; kept while the camera blends back
    let viewMarker: HTMLElement | null = null
    let zoomStartedAt = 0
    let blendFrom = 0
    let blendTo = 0
    let zoomFromAngle = 0
    let zoomToAngle = 0
    let zoomTurnSettled = false
    const zoomTarget = new Vector3()
    const easeNow = () => 1 - (1 - Math.min(1, (performance.now() - zoomStartedAt) / ZOOM_MS)) ** 3 // ease-out cubic
    const blendNow = () => blendFrom + (blendTo - blendFrom) * easeNow()
    const startZoom = (object: Object3D, layerIds: readonly TwinLayerId[], element: HTMLElement) => {
      if (zoomAnchor) return
      zoomAnchor = object
      viewAnchor = object
      viewMarker = element
      setMarkerActive(element, true)
      blendFrom = blendNow()
      blendTo = 1
      zoomTurnSettled = false
      zoomStartedAt = reducedMotion.matches ? -Infinity : performance.now()
      // Shortest turn from the current angle to the target angle (the pivot accumulates rotation).
      zoomFromAngle = pivot.rotation.y
      const delta = MathUtils.euclideanModulo(MathUtils.degToRad(ZOOM_TURN_DEG) - zoomFromAngle + Math.PI, Math.PI * 2) - Math.PI
      zoomToAngle = zoomFromAngle + delta
      draw()
      Promise.all(layerIds.map(loadLayer)).then(
        () => {
          if (disposed) return
          applyLayers(layerIds)
          draw()
        },
        (error: unknown) => console.warn('Twin layer failed to load', error),
      )
    }
    // Drag turns the body, only once the zoom has settled. Auto-rotate stays off after a selection.
    let dragLast: { x: number; y: number } | null = null
    const settleZoomTurn = () => {
      zoomTurnSettled = true
      canvas.style.pointerEvents = 'auto'
      canvas.style.touchAction = 'none'
      canvas.style.cursor = 'grab'
    }
    // Double-tap (mouse or touch) on the canvas reverses the selection. Taps are detected on pointerup.
    let tapDown: { x: number; y: number } | null = null
    let lastTap: { x: number; y: number; at: number } | null = null
    const onPointerDown = (event: PointerEvent) => {
      tapDown = { x: event.clientX, y: event.clientY }
      if (!zoomTurnSettled) return
      dragLast = { x: event.clientX, y: event.clientY }
      canvas.setPointerCapture(event.pointerId)
    }
    const onPointerMove = (event: PointerEvent) => {
      if (dragLast === null) return
      // Horizontal drag turns around Y; vertical drag tilts around X, limited so the body never flips.
      pivot.rotation.y += (event.clientX - dragLast.x) * DRAG_RAD_PER_PX
      pivot.rotation.x = MathUtils.clamp(
        pivot.rotation.x + (event.clientY - dragLast.y) * DRAG_RAD_PER_PX,
        -DRAG_MAX_TILT_RAD,
        DRAG_MAX_TILT_RAD,
      )
      dragLast = { x: event.clientX, y: event.clientY }
      draw()
    }
    const releasePointer = (event: PointerEvent) => {
      dragLast = null
      if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId)
    }
    const onPointerUp = (event: PointerEvent) => {
      releasePointer(event)
      const down = tapDown
      tapDown = null
      if (!down || Math.hypot(event.clientX - down.x, event.clientY - down.y) > TAP_SLOP_PX) return
      const now = performance.now()
      const previous = lastTap
      if (previous && now - previous.at < DOUBLE_TAP_MS && Math.hypot(event.clientX - previous.x, event.clientY - previous.y) <= TAP_SLOP_PX) {
        lastTap = null
        resetView()
      } else {
        lastTap = { x: event.clientX, y: event.clientY, at: now }
      }
    }
    const onPointerCancel = (event: PointerEvent) => {
      tapDown = null
      releasePointer(event)
    }
    canvas.addEventListener('pointerdown', onPointerDown)
    canvas.addEventListener('pointermove', onPointerMove)
    canvas.addEventListener('pointerup', onPointerUp)
    canvas.addEventListener('pointercancel', onPointerCancel)

    const disableDrag = () => {
      zoomTurnSettled = false
      canvas.style.pointerEvents = ''
      canvas.style.touchAction = ''
      canvas.style.cursor = ''
    }
    // Reverses the selection: organ layers go back to the default, the camera blends back to the framed view,
    // the tilt resets and auto-rotate resumes (tick only spins while nothing is selected).
    const resetView = () => {
      if (!zoomAnchor) return
      zoomAnchor = null
      if (viewMarker) setMarkerActive(viewMarker, false)
      viewMarker = null
      blendFrom = blendNow()
      blendTo = 0
      zoomStartedAt = reducedMotion.matches ? -Infinity : performance.now()
      dragLast = null
      disableDrag()
      pivot.rotation.x = 0
      applyLayers(DEFAULT_TWIN_LAYERS)
      draw()
    }

    const updateCamera = () => {
      if (framedDistance === 0) return
      const eased = easeNow()
      const t = blendFrom + (blendTo - blendFrom) * eased
      if (zoomAnchor && !zoomTurnSettled) {
        pivot.rotation.y = zoomFromAngle + (zoomToAngle - zoomFromAngle) * eased
        if (eased >= 1) settleZoomTurn()
      }
      if (viewAnchor) viewAnchor.getWorldPosition(zoomTarget).multiplyScalar(t) // lerp from the GLB middle to the anchor
      else zoomTarget.set(0, 0, 0)
      const distance = framedDistance * (1 - (1 - ZOOM_DISTANCE) * t)
      camera.position.set(zoomTarget.x, zoomTarget.y, zoomTarget.z + distance)
      camera.lookAt(zoomTarget)
    }

    const anchorWorld = new Vector3()
    const anchorNdc = new Vector3()
    // Projects every anchor into CSS pixels. Markers stay visible whether the front faces the camera or not.
    const updateMarkers = () => {
      const width = canvas.clientWidth
      const height = canvas.clientHeight
      if (width === 0 || height === 0) return
      camera.updateMatrixWorld()
      for (const { object, element } of anchors) {
        // Once zoomed in, only the selected marker stays; the others are hidden and stop receiving pointer events.
        if (zoomAnchor && object !== zoomAnchor) {
          element.style.visibility = 'hidden'
          continue
        }
        object.getWorldPosition(anchorWorld)
        anchorNdc.copy(anchorWorld).project(camera)
        placeMarker(element, ((anchorNdc.x + 1) / 2) * width, ((1 - anchorNdc.y) / 2) * height)
      }
    }

    const draw = () => {
      updateCamera()
      updateMarkers()
      webgl.render(scene, camera)
    }

    const resize = () => {
      const width = canvas.clientWidth
      const height = canvas.clientHeight
      if (width === 0 || height === 0) return
      webgl.setPixelRatio(Math.min(window.devicePixelRatio, MAX_PIXEL_RATIO))
      webgl.setSize(width, height, false)
      camera.aspect = width / height
      camera.updateProjectionMatrix()
      fitCamera()
      draw()
    }

    let frame = 0
    let last = 0
    const tick = (now: number) => {
      frame = requestAnimationFrame(tick)
      const elapsed = now - last
      if (elapsed < FRAME_MS - 1) return
      last = now
      // The turntable stops once a marker has been zoomed into (see twin3d.md).
      if (!zoomAnchor) pivot.rotation.y += SPIN_RAD_PER_SECOND * (Math.min(elapsed, 100) / 1000)
      draw()
    }
    const start = () => {
      if (frame !== 0) return
      last = performance.now()
      frame = requestAnimationFrame(tick)
    }
    const stop = () => {
      cancelAnimationFrame(frame)
      frame = 0
    }

    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)')
    const sync = () => {
      if (reducedMotion.matches || document.hidden) {
        stop()
        draw()
      } else {
        start()
      }
    }

    const markerClicks = anchors.map(({ object, element, layerIds }) => {
      const onClick = () => startZoom(object, layerIds, element)
      element.addEventListener('click', onClick)
      return { element, onClick }
    })

    const observer = new ResizeObserver(resize)
    observer.observe(canvas)
    document.addEventListener('visibilitychange', sync)
    reducedMotion.addEventListener('change', sync)
    resize()
    sync()

    return {
      dispose() {
        disposed = true
        stop()
        for (const { element, onClick } of markerClicks) element.removeEventListener('click', onClick)
        canvas.removeEventListener('pointerdown', onPointerDown)
        canvas.removeEventListener('pointermove', onPointerMove)
        canvas.removeEventListener('pointerup', onPointerUp)
        canvas.removeEventListener('pointercancel', onPointerCancel)
        canvas.style.pointerEvents = ''
        canvas.style.touchAction = ''
        canvas.style.cursor = ''
        observer.disconnect()
        document.removeEventListener('visibilitychange', sync)
        reducedMotion.removeEventListener('change', sync)
        disposeObject(body)
        // No forceContextLoss(): React StrictMode remounts reuse this canvas, and a lost context is permanent.
        webgl.dispose()
      },
    }
  } catch (error) {
    disposed = true
    disposeObject(body)
    renderer?.dispose()
    throw error
  }
}
