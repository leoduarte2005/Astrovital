/**
 * Asteroids rules, written from scratch: the classic mechanics, with no code or assets copied.
 * Pure functions: the component draws the state and feeds the input. Logical world units, not pixels.
 */
/** 16:9, three times the pixel buffer (features/games/palette.ts). */
export const WORLD_W = 960
export const WORLD_H = 540

const SHIP_RADIUS = 12
const TURN_SPEED = 4.2 // rad/s
const THRUST = 260 // px/s²
const FRICTION = 0.35 // share of speed lost per second
const MAX_SPEED = 420
const SHOT_SPEED = 520
const SHOT_LIFE = 1.1 // s
const FIRE_INTERVAL = 0.25 // s
const RESPAWN_INVULNERABLE = 2.5 // s

export type RockSize = 3 | 2 | 1
const ROCK_RADIUS: Record<RockSize, number> = { 3: 46, 2: 26, 1: 14 }
const ROCK_POINTS: Record<RockSize, number> = { 3: 20, 2: 50, 1: 100 }

export interface Input {
  left: boolean
  right: boolean
  thrust: boolean
  fire: boolean
}

export interface Body {
  x: number
  y: number
  vx: number
  vy: number
}

export interface Ship extends Body {
  angle: number
  fireCooldown: number
  invulnerable: number
}

export interface Rock extends Body {
  size: RockSize
}

export interface Shot extends Body {
  life: number
}

export interface AsteroidsState {
  ship: Ship
  rocks: Rock[]
  shots: Shot[]
  score: number
  lives: number
  wave: number
  over: boolean
}

export const NO_INPUT: Input = { left: false, right: false, thrust: false, fire: false }

/** Geometry the component draws with, kept here so the rules and the picture agree. */
export const GEOMETRY = { shipRadius: SHIP_RADIUS, rockRadius: ROCK_RADIUS }

function wrap(body: Body): void {
  if (body.x < 0) body.x += WORLD_W
  if (body.x >= WORLD_W) body.x -= WORLD_W
  if (body.y < 0) body.y += WORLD_H
  if (body.y >= WORLD_H) body.y -= WORLD_H
}

function distance(a: Body, b: Body): number {
  return Math.hypot(a.x - b.x, a.y - b.y)
}

function spawnRock(size: RockSize, x: number, y: number, random: () => number): Rock {
  const angle = random() * Math.PI * 2
  const speed = 30 + random() * 60 + (3 - size) * 20
  return { x, y, vx: Math.cos(angle) * speed, vy: Math.sin(angle) * speed, size }
}

/** New rocks appear away from the ship. One more rock each wave. */
function spawnWave(state: AsteroidsState, random: () => number): void {
  const count = 2 + state.wave
  for (let i = 0; i < count; i++) {
    // Bounded: a poor random source must not hang the game. After the tries, the rock simply appears.
    let x = 0
    let y = 0
    for (let attempt = 0; attempt < 20; attempt++) {
      x = random() * WORLD_W
      y = random() * WORLD_H
      if (distance({ x, y, vx: 0, vy: 0 }, state.ship) >= 220) break
    }
    state.rocks.push(spawnRock(3, x, y, random))
  }
}

export function createGame(random: () => number = Math.random): AsteroidsState {
  const state: AsteroidsState = {
    ship: {
      x: WORLD_W / 2,
      y: WORLD_H / 2,
      vx: 0,
      vy: 0,
      angle: -Math.PI / 2,
      fireCooldown: 0,
      invulnerable: RESPAWN_INVULNERABLE,
    },
    rocks: [],
    shots: [],
    score: 0,
    lives: 3,
    wave: 1,
    over: false,
  }
  spawnWave(state, random)
  return state
}

/** Advances the game by `dt` seconds. Mutates and returns the state. */
export function step(state: AsteroidsState, input: Input, dt: number, random: () => number = Math.random): AsteroidsState {
  if (state.over) return state
  const ship = state.ship

  // Ship: turn, thrust, friction, a speed cap, fire.
  ship.angle += ((input.right ? 1 : 0) - (input.left ? 1 : 0)) * TURN_SPEED * dt
  if (input.thrust) {
    ship.vx += Math.cos(ship.angle) * THRUST * dt
    ship.vy += Math.sin(ship.angle) * THRUST * dt
  }
  const keep = Math.max(0, 1 - FRICTION * dt)
  ship.vx *= keep
  ship.vy *= keep
  const speed = Math.hypot(ship.vx, ship.vy)
  if (speed > MAX_SPEED) {
    ship.vx = (ship.vx / speed) * MAX_SPEED
    ship.vy = (ship.vy / speed) * MAX_SPEED
  }
  ship.x += ship.vx * dt
  ship.y += ship.vy * dt
  wrap(ship)
  ship.invulnerable = Math.max(0, ship.invulnerable - dt)
  ship.fireCooldown = Math.max(0, ship.fireCooldown - dt)
  if (input.fire && ship.fireCooldown === 0) {
    ship.fireCooldown = FIRE_INTERVAL
    state.shots.push({
      x: ship.x + Math.cos(ship.angle) * SHIP_RADIUS,
      y: ship.y + Math.sin(ship.angle) * SHIP_RADIUS,
      vx: Math.cos(ship.angle) * SHOT_SPEED,
      vy: Math.sin(ship.angle) * SHOT_SPEED,
      life: SHOT_LIFE,
    })
  }

  // Shots and rocks move; shots expire.
  for (const shot of state.shots) {
    shot.x += shot.vx * dt
    shot.y += shot.vy * dt
    shot.life -= dt
    wrap(shot)
  }
  state.shots = state.shots.filter((shot) => shot.life > 0)
  for (const rock of state.rocks) {
    rock.x += rock.vx * dt
    rock.y += rock.vy * dt
    wrap(rock)
  }

  // A shot hits a rock: a big rock splits into two smaller ones, a small one is gone.
  for (const shot of [...state.shots]) {
    const hit = state.rocks.find((rock) => distance(shot, rock) < ROCK_RADIUS[rock.size])
    if (!hit) continue
    state.shots = state.shots.filter((other) => other !== shot)
    state.rocks = state.rocks.filter((rock) => rock !== hit)
    state.score += ROCK_POINTS[hit.size]
    if (hit.size > 1) {
      const smaller = (hit.size - 1) as RockSize
      state.rocks.push(spawnRock(smaller, hit.x, hit.y, random), spawnRock(smaller, hit.x, hit.y, random))
    }
  }

  // A rock hits the ship: one life less, back in the middle and invulnerable for a while.
  if (ship.invulnerable === 0) {
    const crash = state.rocks.find((rock) => distance(ship, rock) < ROCK_RADIUS[rock.size] + SHIP_RADIUS)
    if (crash) {
      state.lives -= 1
      if (state.lives <= 0) {
        state.over = true
        return state
      }
      ship.x = WORLD_W / 2
      ship.y = WORLD_H / 2
      ship.vx = 0
      ship.vy = 0
      ship.invulnerable = RESPAWN_INVULNERABLE
    }
  }

  // Field cleared: next wave.
  if (state.rocks.length === 0) {
    state.wave += 1
    spawnWave(state, random)
  }
  return state
}
