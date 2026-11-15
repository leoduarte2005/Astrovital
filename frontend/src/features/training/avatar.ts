import {
  BoxGeometry,
  CapsuleGeometry,
  Color,
  Group,
  Mesh,
  MeshStandardMaterial,
  SphereGeometry,
  type BufferGeometry,
} from 'three'

/**
 * A simple humanoid avatar for the training hangar, built from primitives (no GLB). Joints at the hips, knees,
 * shoulders and elbows; poses are set each frame by rotation only. Origin at the feet, facing +Z, in metres.
 * Proportions are for a 1.75 m person and scaled to the crew member's height.
 */

export type Pose = 'stand' | 'walk' | 'run' | 'sit' | 'lie' | 'swim' | 'row' | 'cycle' | 'climb' | 'lift'

export interface AvatarSpec {
  skinTone: string
  /** Shirt colour (the crew member's accent). */
  shirt: string
  heightM: number
}

export interface Avatar {
  /** Placed by the caller: position and rotation about Y. */
  root: Group
  /** Height of the head top above the root, for the current pose (for the name marker). */
  headHeight: number
  setPose(pose: Pose, timeS: number, walkPhase: number): void
  dispose(): void
}

const REFERENCE_HEIGHT = 1.75
const HIP_Y = 0.92
const THIGH = 0.44
const SHIN = 0.44
const UPPER_ARM = 0.3
const FOREARM = 0.28
const SEAT_Y = 0.46
const BED_Y = 0.55
const PANTS = '#2b2f36'
const SHOES = '#1b1d22'
const HAIR = '#2a211b'
const HALF_PI = Math.PI / 2

/** A capsule hanging from its top end (the joint). */
function limb(radius: number, length: number, material: MeshStandardMaterial): Mesh {
  const cylinder = Math.max(0.01, length - radius * 2)
  const mesh = new Mesh(new CapsuleGeometry(radius, cylinder, 4, 8), material)
  mesh.position.y = -length / 2
  return mesh
}

export function buildAvatar(spec: AvatarSpec): Avatar {
  const skin = new MeshStandardMaterial({ color: new Color(spec.skinTone), roughness: 0.8 })
  const shirt = new MeshStandardMaterial({ color: new Color(spec.shirt), roughness: 0.85 })
  const pants = new MeshStandardMaterial({ color: new Color(PANTS), roughness: 0.9 })
  const shoes = new MeshStandardMaterial({ color: new Color(SHOES), roughness: 0.9 })
  const hair = new MeshStandardMaterial({ color: new Color(HAIR), roughness: 0.95 })

  const root = new Group()
  // `body` carries the pose offsets (seat height, lying, swimming); `root` carries the placement.
  const body = new Group()
  body.scale.setScalar(spec.heightM / REFERENCE_HEIGHT)
  root.add(body)

  const torso = new Mesh(new BoxGeometry(0.38, 0.56, 0.22), shirt)
  torso.position.y = 1.2
  const pelvis = new Mesh(new BoxGeometry(0.34, 0.16, 0.2), pants)
  pelvis.position.y = HIP_Y + 0.02
  const neck = new Mesh(new CapsuleGeometry(0.045, 0.04, 2, 8), skin)
  neck.position.y = 1.52
  const head = new Mesh(new SphereGeometry(0.11, 16, 12), skin)
  head.position.y = 1.64
  const cap = new Mesh(new SphereGeometry(0.115, 16, 8, 0, Math.PI * 2, 0, Math.PI / 2.2), hair)
  cap.position.y = 1.655
  body.add(torso, pelvis, neck, head, cap)

  const legSide = (side: 1 | -1) => {
    const hip = new Group()
    hip.position.set(0.1 * side, HIP_Y, 0)
    hip.add(limb(0.075, THIGH, pants))
    const knee = new Group()
    knee.position.y = -THIGH
    knee.add(limb(0.06, SHIN, pants))
    const foot = new Mesh(new BoxGeometry(0.1, 0.06, 0.24), shoes)
    foot.position.set(0, -SHIN - 0.01, 0.05)
    knee.add(foot)
    hip.add(knee)
    body.add(hip)
    return { hip, knee }
  }
  const armSide = (side: 1 | -1) => {
    const shoulder = new Group()
    shoulder.position.set(0.24 * side, 1.44, 0)
    shoulder.add(limb(0.055, UPPER_ARM, shirt))
    const elbow = new Group()
    elbow.position.y = -UPPER_ARM
    elbow.add(limb(0.048, FOREARM, skin))
    const hand = new Mesh(new SphereGeometry(0.05, 10, 8), skin)
    hand.position.y = -FOREARM - 0.02
    elbow.add(hand)
    shoulder.add(elbow)
    body.add(shoulder)
    return { shoulder, elbow }
  }
  const leftLeg = legSide(-1)
  const rightLeg = legSide(1)
  const leftArm = armSide(-1)
  const rightArm = armSide(1)
  const scale = spec.heightM / REFERENCE_HEIGHT

  const reset = () => {
    body.position.set(0, 0, 0)
    body.rotation.set(0, 0, 0)
    for (const leg of [leftLeg, rightLeg]) {
      leg.hip.rotation.set(0, 0, 0)
      leg.knee.rotation.set(0, 0, 0)
    }
    for (const arm of [leftArm, rightArm]) {
      arm.shoulder.rotation.set(0, 0, 0)
      arm.elbow.rotation.set(0, 0, 0)
    }
    leftArm.shoulder.rotation.z = -0.06
    rightArm.shoulder.rotation.z = 0.06
  }

  // Joint signs: a negative rotation about X swings a hanging limb forward (+Z); a positive knee bends the shin back.
  const seated = () => {
    body.position.y = -(HIP_Y - SEAT_Y) * scale
    leftLeg.hip.rotation.x = -HALF_PI
    rightLeg.hip.rotation.x = -HALF_PI
    leftLeg.knee.rotation.x = HALF_PI
    rightLeg.knee.rotation.x = HALF_PI
  }

  let headHeight = spec.heightM + 0.15

  const setPose = (pose: Pose, t: number, phase: number) => {
    reset()
    headHeight = spec.heightM + 0.15
    switch (pose) {
      case 'walk':
      case 'run': {
        const swing = pose === 'run' ? 0.8 : 0.45
        const knee = pose === 'run' ? 1.2 : 0.6
        const s = Math.sin(phase)
        leftLeg.hip.rotation.x = -swing * s
        rightLeg.hip.rotation.x = swing * s
        leftLeg.knee.rotation.x = knee * Math.max(0, Math.sin(phase + 1.2))
        rightLeg.knee.rotation.x = knee * Math.max(0, Math.sin(phase + 1.2 + Math.PI))
        leftArm.shoulder.rotation.x = swing * 0.9 * s
        rightArm.shoulder.rotation.x = -swing * 0.9 * s
        leftArm.elbow.rotation.x = pose === 'run' ? -1.4 : -0.25
        rightArm.elbow.rotation.x = pose === 'run' ? -1.4 : -0.25
        break
      }
      case 'sit':
        seated()
        leftArm.shoulder.rotation.x = -0.35
        rightArm.shoulder.rotation.x = -0.35
        leftArm.elbow.rotation.x = -0.9
        rightArm.elbow.rotation.x = -0.9
        headHeight = spec.heightM - (HIP_Y - SEAT_Y) * scale + 0.15
        break
      case 'row': {
        seated()
        const c = (Math.sin(t * 3) + 1) / 2 // 0 = catch, 1 = finish
        for (const leg of [leftLeg, rightLeg]) {
          leg.hip.rotation.x = -HALF_PI - 0.6 * (1 - c)
          leg.knee.rotation.x = HALF_PI * (0.3 + 0.7 * (1 - c))
        }
        for (const arm of [leftArm, rightArm]) {
          arm.shoulder.rotation.x = -1.3 + 0.7 * c
          arm.elbow.rotation.x = -1.4 * c
        }
        headHeight = spec.heightM - (HIP_Y - SEAT_Y) * scale + 0.15
        break
      }
      case 'cycle': {
        seated()
        const a = t * 6
        leftLeg.hip.rotation.x = -HALF_PI + 0.35 * Math.sin(a)
        rightLeg.hip.rotation.x = -HALF_PI + 0.35 * Math.sin(a + Math.PI)
        leftLeg.knee.rotation.x = HALF_PI + 0.35 * Math.sin(a + HALF_PI)
        rightLeg.knee.rotation.x = HALF_PI + 0.35 * Math.sin(a + HALF_PI + Math.PI)
        leftArm.shoulder.rotation.x = -0.9
        rightArm.shoulder.rotation.x = -0.9
        headHeight = spec.heightM - (HIP_Y - SEAT_Y) * scale + 0.15
        break
      }
      case 'climb': {
        const a = t * 2
        leftArm.shoulder.rotation.x = -2.8 + 0.25 * Math.sin(a)
        rightArm.shoulder.rotation.x = -2.8 - 0.25 * Math.sin(a)
        leftArm.elbow.rotation.x = -0.4
        rightArm.elbow.rotation.x = -0.4
        leftLeg.hip.rotation.x = -0.4 * Math.max(0, Math.sin(a))
        rightLeg.hip.rotation.x = -0.4 * Math.max(0, -Math.sin(a))
        break
      }
      case 'lift': {
        const curl = -1.2 - 0.6 * Math.sin(t * 3)
        leftArm.elbow.rotation.x = curl
        rightArm.elbow.rotation.x = curl
        leftArm.shoulder.rotation.x = -0.2
        rightArm.shoulder.rotation.x = -0.2
        break
      }
      case 'lie':
        // On the back, head toward the facing direction's opposite, centred over the bed point.
        body.rotation.x = -HALF_PI
        body.position.set(0, BED_Y, (spec.heightM / 2) * 1.0)
        headHeight = BED_Y + 0.35
        break
      case 'swim': {
        body.rotation.x = HALF_PI
        body.position.set(0, 0.15, -spec.heightM / 2)
        const a = t * 4
        leftArm.shoulder.rotation.x = -(a % (Math.PI * 2))
        rightArm.shoulder.rotation.x = -((a + Math.PI) % (Math.PI * 2))
        leftLeg.hip.rotation.x = 0.2 * Math.sin(t * 8)
        rightLeg.hip.rotation.x = -0.2 * Math.sin(t * 8)
        headHeight = 0.5
        break
      }
      case 'stand':
        break
    }
  }
  setPose('stand', 0, 0)

  return {
    root,
    get headHeight() {
      return headHeight
    },
    setPose,
    dispose() {
      root.traverse((node) => {
        if (node instanceof Mesh) (node.geometry as BufferGeometry).dispose()
      })
      for (const material of [skin, shirt, pants, shoes, hair]) material.dispose()
    },
  }
}
