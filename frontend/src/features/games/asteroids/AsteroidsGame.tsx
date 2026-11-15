import { useEffect, useRef, useState } from 'react'
import { useI18n } from '@/lib/i18n'
import { Button } from '@/ui/Button'
import { useControls } from '../useControls'
import { useGameLoop } from '../useGameLoop'
import styles from '../Game.module.css'
import { createGame, GEOMETRY, step, WORLD_H, WORLD_W, type AsteroidsState, type Input } from './engine'

interface Hud {
  score: number
  lives: number
  wave: number
  over: boolean
}

const toHud = (s: AsteroidsState): Hud => ({ score: s.score, lives: s.lives, wave: s.wave, over: s.over })
const sameHud = (a: Hud, b: Hud) => a.score === b.score && a.lives === b.lives && a.wave === b.wave && a.over === b.over

function drawFrame(ctx: CanvasRenderingContext2D, s: AsteroidsState, ink: string, now: number): void {
  ctx.clearRect(0, 0, WORLD_W, WORLD_H)
  ctx.strokeStyle = ink
  ctx.fillStyle = ink
  ctx.lineWidth = 1.5

  const ship = s.ship
  // The ship blinks while it cannot be hit.
  if (!s.over && (ship.invulnerable === 0 || Math.floor(now / 120) % 2 === 0)) {
    const r = GEOMETRY.shipRadius
    ctx.beginPath()
    ctx.moveTo(ship.x + Math.cos(ship.angle) * r * 1.4, ship.y + Math.sin(ship.angle) * r * 1.4)
    ctx.lineTo(ship.x + Math.cos(ship.angle + 2.4) * r, ship.y + Math.sin(ship.angle + 2.4) * r)
    ctx.lineTo(ship.x + Math.cos(ship.angle - 2.4) * r, ship.y + Math.sin(ship.angle - 2.4) * r)
    ctx.closePath()
    ctx.stroke()
  }
  for (const rock of s.rocks) {
    ctx.beginPath()
    ctx.arc(rock.x, rock.y, GEOMETRY.rockRadius[rock.size], 0, Math.PI * 2)
    ctx.stroke()
  }
  for (const shot of s.shots) {
    ctx.beginPath()
    ctx.arc(shot.x, shot.y, 2, 0, Math.PI * 2)
    ctx.fill()
  }
}

/** Asteroids-style game: rotate, thrust, fire; rocks split when hit. Own rules and drawing (see engine.ts). */
export function AsteroidsGame() {
  const { t, locale } = useI18n()
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const ctxRef = useRef<CanvasRenderingContext2D | null>(null)
  // The first game is made once, in state, so no ref is read while rendering.
  const [initial] = useState(() => createGame())
  const game = useRef<AsteroidsState>(initial)
  const controls = useControls()
  const [hud, setHud] = useState<Hud>(() => toHud(initial))
  const shown = useRef(hud)
  const ink = useRef('#f9f8f2')

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    // Backing store at device resolution; drawing stays in world units.
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    canvas.width = WORLD_W * dpr
    canvas.height = WORLD_H * dpr
    const ctx = canvas.getContext('2d')
    if (ctx) ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctxRef.current = ctx
    const token = getComputedStyle(document.documentElement).getPropertyValue('--ink').trim()
    if (token) ink.current = token
  }, [])

  useGameLoop((dt) => {
    const ctx = ctxRef.current
    if (!ctx) return
    const input: Input = { ...controls.current }
    step(game.current, input, dt)
    drawFrame(ctx, game.current, ink.current, performance.now())
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
  const hold = (name: keyof Input, pressed: boolean) => () => {
    controls.current[name] = pressed
  }
  const press = (name: keyof Input) => ({
    onPointerDown: hold(name, true),
    onPointerUp: hold(name, false),
    onPointerLeave: hold(name, false),
    onPointerCancel: hold(name, false),
  })

  return (
    <main className={styles.root}>
      <div className={styles.hud}>
        <span>
          {t('asteroids.hud.score')} <span className={styles.hudValue}>{number.format(hud.score)}</span>
        </span>
        <span>
          {t('asteroids.hud.lives')} <span className={styles.hudValue}>{hud.lives}</span>
        </span>
        <span>
          {t('asteroids.hud.wave')} <span className={styles.hudValue}>{hud.wave}</span>
        </span>
      </div>
      <canvas ref={canvasRef} className={styles.canvas} role="img" aria-label={t('games.asteroids.title')} />
      {hud.over ? (
        <div className={styles.panel}>
          <p className={styles.panelTitle}>{t('asteroids.over')}</p>
          <p className={styles.panelText}>
            {t('asteroids.hud.score')} {number.format(hud.score)}
          </p>
          <Button onClick={restart}>{t('asteroids.restart')}</Button>
        </div>
      ) : (
        <div className={styles.controls}>
          <button type="button" className={styles.control} aria-label={t('asteroids.control.left')} {...press('left')}>
            ←
          </button>
          <button type="button" className={styles.control} aria-label={t('asteroids.control.thrust')} {...press('thrust')}>
            ↑
          </button>
          <button type="button" className={styles.control} aria-label={t('asteroids.control.right')} {...press('right')}>
            →
          </button>
          <button type="button" className={styles.control} aria-label={t('asteroids.control.fire')} {...press('fire')}>
            •
          </button>
        </div>
      )}
    </main>
  )
}
