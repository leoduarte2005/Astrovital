import { useEffect, useRef, useState } from 'react'
import { useI18n } from '@/lib/i18n'
import { Button } from '@/ui/Button'
import { GameControls, type ControlButton } from '../GameControls'
import { GameStat } from '../GameStat'
import { PALETTE, PIXEL_H, PIXEL_W } from '../palette'
import { makeStars, PixelBuffer } from '../pixels'
import { useControls } from '../useControls'
import { useGameLoop } from '../useGameLoop'
import styles from '../Game.module.css'
import { createGame, GEOMETRY, step, WORLD_W, type AsteroidsState, type Input } from './engine'

interface Hud {
  score: number
  lives: number
  wave: number
  over: boolean
}

const toHud = (s: AsteroidsState): Hud => ({ score: s.score, lives: s.lives, wave: s.wave, over: s.over })
const sameHud = (a: Hud, b: Hud) => a.score === b.score && a.lives === b.lives && a.wave === b.wave && a.over === b.over

/** World units per pixel of the buffer. */
const SCALE = WORLD_W / PIXEL_W
const STARS = makeStars(PIXEL_W, PIXEL_H, 70)

function drawFrame(px: PixelBuffer, s: AsteroidsState, thrusting: boolean, now: number): void {
  px.clear(PALETTE.space)
  for (const star of STARS) px.set(star.x, star.y, PALETTE.stars[star.tone] ?? PALETTE.space)

  // Rocks: a solid body with a darker crater, sized by the rules' radius.
  for (const rock of s.rocks) {
    const x = rock.x / SCALE
    const y = rock.y / SCALE
    const r = GEOMETRY.rockRadius[rock.size] / SCALE
    px.disc(x, y, r, PALETTE.rock[rock.size])
    px.disc(x + r * 0.3, y - r * 0.25, Math.max(1, r * 0.3), PALETTE.rockShade)
    px.disc(x - r * 0.35, y + r * 0.3, Math.max(1, r * 0.2), PALETTE.rockShade)
  }

  for (const shot of s.shots) px.rect(shot.x / SCALE - 1, shot.y / SCALE - 1, 2, 2, PALETTE.shot)

  // Ship: blinks while it cannot be hit; a flame behind it while thrusting.
  const ship = s.ship
  if (!s.over && (ship.invulnerable === 0 || Math.floor(now / 120) % 2 === 0)) {
    const x = ship.x / SCALE
    const y = ship.y / SCALE
    const r = (GEOMETRY.shipRadius / SCALE) * 1.6
    const a = ship.angle
    const point = (angle: number, length: number) => [x + Math.cos(angle) * length, y + Math.sin(angle) * length] as const
    const [nx, ny] = point(a, r * 1.3)
    const [lx, ly] = point(a + 2.5, r)
    const [rx, ry] = point(a - 2.5, r)
    if (thrusting) {
      const [fx, fy] = point(a + Math.PI, r * (1.3 + Math.random() * 0.5))
      const [bx1, by1] = point(a + 2.8, r * 0.6)
      const [bx2, by2] = point(a - 2.8, r * 0.6)
      px.triangle(bx1, by1, bx2, by2, fx, fy, PALETTE.flame)
    }
    px.triangle(nx, ny, lx, ly, rx, ry, PALETTE.ship)
    px.set(x, y, PALETTE.shipCore)
  }
}

/** Asteroids-style game in an 8-bit look: rotate, thrust, fire; rocks split when hit (rules in engine.ts). */
export function AsteroidsGame() {
  const { t, locale } = useI18n()
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const ctxRef = useRef<CanvasRenderingContext2D | null>(null)
  const pixelsRef = useRef<PixelBuffer | null>(null)
  // The first game is made once, in state, so no ref is read while rendering.
  const [initial] = useState(() => createGame())
  const game = useRef<AsteroidsState>(initial)
  const { controls, pressed, hold } = useControls()
  const [hud, setHud] = useState<Hud>(() => toHud(initial))
  const shown = useRef(hud)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    canvas.width = PIXEL_W
    canvas.height = PIXEL_H
    ctxRef.current = canvas.getContext('2d')
    pixelsRef.current = new PixelBuffer(PIXEL_W, PIXEL_H)
  }, [])

  useGameLoop((dt) => {
    const ctx = ctxRef.current
    const pixels = pixelsRef.current
    if (!ctx || !pixels) return
    const input: Input = { ...controls.current }
    step(game.current, input, dt)
    drawFrame(pixels, game.current, input.thrust, performance.now())
    pixels.present(ctx)
    const next = toHud(game.current)
    if (!sameHud(next, shown.current)) {
      shown.current = next
      setHud(next)
    }
  })

  const restart = () => {
    game.current = createGame()
    shown.current = toHud(game.current)
    setHud(shown.current)
  }

  const number = new Intl.NumberFormat(locale)
  const buttons: ControlButton[] = [
    { name: 'left', label: t('asteroids.control.left'), glyph: '←' },
    { name: 'thrust', label: t('asteroids.control.thrust'), glyph: '↑' },
    { name: 'right', label: t('asteroids.control.right'), glyph: '→' },
    { name: 'fire', label: t('asteroids.control.fire'), glyph: '●', keyHint: t('games.key.space') },
  ]

  return (
    <main className={styles.root}>
      <div className={styles.stage}>
        <canvas ref={canvasRef} className={styles.canvas} role="img" aria-label={t('games.asteroids.title')} />
        <div className={styles.overlay}>
          <GameStat label={t('asteroids.hud.score')} value={number.format(hud.score)} />
          <GameStat label={t('asteroids.hud.lives')} value={number.format(hud.lives)} />
          <GameStat label={t('asteroids.hud.wave')} value={number.format(hud.wave)} />
        </div>
      </div>
      {hud.over ? (
        <div className={styles.panel}>
          <p className={styles.panelTitle}>{t('asteroids.over')}</p>
          <GameStat label={t('asteroids.hud.score')} value={number.format(hud.score)} />
          <Button onClick={restart}>{t('asteroids.restart')}</Button>
        </div>
      ) : (
        <GameControls buttons={buttons} pressed={pressed} hold={hold} />
      )}
    </main>
  )
}
