import {
  ACESFilmicToneMapping,
  Box3,
  Color,
  DirectionalLight,
  HemisphereLight,
  MathUtils,
  Mesh,
  PerspectiveCamera,
  Scene,
  Vector3,
  WebGLRenderer,
  type Material,
  type Object3D,
  type Texture,
} from 'three'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js'
import type { CrewId, CrewLore } from '@/lib/data/mock/crewLore'
import { STUDIO_LIGHT } from '@/lib/model/astronaut/view'
import { placeMarker } from '@/ui/Marker/placeMarker'
import { buildAvatar, type Avatar, type AvatarSpec } from './avatar'
import { MINUTES_PER_DAY, SIM_DAY_MS, WAYPOINTS, simTimeAt } from './behaviour'
import { obstaclesOf } from './obstacles'
import { Mover } from './mover'
import type { PlacedPoint } from './navigation'
import { TrainingSimulation } from './simulation'
import { WalkGrid } from './walkgrid'

/** Relative path: the central (or the dev middleware) serves `data/models` under `/models`. */
const HANGAR_URL = './models/hangar/edgespace_training_hangar.glb'

const MAX_PIXEL_RATIO = 2
const FRAME_MS = 1000 / 30 // fixed 30 fps target (see performance.md)
const FOV_DEG = 60
const FOV_MIN_DEG = 25 // most zoomed in
const FOV_MAX_DEG = 90 // most zoomed out
/** Mouse wheel: degrees of field of view per pixel of wheel travel (a notch is about 100 px). */
const WHEEL_DEG_PER_PX = 0.05
const DRAG_RAD_PER_PX = 0.005
/** Third person: the camera stays this far behind the crew member (metres), at this pitch (radians above the horizon). */
const FOLLOW_DISTANCE_M = 4.5
const DEFAULT_PITCH = 0.28
const MIN_PITCH = 0.05
const MAX_PITCH = 1.1
/** How quickly the camera catches up with the crew member, per second (higher = tighter). */
const FOLLOW_RATE = 6
/** The camera never goes below this height (metres), so it does not dive into the floor. */
const CAMERA_MIN_Y = 0.8
/** Uniform light over the whole hangar: no lamps (they were removed from the GLB), so no spot or point sources. */
const HANGAR_LIGHT = { hemisphere: 1.3, sun: 1.5, sunFrom: [0, 1, 0] as const }
/** Fallback for the `--bg` token (see styles/tokens.css). */
const FALLBACK_BG = '#100c08'
/** Names stay inside the view, this far (normalised device units, 1 = the edge) from its centre. */
const NAME_EDGE = 0.9
/** A month starts at 07:00 of its first day, when the crew is up. */
const START_MINUTE = 7 * 60

export interface TrainingCrew extends AvatarSpec {
  crewId: CrewId
  walkSpeed: 'slow' | 'normal' | 'brisk'
}

export interface HangarOptions {
  lore: readonly CrewLore[]
  crew: readonly TrainingCrew[]
  /** Name markers, moved each frame above each avatar (never by React state). */
  markers: Partial<Record<CrewId, HTMLElement>>
  monthIndex: number
  playing: boolean
  /** The crew member the camera follows (the active one). Null: no follow, the camera stays where it is. */
  follow: CrewId | null
}

export interface SimClock {
  monthIndex: number
  dayIndex: number
  /** Whole minutes of the simulated day. */
  minute: number
}

export interface HangarHandle {
  setMonth(monthIndex: number): void
  setPlaying(playing: boolean): void
  setFollow(crewId: CrewId | null): void
  /** Called with the simulated time whenever its minute changes, and once at once. Returns the unsubscribe. */
  onClock(listener: (clock: SimClock) => void): () => void
  dispose(): void
}

/** Where one avatar is drawn this frame. */
interface Spot {
  visible: boolean
  x: number
  y: number
  z: number
}

/** Waypoints as placed in the loaded GLB: world position and extras (facing, approach). */
function placePoints(model: Object3D): Map<string, PlacedPoint> {
  const points = new Map<string, PlacedPoint>()
  const world = new Vector3()
  for (const waypoint of WAYPOINTS) {
    const node = model.getObjectByName(waypoint.id)
    if (!node) {
      console.warn('training hangar: waypoint missing in the GLB', waypoint.id)
      continue
    }
    node.getWorldPosition(world)
    const extras = node.userData as { facingDeg?: number; approach?: { x: number; z: number } }
    points.set(waypoint.id, {
      id: waypoint.id,
      zone: waypoint.zone,
      level: waypoint.level,
      position: { x: world.x, y: world.y, z: world.z },
      facingDeg: typeof extras.facingDeg === 'number' ? extras.facingDeg : waypoint.facingDeg,
      approach: extras.approach ?? null,
      crewId: waypoint.crewId ?? null,
    })
  }
  return points
}

/**
 * Mounts the training hangar (its interior content only) full screen in `host`, with the crew avatars living the
 * chosen month in accelerated time. The camera follows the chosen crew member in third person; drag turns the view
 * around them, the wheel zooms (field of view), a double click returns to the first view.
 */
export async function mountHangar(host: HTMLElement, options: HangarOptions): Promise<HangarHandle> {
  const gltf = await new GLTFLoader().setMeshoptDecoder(MeshoptDecoder).loadAsync(HANGAR_URL)
  const model = gltf.scene

  const scene = new Scene()
  scene.add(model)
  scene.add(new HemisphereLight(STUDIO_LIGHT.paper, STUDIO_LIGHT.ground, HANGAR_LIGHT.hemisphere))
  const sun = new DirectionalLight(STUDIO_LIGHT.paper, HANGAR_LIGHT.sun)
  sun.position.set(...HANGAR_LIGHT.sunFrom)
  scene.add(sun)

  // The interior is measured in the GLB (root node extras). The bounding box of the whole model is larger than the
  // building (outlying meshes), so it is only a fallback.
  const box = new Box3().setFromObject(model)
  const declared = model.getObjectByName('TrainingHangar')?.userData?.interior as
    | { x: [number, number]; z: [number, number]; height: number }
    | undefined
  const interior = declared ?? { x: [box.min.x, box.max.x] as [number, number], z: [box.min.z, box.max.z] as [number, number], height: box.max.y }
  const target = new Vector3((interior.x[0] + interior.x[1]) / 2, interior.height * 0.35, (interior.z[0] + interior.z[1]) / 2)
  // Where the camera starts when no one is followed: the centre of the back wall, at half the height of the walls.
  const fallbackPosition = new Vector3((interior.x[0] + interior.x[1]) / 2, interior.height / 2, interior.z[1] - 2)

  // Avatars and the simulation.
  model.updateMatrixWorld(true)
  const points = placePoints(model)
  const avatars = new Map<CrewId, Avatar>()
  for (const member of options.crew) {
    const avatar = buildAvatar(member)
    avatars.set(member.crewId, avatar)
    scene.add(avatar.root)
  }
  // The clock sets each crew member's goal; the movers walk to it in real time, at a natural pace.
  const simulation = new TrainingSimulation(options.lore, points)
  // Floor objects from the GLB's own named nodes, as a walkable grid: routes go around them.
  const grid = new WalkGrid(obstaclesOf(model), { x0: interior.x[0], x1: interior.x[1], z0: interior.z[0], z1: interior.z[1] })
  const movers = new Map<CrewId, Mover>(options.crew.map((member) => [member.crewId, new Mover(member.crewId, points, member.walkSpeed, grid)]))

  const camera = new PerspectiveCamera(FOV_DEG, 1, 0.05, 1000)
  const renderer = new WebGLRenderer({ antialias: true })
  renderer.toneMapping = ACESFilmicToneMapping
  renderer.toneMappingExposure = 1
  renderer.setClearColor(
    new Color(getComputedStyle(document.documentElement).getPropertyValue('--bg').trim() || FALLBACK_BG),
    1,
  )
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, MAX_PIXEL_RATIO))
  host.prepend(renderer.domElement)
  const canvas = renderer.domElement
  // Drag on touch too: the browser must not scroll or zoom the page over the canvas.
  canvas.style.touchAction = 'none'
  canvas.style.cursor = 'grab'

  // Camera state. The orbit is relative to the followed crew member's facing: 0 means straight behind.
  let orbitYaw = 0
  let orbitPitch = DEFAULT_PITCH
  let fov = FOV_DEG
  let follow: CrewId | null = options.follow
  let followVisible = false
  let followHeading = 0
  const followHead = new Vector3()
  const cameraGoal = new Vector3()
  const aim = new Vector3()
  // Until the camera has been placed once, and after a change of followed person or month, it snaps (no glide).
  let cameraPlaced = false
  let dirty = true

  const fit = () => {
    const width = host.clientWidth
    const height = host.clientHeight
    if (!width || !height) return
    renderer.setSize(width, height, false)
    camera.aspect = width / height
    camera.updateProjectionMatrix()
    dirty = true
  }

  // Simulated time: the month loops; `elapsed` is real milliseconds into it.
  let monthIndex = options.monthIndex
  let playing = options.playing
  let elapsed = (START_MINUTE / MINUTES_PER_DAY) * SIM_DAY_MS
  const listeners = new Set<(clock: SimClock) => void>()
  let lastClockKey = ''

  // Seconds of animation (rowing, cycling...): advance only while playing, so a pause freezes everything.
  let animTime = 0
  const spots = new Map<CrewId, Spot>()
  const ndc = new Vector3()

  /** The camera behind the followed crew member, or the fallback view when nobody is followed. Glides unless snapping. */
  const placeCamera = (dt: number) => {
    if (followVisible) {
      const horizontal = FOLLOW_DISTANCE_M * Math.cos(orbitPitch)
      const vertical = FOLLOW_DISTANCE_M * Math.sin(orbitPitch)
      // Facing is 0 along +Z: "behind" is the opposite direction.
      const theta = followHeading + Math.PI + orbitYaw
      cameraGoal.set(followHead.x + Math.sin(theta) * horizontal, followHead.y + vertical, followHead.z + Math.cos(theta) * horizontal)
      cameraGoal.x = MathUtils.clamp(cameraGoal.x, interior.x[0] + 0.5, interior.x[1] - 0.5)
      cameraGoal.y = MathUtils.clamp(cameraGoal.y, CAMERA_MIN_Y, interior.height - 0.5)
      cameraGoal.z = MathUtils.clamp(cameraGoal.z, interior.z[0] + 0.5, interior.z[1] - 0.5)
      aim.copy(followHead)
    } else if (cameraPlaced) {
      return // nobody to follow right now (the crew member is away): keep the last view
    } else {
      cameraGoal.copy(fallbackPosition)
      aim.copy(target)
    }
    const k = cameraPlaced && dt > 0 ? 1 - Math.exp(-FOLLOW_RATE * dt) : 1
    camera.position.lerp(cameraGoal, k)
    camera.lookAt(aim)
    cameraPlaced = true
  }

  const updateScene = (dt: number) => {
    const { dayIndex, minute } = simTimeAt(monthIndex, elapsed)
    // First pass: each avatar's goal, walk and pose; the followed one also feeds the camera.
    followVisible = false
    for (const [crewId, avatar] of avatars) {
      const goal = simulation.goalAt(crewId, monthIndex, dayIndex, minute)
      const state = movers.get(crewId)?.update(goal, dt) ?? { ...goal, walkPhase: 0 }
      avatar.root.visible = state.visible
      const spot = spots.get(crewId) ?? { visible: false, x: 0, y: 0, z: 0 }
      spot.visible = state.visible
      spot.x = state.position.x
      spot.y = state.position.y
      spot.z = state.position.z
      spots.set(crewId, spot)
      if (!state.visible) continue
      avatar.root.position.set(state.position.x, state.position.y, state.position.z)
      avatar.root.rotation.y = state.heading
      avatar.setPose(state.pose, animTime, state.walkPhase)
      if (crewId === follow) {
        followVisible = true
        followHeading = state.heading
        followHead.set(state.position.x, state.position.y + avatar.headHeight, state.position.z)
      }
    }

    // Camera, then the name markers, which project through it.
    placeCamera(dt)
    for (const [crewId, avatar] of avatars) {
      const marker = options.markers[crewId]
      const spot = spots.get(crewId)
      if (!marker || !spot) continue
      if (!spot.visible) {
        marker.style.visibility = 'hidden'
        continue
      }
      ndc.set(spot.x, spot.y + avatar.headHeight, spot.z).project(camera)
      // Behind the camera the projection flips: mirror it, so the name still sits on that side of the view.
      let x = ndc.z > 1 ? -ndc.x : ndc.x
      let y = ndc.z > 1 ? -ndc.y : ndc.y
      // Always on screen: a name leaving the view stays at the nearest edge.
      x = MathUtils.clamp(x, -NAME_EDGE, NAME_EDGE)
      y = MathUtils.clamp(y, -NAME_EDGE, NAME_EDGE)
      placeMarker(marker, ((x + 1) / 2) * canvas.clientWidth, ((1 - y) / 2) * canvas.clientHeight)
    }

    const clock: SimClock = { monthIndex, dayIndex, minute: Math.floor(minute) }
    const key = `${clock.monthIndex}:${clock.dayIndex}:${clock.minute}`
    if (key !== lastClockKey) {
      lastClockKey = key
      for (const listener of listeners) listener(clock)
    }
  }

  const draw = (dt: number) => {
    camera.updateMatrixWorld()
    updateScene(dt)
    renderer.render(scene, camera)
  }

  // Loop at 30 fps. While playing, one real step advances the clock (fast: a day in SIM_DAY_MS) and the walks (natural
  // pace) together; a paused scene draws only when the view changes, and nothing moves.
  let frame = 0
  let last = 0
  const tick = (now: number) => {
    frame = requestAnimationFrame(tick)
    const delta = now - last
    if (delta < FRAME_MS - 1) return
    last = now
    let moveSeconds = 0
    if (playing) {
      const step = Math.min(delta, 100)
      elapsed += step
      moveSeconds = step / 1000
      animTime += moveSeconds
      dirty = true
    }
    if (dirty) {
      dirty = false
      draw(moveSeconds)
    }
  }

  // Drag: horizontal turns the view around the crew member, vertical raises or lowers the camera.
  let drag: { x: number; y: number } | null = null
  const onPointerDown = (event: PointerEvent) => {
    drag = { x: event.clientX, y: event.clientY }
    canvas.setPointerCapture(event.pointerId)
    canvas.style.cursor = 'grabbing'
  }
  const onPointerMove = (event: PointerEvent) => {
    if (!drag) return
    orbitYaw -= (event.clientX - drag.x) * DRAG_RAD_PER_PX
    orbitPitch = MathUtils.clamp(orbitPitch - (event.clientY - drag.y) * DRAG_RAD_PER_PX, MIN_PITCH, MAX_PITCH)
    drag = { x: event.clientX, y: event.clientY }
    dirty = true
  }
  const endDrag = (event: PointerEvent) => {
    drag = null
    if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId)
    canvas.style.cursor = 'grab'
  }
  // Wheel: zoom by the field of view (the camera stays at its distance). Lines are converted to pixels.
  const onWheel = (event: WheelEvent) => {
    event.preventDefault()
    const pixels = event.deltaMode === 1 ? event.deltaY * 16 : event.deltaY
    fov = MathUtils.clamp(fov + pixels * WHEEL_DEG_PER_PX, FOV_MIN_DEG, FOV_MAX_DEG)
    camera.fov = fov
    camera.updateProjectionMatrix()
    dirty = true
  }
  // Double click: back to the first view behind the crew member.
  const onDoubleClick = () => {
    orbitYaw = 0
    orbitPitch = DEFAULT_PITCH
    fov = FOV_DEG
    camera.fov = fov
    camera.updateProjectionMatrix()
    dirty = true
  }

  canvas.addEventListener('pointerdown', onPointerDown)
  canvas.addEventListener('pointermove', onPointerMove)
  canvas.addEventListener('pointerup', endDrag)
  canvas.addEventListener('pointercancel', endDrag)
  canvas.addEventListener('wheel', onWheel, { passive: false })
  canvas.addEventListener('dblclick', onDoubleClick)

  const observer = new ResizeObserver(fit)
  observer.observe(host)
  fit()
  draw(0)
  frame = requestAnimationFrame(tick)

  return {
    setMonth(index) {
      if (index === monthIndex) return
      monthIndex = index
      elapsed = (START_MINUTE / MINUTES_PER_DAY) * SIM_DAY_MS
      // A new month: everyone starts at their goal, no walk across months; the camera snaps to them.
      for (const mover of movers.values()) mover.reset()
      cameraPlaced = false
      dirty = true
    },
    setPlaying(value) {
      playing = value
      dirty = true
    },
    setFollow(crewId) {
      if (crewId === follow) return
      follow = crewId
      cameraPlaced = false
      dirty = true
    },
    onClock(listener) {
      listeners.add(listener)
      const { dayIndex, minute } = simTimeAt(monthIndex, elapsed)
      listener({ monthIndex, dayIndex, minute: Math.floor(minute) })
      return () => listeners.delete(listener)
    },
    dispose() {
      cancelAnimationFrame(frame)
      listeners.clear()
      observer.disconnect()
      canvas.removeEventListener('pointerdown', onPointerDown)
      canvas.removeEventListener('pointermove', onPointerMove)
      canvas.removeEventListener('pointerup', endDrag)
      canvas.removeEventListener('pointercancel', endDrag)
      canvas.removeEventListener('wheel', onWheel)
      canvas.removeEventListener('dblclick', onDoubleClick)
      for (const avatar of avatars.values()) {
        scene.remove(avatar.root)
        avatar.dispose()
      }
      model.traverse((node) => {
        if (!(node instanceof Mesh)) return
        node.geometry.dispose()
        const materials = Array.isArray(node.material) ? node.material : [node.material]
        for (const material of materials as Material[]) {
          for (const value of Object.values(material)) {
            // Duck-typed: it keeps working if the bundler ends up with two copies of three.
            if (typeof value === 'object' && value !== null && 'isTexture' in value) (value as Texture).dispose()
          }
          material.dispose()
        }
      })
      renderer.dispose()
      canvas.remove()
    },
  }
}
