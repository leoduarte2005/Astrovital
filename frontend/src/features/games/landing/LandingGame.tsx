import { useEffect, useRef, useState } from 'react'
import { useI18n, type MessageKey } from '@/lib/i18n'
import { Button } from '@/ui/Button'
import { useControls } from '../useControls'
import { useGameLoop } from '../useGameLoop'
import styles from '../Game.module.css'
import {
  createLanding,
  GROUND_Y,
  LANDER_HALF,
  step,
  WORLD_H,
  WORLD_W,
  type LanderInput,
  type LanderState,
  type LandingReason,
} from './physics'

const REASON_KEY: Record<LandingReason, MessageKey> = {
  vertical: 'landing.reason.vertical',
  lateral: 'landing.reason.lateral',
  angle: 'landing.reason.angle',
  offPad: 'landing.reason.offPad',
}

interface Hud {
  fuel: number
  vertical: number
  angle: number
  status: LanderState['status']
}

const toHud = (s: LanderState): Hud => ({ fuel: s.fuel, vertical: s.vy, angle: s.angle, status: s.status })

function drawFrame(ctx: CanvasRenderingContext2D, s: LanderState, ink: string, thrusting: boolean): void {
  ctx.clearRect(0, 0, WORLD_W, WORLD_H)
  ctx.strokeStyle = ink
  ctx.fillStyle = ink
  ctx.lineWidth = 1.5

  // Ground, with the pad drawn thicker.
  ctx.beginPath()
  ctx.moveTo(0, GROUND_Y)
  ctx.lineTo(WORLD_W, GROUND_Y)
  ctx.stroke()
  ctx.lineWidth = 4
  ctx.beginPath()
  ctx.moveTo(s.pad.left, GROUND_Y)
  ctx.lineTo(s.pad.right, GROUND_Y)
  ctx.stroke()
  ctx.lineWidth = 1.5

  // Lander: a triangle, with a flame while thrusting.
  const cos = Math.cos(s.angle)
  const sin = Math.sin(s.angle)
  const at = (dx: number, dy: number) => [s.x + dx * cos - dy * sin, s.y + dx * sin + dy * cos] as const
  ctx.beginPath()
  ctx.moveTo(...at(0, -LANDER_HALF))
  ctx.lineTo(...at(LANDER_HALF, LANDER_HALF))
  ctx.lineTo(...at(-LANDER_HALF, LANDER_HALF))
  ctx.closePath()
  ctx.stroke()
  if (thrusting && s.status === 'flying') {
    ctx.beginPath()
    ctx.moveTo(...at(-5, LANDER_HALF))
    ctx.lineTo(...at(0, LANDER_HALF + 14))
    ctx.lineTo(...at(5, LANDER_HALF))
    ctx.stroke()
  }
}

/** Landing practice: gravity, thrust and fuel. The end shows what to review; it is not a score. */
export function LandingGame() {
  const { t, locale } = useI18n()
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const ctxRef = useRef<CanvasRenderingContext2D | null>(null)
  // The first landing is made once, in state, so no ref is read while rendering.
  const [initial] = useState(() => createLanding())
  const lander = useRef<LanderState>(initial)
  const controls = useControls()
  const [hud, setHud] = useState<Hud>(() => toHud(initial))
  const shown = useRef(hud)
  const [reasons, setReasons] = useState<LandingReason[]>([])
  const ink = useRef('#f9f8f2')

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
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
    const input: LanderInput = { ...controls.current }
    step(lander.current, input, dt)
    drawFrame(ctx, lander.current, ink.current, input.thrust && lander.current.fuel > 0)
    const next = toHud(lander.current)
    const changed = next.status !== shown.current.status || Math.round(next.fuel) !== Math.round(shown.current.fuel)
    if (changed || next.status !== 'flying') {
      if (next.status !== 'flying' && shown.current.status === 'flying') setReasons(lander.current.reasons)
      shown.current = next
      setHud(next)
    }
  })

  const restart = () => {
    lander.current = createLanding()
    shown.current = toHud(lander.current)
    setHud(shown.current)
    setReasons([])
  }

  const number = new Intl.NumberFormat(locale, { maximumFractionDigits: 0 })
  const press = (name: keyof LanderInput) => ({
    onPointerDown: () => {
      controls.current[name] = true
    },
    onPointerUp: () => {
      controls.current[name] = false
    },
    onPointerLeave: () => {
      controls.current[name] = false
    },
    onPointerCancel: () => {
      controls.current[name] = false
    },
  })
  const landed = hud.status === 'landed'
  const over = hud.status !== 'flying'

  return (
    <main className={styles.root}>
      <div className={styles.hud}>
        <span>
          {t('landing.hud.fuel')} <span className={styles.hudValue}>{number.format(hud.fuel)}%</span>
        </span>
        <span>
          {t('landing.hud.vertical')} <span className={styles.hudValue}>{number.format(hud.vertical)}</span>
        </span>
        <span>
          {t('landing.hud.angle')}{' '}
          <span className={styles.hudValue}>{number.format((hud.angle * 180) / Math.PI)}°</span>
        </span>
      </div>
      <canvas ref={canvasRef} className={styles.canvas} role="img" aria-label={t('games.landing.title')} />
      {over ? (
        <div className={styles.panel}>
          <p className={styles.panelTitle}>{landed ? t('landing.landed') : t('landing.crashed')}</p>
          {!landed && reasons.length > 0 && (
            <>
              <p className={styles.panelText}>{t('landing.review')}</p>
              <ul className={styles.list}>
                {reasons.map((reason) => (
                  <li key={reason}>{t(REASON_KEY[reason])}</li>
                ))}
              </ul>
            </>
          )}
          <Button onClick={restart}>{t('landing.restart')}</Button>
        </div>
      ) : (
        <div className={styles.controls}>
          <button type="button" className={styles.control} aria-label={t('landing.control.left')} {...press('left')}>
            ←
          </button>
          <button type="button" className={styles.control} aria-label={t('landing.control.thrust')} {...press('thrust')}>
            ↑
          </button>
          <button type="button" className={styles.control} aria-label={t('landing.control.right')} {...press('right')}>
            →
          </button>
        </div>
      )}
    </main>
  )
}
