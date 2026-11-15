import {
  ACESFilmicToneMapping,
  BufferGeometry,
  Box3,
  DirectionalLight,
  Group,
  HemisphereLight,
  LineBasicMaterial,
  LineSegments,
  Matrix4,
  MathUtils,
  PerspectiveCamera,
  Scene,
  Vector3,
  WebGLRenderer,
  Object3D,
  type Material,
  type Mesh,
  type Texture,
} from 'three'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js'
import { placeMarker } from '@/ui/Marker/placeMarker'
import { setMarkerActive } from '@/ui/Marker/setMarkerActive'
import { STATION_SECTIONS, type SectionId } from './anchors'
import { ASTRONAUT_ROUTES } from './astronauts'
import { STATION_SENSORS, type StationSensor } from './sensors'
import { buildStationGraph } from './stationGraph'
import { wallPointAlong } from './wall'
import { applyPanelTexture, createPanelTexture } from './stationColor'
import { bakeAstronaut, splitAstronaut } from '@/lib/model/astronaut/astronautModel'
import { loadAstronautSource, type AstronautSource } from '@/lib/model/astronaut/astronautLoader'
import { createAstronaut, poseAstronaut, type AstronautMode, type AstronautRig } from './astronautMesh'
import { createFocusClean } from './focusClean'
import { Walkers } from './walkers'

/** Relative path: the dev middleware serves `data/models` under `/models`; the build copies this file to `dist/`. */
const STATION_URL = './models/iss/international_space_station.glb'
/** The NASA astronaut model: the crew avatars (see astronautModel.ts). */
const ASTRONAUT_URL = './models/astronaut/Astronaut.glb'

const FRAME_MS = 1000 / 30 // fixed 30 fps target (see performance.md)
const MAX_PIXEL_RATIO = 2
const SPIN_RAD_PER_SECOND = 0.06 // slower than the body twin (0.2): about 105 s per turn
/** Visible half-width of the frame, as a fraction of the station length, measured from its centre. */
const FRAME_HALF_WIDTH = 0.6
/** Model opacity at rest: slightly see-through, so the structure reads as a hologram over the page. */
const STATION_OPACITY = 0.9
/** Model opacity while a section is in focus: the model fades so the marker and its surroundings read. */
const FOCUS_OPACITY = 0.2
/** Guide lines along the corridors: simple cyan, drawn over the model, visible only in focus. */
const GUIDE_COLOR = 0x00e5ff
const GUIDE_OPACITY = 0.9
// Crew avatars: real-world sizes and speeds, in metres. The model's scale (about 28 m per unit) is read from the GLB.
const ASTRONAUT_HEIGHT_M = 1.8 * 0.9 // a 1.8 m adult scaled down 10%, so the crew reads against the tubes
const WALK_SPEED_M_S = 1.2 // peak drift speed along a corridor; each leg is a push-off, a glide and a slow stop
const WALK_SLOT_M = 1.0 // distance between crew sharing a room
const WALK_DWELL_MS = 2500
const WALK_MEET_MS = 5000
const WALK_TALK_MS = 2000
// Same zoom as the body twin (TwinCanvas): ease-out, 450 ms, camera at 25% of the framed distance.
const ZOOM_DISTANCE = 0.25
const ZOOM_MS = 450
const DOUBLE_TAP_MS = 300
const TAP_SLOP_PX = 8 // movement beyond this is a drag, not a tap
// Free rotation with the mouse in focus: the same as the body twin.
const DRAG_RAD_PER_PX = 0.01
const DRAG_MAX_TILT_RAD = Math.PI / 2 // vertical drag tilts up to 90 degrees, so the station never flips

// Studio lights (scene values, not UI tokens), as in the body twin.
const LIGHT_PAPER = 0xf9f8f2
const LIGHT_GROUND = 0x353a3e

export interface StationOptions {
  /** Aborted by the caller when this mount is stale; checked before any GL object is created. */
  signal: AbortSignal
  /** Section markers by section id; they follow the model's rotation, projected each frame (never by React state). */
  markers: Partial<Record<SectionId, HTMLElement>>
  /** Sensor markers by sensor id: shown only in focus, presentation only. */
  sensors: Partial<Record<string, HTMLElement>>
  /** Called when a section comes into focus (its id) or focus ends (null). */
  onSelect?: (id: SectionId | null) => void
}

export interface StationRenderer {
  dispose(): void
}

interface MountedAnchor {
  id: SectionId
  object: Object3D
  element: HTMLElement
}

/** A marker placed on the model: a section (clickable) or a sensor (presentation only). */
interface MountedMarker {
  object: Object3D
  element: HTMLElement
}

// Duck-typed checks, as in the body twin: they keep working if the bundler ends up with two copies of three.
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

/**
 * The GLB export carries two objects that are not part of the station. They would skew the framing
 * (the camera would fit them and the station would look tiny), so they are removed before it:
 * - `Object_500`: Earth, a 13 m sphere with a strong white emission (material `Procedural_Earth`).
 * - `Object_502`: a 2 m white cube about 155 m from the station.
 */
const NOT_STATION_NODES = new Set(['Object_500', 'Object_502'])

function removeNotStation(root: Object3D): void {
  const extra: Object3D[] = []
  root.traverse((node) => {
    if (NOT_STATION_NODES.has(node.name)) extra.push(node)
  })
  for (const node of extra) {
    disposeObject(node)
    node.removeFromParent()
  }
}

/**
 * Station showroom: the ISS turns slowly around Y. Clicking a section's marker zooms to it (the same zoom as the body
 * twin): the station turns so the marker faces the camera and the slow turn stops. The station is cleaned (only the
 * hulls remain, drawn without layers through each other), and the guide lines and the crew appear. From there the mouse
 * rotates the station freely (drag; vertical drag tilts up to 90 degrees), as in the twin. Other markers stay usable;
 * double click or double tap on the canvas ends the focus. With `prefers-reduced-motion` the slow turn stops.
 */
export async function mount(canvas: HTMLCanvasElement, options: StationOptions): Promise<StationRenderer> {
  // The station and the crew model load together. A missing crew model leaves the station alone (no avatars).
  const [gltf, astronaut] = await Promise.all([
    new GLTFLoader().setMeshoptDecoder(MeshoptDecoder).loadAsync(STATION_URL),
    loadAstronautSource(ASTRONAUT_URL).catch((error: unknown): AstronautSource | null => {
      console.warn('Astronaut model failed to load', error)
      return null
    }),
  ])
  const model = gltf.scene
  if (options.signal.aborted) {
    disposeObject(model)
    throw new DOMException('Station mount aborted', 'AbortError')
  }
  removeNotStation(model)

  let webgl: WebGLRenderer | null = null
  try {
    // Centre the station on the origin: the turn happens around its middle.
    const box = new Box3().setFromObject(model)
    const size = box.getSize(new Vector3())
    const axis = size.x >= size.y && size.x >= size.z ? 0 : size.y >= size.z ? 1 : 2
    const length = size.getComponent(axis)
    model.position.sub(box.getCenter(new Vector3()))
    model.updateMatrixWorld(true)
    // The station's own meshes, taken before anything of ours (markers, guides, crew) is added to the model: only
    // these are faded and hidden, never the crew.
    const stationMeshes: Mesh[] = []
    model.traverse((node) => {
      if ((node as Mesh).isMesh) stationMeshes.push(node as Mesh)
    })
    // Colour for the surfaces the GLB leaves without one (see stationColor.ts). Its maps are kept as they are.
    const panelTexture = createPanelTexture()
    if (panelTexture) applyPanelTexture(stationMeshes, panelTexture)

    // Rooms and corridors read from the GLB (see stationGraph.ts). The guide lines and the walkers use this same
    // graph, in the model's local coordinates, so the walkers move exactly along the lines.
    const graph = buildStationGraph(model)

    // Section markers: at the junctions of the guide lines. Each is a child of the model, so it turns with the station.
    const anchors: MountedAnchor[] = STATION_SECTIONS.flatMap((section) => {
      const element = options.markers[section.id]
      const local = graph.rooms[section.key]
      if (!element || !local) return []
      const object = new Object3D()
      object.name = `section-${section.id}`
      object.position.copy(local)
      model.add(object)
      return [{ id: section.id, object, element }]
    })

    // Sensor markers: on the walls of the corridors and rooms, in focus only. They take no click; the chips show on hover.
    // Walls come from the hull vertices of the GLB, in the model's local coordinates (see wall.ts).
    const toLocal = new Matrix4().copy(model.matrixWorld).invert()
    const hullCache = new Map<string, Vector3[]>()
    const hullOf = (module: string): Vector3[] => {
      const cached = hullCache.get(module)
      if (cached) return cached
      const points: Vector3[] = []
      const matrix = new Matrix4()
      for (const mesh of graph.hullByModule[module] ?? []) {
        matrix.multiplyMatrices(toLocal, mesh.matrixWorld)
        const position = mesh.geometry.getAttribute('position')
        for (let i = 0; i < position.count; i++) {
          points.push(new Vector3().fromBufferAttribute(position, i).applyMatrix4(matrix))
        }
      }
      hullCache.set(module, points)
      return points
    }
    // Direction on the wall: `angleDeg` from the station's ceiling, in the plane of the cross-section (lateral and up).
    const wallDirection = (angleDeg: number): Vector3 => {
      const { up, lateral } = graph.frame
      const a = MathUtils.degToRad(angleDeg)
      return up.clone().multiplyScalar(Math.cos(a)).addScaledVector(lateral, Math.sin(a))
    }
    // Points already given to devices: a new device keeps clear of them (see wall.ts).
    const placed: Vector3[] = []
    const sensorPoint = (sensor: StationSensor): Vector3 | null => {
      const dir = wallDirection(sensor.angleDeg)
      if (sensor.site.kind === 'room') {
        const at = graph.rooms[sensor.site.room]
        return at ? wallPointAlong(hullOf(sensor.site.room), at, null, dir, placed) : null
      }
      const { from, to, t } = sensor.site
      const a = graph.rooms[from]
      const b = graph.rooms[to]
      if (!a || !b) return null
      const at = a.clone().lerp(b, t)
      const axis = b.clone().sub(a).normalize()
      return wallPointAlong([...hullOf(from), ...hullOf(to)], at, axis, dir, placed)
    }
    const sensorMounts: MountedMarker[] = STATION_SENSORS.flatMap((sensor) => {
      const element = options.sensors[sensor.id]
      const point = element ? sensorPoint(sensor) : null
      if (!element || !point) return []
      placed.push(point)
      const object = new Object3D()
      object.name = `sensor-${sensor.id}`
      object.position.copy(point)
      model.add(object)
      element.hidden = true
      return [{ object, element }]
    })
    const markerMounts: MountedMarker[] = [...anchors, ...sensorMounts]
    // The look of the station: translucent at rest; in focus only the hulls remain, drawn without layers through
    // each other (see focusClean.ts). Applies the resting opacity now.
    const clean = createFocusClean(stationMeshes, graph.hull, { rest: STATION_OPACITY, focus: FOCUS_OPACITY })
    const guidePoints: Vector3[] = []
    for (const [from, to] of graph.corridors) {
      const a = graph.rooms[from]
      const b = graph.rooms[to]
      if (a && b) guidePoints.push(a, b)
    }
    // Guide lines: a child of the model (they turn with it), hidden until a section is in focus.
    const guides = new LineSegments(
      new BufferGeometry().setFromPoints(guidePoints),
      new LineBasicMaterial({ color: GUIDE_COLOR, transparent: true, opacity: GUIDE_OPACITY, depthTest: false }),
    )
    guides.visible = false
    guides.renderOrder = 10 // after the translucent hulls, so the lines are not dimmed by them
    model.add(guides)

    // Crew in zero gravity: green humanoids that drift along the corridors, loop through the rooms and meet at the
    // hubs. Real size (1.8 m) against the station's scale, so they fit the tubes (the nodes are about 4.5 m across).
    const unitsPerMetre = 1 / graph.metresPerUnit
    const walkers = new Walkers(
      {
        routes: ASTRONAUT_ROUTES.filter((route) => route.stops.every((stop) => graph.rooms[stop.room])),
        corridors: graph.corridors,
        rooms: graph.rooms,
        speed: WALK_SPEED_M_S * unitsPerMetre,
        slotStep: WALK_SLOT_M * unitsPerMetre,
        dwellMs: WALK_DWELL_MS,
        meetMs: WALK_MEET_MS,
        talkMs: WALK_TALK_MS,
      },
      performance.now(),
    )
    // The NASA astronaut, scaled to the avatar height and split into limbs (see astronautModel.ts). The model is
    // baked once and shared by the avatars. Avatars are children of the model, hidden until a section is in focus.
    const bakedAstronaut = astronaut ? bakeAstronaut(splitAstronaut(astronaut.body), astronaut.visor, ASTRONAUT_HEIGHT_M * unitsPerMetre) : null
    const astronautMaterials = astronaut ? { suit: astronaut.bodyMaterial, visor: astronaut.visorMaterial } : null
    const walkerRigs: AstronautRig[] =
      bakedAstronaut && astronautMaterials
        ? walkers.list.map((_, i) => {
            const rig = createAstronaut(bakedAstronaut, astronautMaterials, i * 2.1)
            rig.root.visible = false
            model.add(rig.root)
            return rig
          })
        : []
    // The station's own axes, read from the GLB (it is tilted about 22 degrees): crew orient by them, not by world Y.
    const { forward: stationForward, up: stationUp } = graph.frame
    const walkerPrev = walkers.list.map((walker) => ({ x: walker.pos.x, y: walker.pos.y, z: walker.pos.z }))
    const walkerTravel = walkers.list.map(() => stationForward.clone()) // last direction of travel
    const poseHead = new Vector3()
    const poseFront = new Vector3()
    let lastPoseAt = performance.now()
    const placeWalkers = () => {
      const now = performance.now()
      const dt = Math.min((now - lastPoseAt) / 1000, 0.1)
      lastPoseAt = now
      walkers.list.forEach((walker, i) => {
        const rig = walkerRigs[i]
        const prev = walkerPrev[i]
        const travel = walkerTravel[i]
        if (!rig || !prev || !travel) return
        const dx = walker.pos.x - prev.x
        const dy = walker.pos.y - prev.y
        const dz = walker.pos.z - prev.z
        const dwelling = walkers.isDwelling(walker, now)
        const moved = Math.hypot(dx, dy, dz)
        const moving = !dwelling && moved > 1e-9
        prev.x = walker.pos.x
        prev.y = walker.pos.y
        prev.z = walker.pos.z
        if (moving) travel.set(dx, dy, dz).divideScalar(moved)
        let mode: AstronautMode
        if (moving) {
          // Gliding along a corridor: head first, belly towards the station's floor.
          mode = 'glide'
          poseHead.copy(travel)
          poseFront.copy(stationUp).negate()
        } else {
          // Hovering: head towards the station's up. Faces the companion while they talk, else the last direction.
          poseHead.copy(stationUp)
          const companion = dwelling ? walkers.companion(walker, now) : undefined
          if (companion) {
            mode = 'wave'
            poseFront.set(companion.pos.x - walker.pos.x, companion.pos.y - walker.pos.y, companion.pos.z - walker.pos.z)
          } else {
            mode = 'idle'
            poseFront.copy(travel)
          }
        }
        poseAstronaut(rig, { at: walker.pos, head: poseHead, front: poseFront, mode, now, dt })
      })
    }
    placeWalkers()

    // Guide lines and walkers appear together, only while a section is in focus.
    const setFocusLayers = (visible: boolean) => {
      guides.visible = visible
      for (const rig of walkerRigs) rig.root.visible = visible
      for (const { element } of sensorMounts) element.hidden = !visible
    }
    const disposeGuides = () => {
      guides.geometry.dispose()
      ;(guides.material as LineBasicMaterial).dispose()
    }

    // The pivot carries the turn; the model stays centred inside it.
    const pivot = new Group()
    pivot.add(model)
    const scene = new Scene()
    scene.add(pivot)
    scene.add(new HemisphereLight(LIGHT_PAPER, LIGHT_GROUND, 0.6))
    const key = new DirectionalLight(LIGHT_PAPER, 1.4)
    key.position.set(2, 3, 4)
    const rim = new DirectionalLight(LIGHT_PAPER, 0.8)
    rim.position.set(-3, 2, -3)
    scene.add(key, rim)

    // The camera sits across the station's longest axis, so the whole length reads side-on.
    const viewDirection = new Vector3()
    viewDirection.setComponent(axis === 2 ? 0 : 2, 1)
    // Tight near and far planes: the scene is a few units across, and the hull depth pre-pass needs the depth buffer's
    // precision to tell shells that are close together apart.
    const camera = new PerspectiveCamera(30, 1, 0.05, 500)
    // Transparent canvas: the page background and its grid show through behind the model.
    webgl = new WebGLRenderer({ canvas, antialias: true, alpha: true })
    webgl.setClearColor(0x000000, 0)
    webgl.toneMapping = ACESFilmicToneMapping
    webgl.toneMappingExposure = 0.9

    const halfFov = MathUtils.degToRad(camera.fov) / 2
    let framedDistance = 0
    const fitCamera = () => {
      // Width-based distance: FRAME_HALF_WIDTH of the station's length fits to each side of the centre, whatever the canvas shape.
      framedDistance = (FRAME_HALF_WIDTH * length) / (Math.tan(halfFov) * camera.aspect)
    }

    // Focus state. `blend` moves the camera between the framed view (0) and the zoomed view (1).
    let focus: MountedAnchor | null = null
    let viewObject: Object3D | null = null // kept after a reset, so the camera blends back to the centre
    let blendFrom = 0
    let blendTo = 0
    let zoomStartedAt = 0
    // The turn that brings a section to face the camera. Once it settles, the mouse rotates the station freely.
    let turning = false
    let turnDelta = 0
    let turnApplied = 0
    let tiltFrom = 0 // tilt (from dragging) when a turn starts; it eases back to level during the turn
    let dragEnabled = false
    let dragLast: { x: number; y: number } | null = null
    const target = new Vector3()
    const markerWorld = new Vector3()
    const markerNdc = new Vector3()
    const easeNow = () => 1 - (1 - Math.min(1, (performance.now() - zoomStartedAt) / ZOOM_MS)) ** 3 // ease-out cubic
    const blendNow = () => blendFrom + (blendTo - blendFrom) * easeNow()

    /** Turn (around Y) that brings a point of the unturned model to face the camera. */
    const facingAngle = (anchor: MountedAnchor) => {
      const local = anchor.object.position.clone().add(model.position) // the model itself is not rotated
      const cameraHeading = Math.atan2(viewDirection.x, viewDirection.z)
      const pointHeading = Math.atan2(local.x, local.z)
      return cameraHeading - pointHeading
    }

    const startFocus = (anchor: MountedAnchor) => {
      if (focus === anchor) return
      const current = pivot.rotation.y
      blendFrom = blendNow()
      // Shortest turn from the current angle to the one that faces the camera.
      turnDelta = MathUtils.euclideanModulo(facingAngle(anchor) - current + Math.PI, Math.PI * 2) - Math.PI
      turnApplied = 0
      turning = true
      tiltFrom = pivot.rotation.x
      dragEnabled = false // enabled again when the turn settles
      dragLast = null
      canvas.style.cursor = ''
      if (focus) setMarkerActive(focus.element, false)
      focus = anchor
      viewObject = anchor.object
      setMarkerActive(anchor.element, true)
      blendTo = 1
      zoomStartedAt = reducedMotion.matches ? -Infinity : performance.now()
      clean.apply(true)
      setFocusLayers(true)
      canvas.style.pointerEvents = 'auto' // so double click and double tap reach the canvas
      canvas.style.touchAction = 'none'
      options.onSelect?.(anchor.id)
      draw()
    }

    const resetFocus = () => {
      if (!focus) return
      setMarkerActive(focus.element, false)
      focus = null
      turning = false
      dragEnabled = false
      dragLast = null
      pivot.rotation.x = 0 // level again; the slow spin resumes
      blendFrom = blendNow()
      blendTo = 0
      zoomStartedAt = reducedMotion.matches ? -Infinity : performance.now()
      clean.apply(false)
      setFocusLayers(false)
      canvas.style.pointerEvents = ''
      canvas.style.touchAction = ''
      canvas.style.cursor = ''
      options.onSelect?.(null)
      draw()
    }

    const updateCamera = () => {
      if (framedDistance === 0) return
      const eased = easeNow()
      if (turning) {
        const turned = turnDelta * eased
        pivot.rotation.y += turned - turnApplied
        turnApplied = turned
        pivot.rotation.x = tiltFrom * (1 - eased) // a tilt from dragging eases back to level as the section turns to the front
        if (eased >= 1) {
          turning = false
          dragEnabled = true // free rotation with the mouse starts once the zoom has settled
          canvas.style.cursor = 'grab'
        }
      }
      const t = blendFrom + (blendTo - blendFrom) * eased
      if (viewObject) viewObject.getWorldPosition(target).multiplyScalar(t) // lerp from the centre to the section
      else target.set(0, 0, 0)
      const distance = framedDistance * (1 - (1 - ZOOM_DISTANCE) * t)
      camera.position.copy(target).addScaledVector(viewDirection, distance)
      camera.lookAt(target)
    }

    // Projects every marker into CSS pixels. All markers stay visible, focus or not.
    const updateMarkers = () => {
      const width = canvas.clientWidth
      const height = canvas.clientHeight
      if (width === 0 || height === 0) return
      camera.updateMatrixWorld()
      for (const { object, element } of markerMounts) {
        if (element.hidden) continue // sensors, outside focus
        object.getWorldPosition(markerWorld)
        markerNdc.copy(markerWorld).project(camera)
        placeMarker(element, ((markerNdc.x + 1) / 2) * width, ((1 - markerNdc.y) / 2) * height)
      }
    }

    const draw = () => {
      placeWalkers()
      updateCamera()
      updateMarkers()
      webgl?.render(scene, camera)
    }

    const resize = () => {
      if (!webgl) return
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
      const seconds = Math.min(elapsed, 100) / 1000
      // The slow spin stops in focus: from there the mouse rotates the station. The crew keeps drifting.
      if (!focus) pivot.rotation.y += SPIN_RAD_PER_SECOND * seconds
      walkers.update(now, seconds)
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
    // Still for reduced motion or a hidden tab; otherwise the slow turn runs.
    const sync = () => {
      if (reducedMotion.matches || document.hidden) {
        stop()
        draw()
      } else {
        start()
      }
    }

    // Markers: click focuses the section. They stay clickable while another one is in focus.
    const markerClicks = anchors.map((anchor) => {
      const onClick = () => startFocus(anchor)
      anchor.element.addEventListener('click', onClick)
      return { element: anchor.element, onClick }
    })

    // On the canvas, in focus: drag rotates freely (once the zoom has settled); a double click or double tap ends the focus.
    let tapDown: { x: number; y: number } | null = null
    let lastTap: { x: number; y: number; at: number } | null = null
    const onPointerDown = (event: PointerEvent) => {
      tapDown = { x: event.clientX, y: event.clientY }
      if (!dragEnabled) return
      dragLast = { x: event.clientX, y: event.clientY }
      canvas.setPointerCapture(event.pointerId)
      canvas.style.cursor = 'grabbing'
    }
    const onPointerMove = (event: PointerEvent) => {
      if (dragLast === null) return
      // Horizontal drag turns around Y; vertical drag tilts around X, limited so the station never flips.
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
      if (dragEnabled) canvas.style.cursor = 'grab'
    }
    const onPointerCancel = (event: PointerEvent) => {
      tapDown = null
      releasePointer(event)
    }
    const onPointerUp = (event: PointerEvent) => {
      releasePointer(event)
      const down = tapDown
      tapDown = null
      if (!down || !focus || Math.hypot(event.clientX - down.x, event.clientY - down.y) > TAP_SLOP_PX) return
      const now = performance.now()
      const previous = lastTap
      if (previous && now - previous.at < DOUBLE_TAP_MS && Math.hypot(event.clientX - previous.x, event.clientY - previous.y) <= TAP_SLOP_PX) {
        lastTap = null
        resetFocus()
      } else {
        lastTap = { x: event.clientX, y: event.clientY, at: now }
      }
    }
    canvas.addEventListener('pointerdown', onPointerDown)
    canvas.addEventListener('pointermove', onPointerMove)
    canvas.addEventListener('pointerup', onPointerUp)
    canvas.addEventListener('pointercancel', onPointerCancel)

    const observer = new ResizeObserver(resize)
    observer.observe(canvas)
    document.addEventListener('visibilitychange', sync)
    reducedMotion.addEventListener('change', sync)
    resize()
    sync()

    return {
      dispose() {
        stop()
        observer.disconnect()
        document.removeEventListener('visibilitychange', sync)
        reducedMotion.removeEventListener('change', sync)
        for (const { element, onClick } of markerClicks) element.removeEventListener('click', onClick)
        canvas.removeEventListener('pointerdown', onPointerDown)
        canvas.removeEventListener('pointermove', onPointerMove)
        canvas.removeEventListener('pointerup', onPointerUp)
        canvas.removeEventListener('pointercancel', onPointerCancel)
        canvas.style.pointerEvents = ''
        canvas.style.touchAction = ''
        canvas.style.cursor = ''
        disposeGuides()
        clean.dispose()
        panelTexture?.dispose()
        disposeObject(model)
        // No forceContextLoss(): React StrictMode remounts reuse this canvas, and a lost context is permanent.
        webgl?.dispose()
      },
    }
  } catch (error) {
    disposeObject(model)
    webgl?.dispose()
    throw error
  }
}
