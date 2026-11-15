import { Euler, Group, Matrix4, Mesh, Quaternion, Vector3, type Material } from 'three'
import type { BakedAstronaut, LimbPart } from '@/lib/model/astronaut/astronautModel'
import type { Point } from './walkers'

/**
 * A crew avatar: the NASA astronaut model (see astronautModel.ts), posed in zero gravity. Its body hangs from a root
 * group; each arm and leg hangs from a shoulder or hip group, so the poses swing it. The elbow and knee groups are
 * at the end of each limb: the model has no bent joints, so they stay straight.
 */
export interface AstronautRig {
  root: Group
  leftShoulder: Group
  leftElbow: Group
  rightShoulder: Group
  rightElbow: Group
  leftHip: Group
  leftKnee: Group
  rightHip: Group
  rightKnee: Group
  /** Overall height in model units, from the sole of the boots to the top of the helmet. */
  height: number
  /** Offsets the slow motions, so the avatars do not move in step. */
  phase: number
  /** False until the first pose: that one snaps to the target orientation instead of turning towards it. */
  oriented: boolean
}

/** What the avatar is doing, in zero gravity: hovering in place, gliding along a corridor, or waving to a companion. */
export type AstronautMode = 'idle' | 'glide' | 'wave'

export interface AstronautPose {
  /** Torso centre, on the corridor line. */
  at: Point
  /** Where the head points (unit vector). */
  head: Vector3
  /** Where the chest faces (unit vector); the avatar turns about its head axis to face it. */
  front: Vector3
  mode: AstronautMode
  /** Clock in ms, for the slow motions. */
  now: number
  /** Seconds since the last pose, for turning smoothly. */
  dt: number
}

const TAU = Math.PI * 2
/** How fast the body turns towards its target orientation, per second (an exponential approach). */
const TURN_RATE = 2.5

export interface AstronautMaterials {
  suit: Material
  visor: Material | null
}

/** Builds one avatar from the baked model. Geometry and materials are shared between avatars; only the groups are new. */
export function createAstronaut(baked: BakedAstronaut, materials: AstronautMaterials, phase: number): AstronautRig {
  const root = new Group()
  const body = new Mesh(baked.body, materials.suit)
  body.renderOrder = -1 // drawn before the hull depth pre-pass (see focusClean.ts), so the hulls do not hide it
  root.add(body)
  if (baked.visor) {
    const visor = new Mesh(baked.visor, materials.visor ?? materials.suit)
    visor.renderOrder = -1
    root.add(visor)
  }

  // A limb is a group at its joint, holding its geometry (relative to the joint) and an empty group at its end.
  const limb = (part: LimbPart) => {
    const joint = new Group()
    joint.position.copy(baked.joints[part])
    root.add(joint)
    const mesh = new Mesh(baked.limbs[part], materials.suit)
    mesh.renderOrder = -1
    joint.add(mesh)
    const end = new Group()
    end.position.set(0, -baked.limbLength[part], 0)
    joint.add(end)
    return { joint, end }
  }
  const leftArm = limb('armLeft')
  const rightArm = limb('armRight')
  const leftLeg = limb('legLeft')
  const rightLeg = limb('legRight')

  return {
    root,
    leftShoulder: leftArm.joint,
    leftElbow: leftArm.end,
    rightShoulder: rightArm.joint,
    rightElbow: rightArm.end,
    leftHip: leftLeg.joint,
    leftKnee: leftLeg.end,
    rightHip: rightLeg.joint,
    rightKnee: rightLeg.end,
    height: baked.height,
    phase,
    oriented: false,
  }
}

// Scratch objects, reused every frame.
const axisX = new Vector3()
const axisY = new Vector3()
const axisZ = new Vector3()
const basis = new Matrix4()
const target = new Quaternion()
const sway = new Quaternion()
const swayEuler = new Euler()

/** Turns the body so its head points along `head` and its chest along `front`, with a slow sway on top. */
function orient(rig: AstronautRig, pose: AstronautPose): void {
  axisY.copy(pose.head).normalize()
  axisZ.copy(pose.front).addScaledVector(axisY, -pose.front.dot(axisY))
  if (axisZ.lengthSq() < 1e-8) {
    // The chest direction is parallel to the head: pick any direction across it.
    axisZ.set(1, 0, 0).addScaledVector(axisY, -axisY.x)
    if (axisZ.lengthSq() < 1e-8) axisZ.set(0, 0, 1)
  }
  axisZ.normalize()
  axisX.crossVectors(axisY, axisZ)
  basis.makeBasis(axisX, axisY, axisZ)
  target.setFromRotationMatrix(basis)
  // Nobody holds still in zero gravity: a small, slow pitch and roll.
  const t = pose.now / 1000
  swayEuler.set(Math.sin(t * 0.5 + rig.phase) * 0.06, 0, Math.sin(t * 0.37 + rig.phase * 1.7) * 0.06)
  target.multiply(sway.setFromEuler(swayEuler))
  if (rig.oriented) rig.root.quaternion.slerp(target, 1 - Math.exp(-pose.dt * TURN_RATE))
  else rig.root.quaternion.copy(target)
  rig.oriented = true
}

/**
 * Places and poses an avatar in zero gravity. The torso centre stays exactly on the corridor line: the floating
 * feel comes from the body's slow sway and from loose limbs, never from stepping. Rotating a shoulder or hip about X
 * by a negative angle swings its limb forward (towards the chest), a positive one backward.
 * - idle: hovering, arms floating forward and out, hips and knees bent (the neutral posture in microgravity).
 * - glide: streamlined, head first, arms and legs trailing along the body.
 * - wave: like idle, with the right arm raised and waving towards the companion.
 */
export function poseAstronaut(rig: AstronautRig, pose: AstronautPose): void {
  rig.root.position.set(pose.at.x, pose.at.y, pose.at.z)
  orient(rig, pose)
  const t = pose.now / 1000
  const drift = (rate: number, shift: number) => Math.sin(t * rate + rig.phase + shift)
  if (pose.mode === 'glide') {
    rig.leftShoulder.rotation.set(0.12 + drift(0.9, 0) * 0.08, 0, -0.16)
    rig.rightShoulder.rotation.set(0.12 + drift(0.9, 1) * 0.08, 0, 0.16)
    rig.leftElbow.rotation.set(-0.12 + drift(0.8, 0.5) * 0.06, 0, 0)
    rig.rightElbow.rotation.set(-0.12 + drift(0.8, 1.5) * 0.06, 0, 0)
    rig.leftHip.rotation.set(0.06 + drift(0.7, 0) * 0.04, 0, -0.05)
    rig.rightHip.rotation.set(0.06 + drift(0.7, 2) * 0.04, 0, 0.05)
    rig.leftKnee.rotation.set(0.14 + drift(0.6, 1) * 0.05, 0, 0)
    rig.rightKnee.rotation.set(0.14 + drift(0.6, 3) * 0.05, 0, 0)
    return
  }
  const waving = pose.mode === 'wave'
  rig.leftShoulder.rotation.set(-0.5 + drift(0.7, 0) * 0.12, 0, -0.3)
  rig.leftElbow.rotation.set(-0.55 + drift(0.6, 1) * 0.1, 0, 0)
  rig.rightShoulder.rotation.set(waving ? -2.5 : -0.5 + drift(0.7, 1) * 0.12, 0, waving ? 0.25 : 0.3)
  rig.rightElbow.rotation.set(waving ? -0.4 + Math.sin(t * TAU * 1.4) * 0.6 : -0.55 + drift(0.6, 2) * 0.1, 0, 0)
  rig.leftHip.rotation.set(-0.35 + drift(0.5, 0) * 0.08, 0, -0.08)
  rig.rightHip.rotation.set(-0.35 + drift(0.5, 2) * 0.08, 0, 0.08)
  rig.leftKnee.rotation.set(0.6 + drift(0.5, 1) * 0.08, 0, 0)
  rig.rightKnee.rotation.set(0.6 + drift(0.5, 3) * 0.08, 0, 0)
}
