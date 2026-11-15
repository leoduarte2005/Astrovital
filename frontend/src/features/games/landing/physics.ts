/**
 * Landing rules: a 2D touchdown with gravity, thrust and fuel. Pure functions, logical units.
 * The result is for learning: it lists what to review. It is not a score (rules/gamification.md).
 */
/** 16:9, three times the pixel buffer (features/games/palette.ts). */
export const WORLD_W = 960
export const WORLD_H = 540
export const GROUND_Y = WORLD_H - 60
export const PAD_WIDTH = 120
export const LANDER_HALF = 14

const GRAVITY = 40 // px/s²
const THRUST = 90 // px/s²
const FUEL_PER_SECOND = 12
const TURN_SPEED = 2 // rad/s

/** World speed units per m/s shown on the HUD: 35 units = 3,5 m/s. */
export const UNITS_PER_METRE = 10

/** Safe touchdown limits. */
export const SAFE_VERTICAL = 35 // px/s
export const SAFE_LATERAL = 20 // px/s
export const SAFE_ANGLE = 0.2 // rad, about 11°

export type LandingReason = 'vertical' | 'lateral' | 'angle' | 'offPad'

export interface LanderState {
  x: number
  y: number
  vx: number
  vy: number
  angle: number
  fuel: number
  pad: { left: number; right: number }
  status: 'flying' | 'landed' | 'crashed'
  reasons: LandingReason[]
}

export interface LanderInput {
  left: boolean
  right: boolean
  thrust: boolean
}

export const NO_LANDER_INPUT: LanderInput = { left: false, right: false, thrust: false }

export function createLanding(random: () => number = Math.random): LanderState {
  const padLeft = 120 + random() * (WORLD_W - 240 - PAD_WIDTH)
  return {
    x: WORLD_W / 2,
    y: 60,
    vx: (random() - 0.5) * 40,
    vy: 0,
    angle: 0,
    fuel: 100,
    pad: { left: padLeft, right: padLeft + PAD_WIDTH },
    status: 'flying',
    reasons: [],
  }
}

/** Why a touchdown was not safe. Empty means a safe landing. */
export function review(state: LanderState): LandingReason[] {
  const reasons: LandingReason[] = []
  if (Math.abs(state.vy) > SAFE_VERTICAL) reasons.push('vertical')
  if (Math.abs(state.vx) > SAFE_LATERAL) reasons.push('lateral')
  if (Math.abs(state.angle) > SAFE_ANGLE) reasons.push('angle')
  if (state.x < state.pad.left || state.x > state.pad.right) reasons.push('offPad')
  return reasons
}

/** Advances the lander by `dt` seconds. Mutates and returns the state. */
export function step(state: LanderState, input: LanderInput, dt: number): LanderState {
  if (state.status !== 'flying') return state
  state.angle += ((input.right ? 1 : 0) - (input.left ? 1 : 0)) * TURN_SPEED * dt
  if (input.thrust && state.fuel > 0) {
    state.fuel = Math.max(0, state.fuel - FUEL_PER_SECOND * dt)
    state.vx += Math.sin(state.angle) * THRUST * dt
    state.vy -= Math.cos(state.angle) * THRUST * dt
  }
  state.vy += GRAVITY * dt
  state.x += state.vx * dt
  state.y += state.vy * dt
  state.x = Math.min(WORLD_W - 10, Math.max(10, state.x))

  if (state.y + LANDER_HALF >= GROUND_Y) {
    state.y = GROUND_Y - LANDER_HALF
    state.reasons = review(state)
    state.status = state.reasons.length === 0 ? 'landed' : 'crashed'
  }
  return state
}
