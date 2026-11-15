import { useEffect, useRef, useState } from 'react'
import { useI18n, type MessageKey } from '@/lib/i18n'
import { Button } from '@/ui/Button'
import { GameControls, type ControlButton } from '../GameControls'
import { GameStat } from '../GameStat'
import { PALETTE, PIXEL_H, PIXEL_W } from '../palette'
import { makeStars, PixelBuffer } from '../pixels'
import { useControls } from '../useControls'
import { useGameLoop } from '../useGameLoop'
import styles from '../Game.module.css'
import {
  createLanding,
  GROUND_Y,
  LANDER_HALF,
  SAFE_ANGLE,
  SAFE_LATERAL,
  SAFE_VERTICAL,
  step,
  UNITS_PER_METRE,
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
  altitude: number
  fuel: number
  vertical: number
  lateral: number
  angle: number
  status: LanderState['status']
}

/** Rounded the way the HUD shows them, so the HUD only re-renders when a shown value changes. */
const toHud = (s: LanderState): Hud => ({
  altitude: Math.max(0, Math.round(((GROUND_Y - LANDER_HALF - s.y) / UNITS_PER_METRE) * 10) / 10),
  fuel: Math.round(s.fuel),
  vertical: Math.round((s.vy / UNITS_PER_METRE) * 10) / 10,
  lateral: Math.round((s.vx / UNITS_PER_METRE) * 10) / 10,
  angle: Math.round((s.angle * 180) / Math.PI),
  status: s.status,
})
const sameHud = (a: Hud, b: Hud) =>
  a.altitude === b.altitude &&
  a.fuel === b.fuel &&
  a.vertical === b.vertical &&
  a.lateral === b.lateral &&
  a.angle === b.angle &&
  a.status === b.status

/** World units per pixel of the buffer. */
const SCALE = WORLD_W / PIXEL_W
const GROUND_PX = GROUND_Y / SCALE
const STARS = makeStars(PIXEL_W, Math.floor(GROUND_PX), 70)

/** Mountain ridge height above the ground line, in pixels, at column x. Fixed shape, no randomness. */
const ridge = (x: number): number =>
  GROUND_PX - (14 + 8 * Math.sin(x * 0.045) + 4 * Math.sin(x * 0.17 + 1.3) + 2 * Math.sin(x * 0.41))

function drawEarth(px: PixelBuffer, cx: number, cy: number, r: number): void {
  px.disc(cx, cy, r, PALETTE.earthBlue)
  px.disc(cx - r * 0.4, cy - r * 0.2, r * 0.35, PALETTE.earthGreen)
  px.disc(cx + r * 0.35, cy + r * 0.35, r * 0.3, PALETTE.earthGreen)
  px.line(cx - r * 0.8, cy + r * 0.5, cx + r * 0.2, cy - r * 0.9, PALETTE.earthCloud)
  px.line(cx - r * 0.2, cy + r * 0.9, cx + r * 0.8, cy - r * 0.2, PALETTE.earthCloud)
}

function drawFrame(px: PixelBuffer, s: LanderState, thrusting: boolean, now: number): void {
  px.clear(PALETTE.space)
  for (const star of STARS) px.set(star.x, star.y, PALETTE.stars[star.tone] ?? PALETTE.space)
  drawEarth(px, PIXEL_W - 26, 22, 12)

  // Mountains, then the flat ground the pad sits on.
  for (let x = 0; x < PIXEL_W; x++) {
    const top = Math.round(ridge(x))
    px.rect(x, top, 1, GROUND_PX - top, PALETTE.mountain)
    px.set(x, top, PALETTE.mountainRidge)
  }
  px.rect(0, GROUND_PX, PIXEL_W, PIXEL_H - GROUND_PX, PALETTE.ground)
  px.rect(0, GROUND_PX, PIXEL_W, 1, PALETTE.groundEdge)

  // Pad with a flag on each end.
  const padLeft = s.pad.left / SCALE
  const padRight = s.pad.right / SCALE
  px.rect(padLeft, GROUND_PX - 2, padRight - padLeft, 2, PALETTE.pad)
  for (const x of [padLeft - 1, padRight]) {
    px.rect(x, GROUND_PX - 14, 1, 14, PALETTE.pole)
    px.triangle(x + 1, GROUND_PX - 14, x + 1, GROUND_PX - 9, x + 7, GROUND_PX - 11.5, PALETTE.flag)
  }

  // Lander: grey body with a blue window, brown base plate, legs. Rotated with the rules' angle.
  const x = s.x / SCALE
  const y = s.y / SCALE
  const h = LANDER_HALF / SCALE + 1
  const cos = Math.cos(s.angle)
  const sin = Math.sin(s.angle)
  const at = (dx: number, dy: number) => [x + dx * cos - dy * sin, y + dx * sin + dy * cos] as const
  const quad = (a: readonly [number, number], b: readonly [number, number], c: readonly [number, number], d: readonly [number, number], color: number) =>
    px.quad(a[0], a[1], b[0], b[1], c[0], c[1], d[0], d[1], color)

  if (thrusting && s.status === 'flying') {
    const flame = 2 + Math.random() * 2 + ((Math.floor(now / 80) % 2) * 1)
    px.triangle(...at(-0.45 * h, 1.45 * h), ...at(0.45 * h, 1.45 * h), ...at(0, (1.45 + flame / 4) * h), PALETTE.flame)
    px.triangle(...at(-0.2 * h, 1.45 * h), ...at(0.2 * h, 1.45 * h), ...at(0, (1.45 + flame / 8) * h), PALETTE.flameCore)
  }
  px.line(...at(-0.9 * h, 1.1 * h), ...at(-1.5 * h, 1.9 * h), PALETTE.landerLegs)
  px.line(...at(0.9 * h, 1.1 * h), ...at(1.5 * h, 1.9 * h), PALETTE.landerLegs)
  quad(at(-h, -0.9 * h), at(h, -0.9 * h), at(h, 0.5 * h), at(-h, 0.5 * h), PALETTE.lander)
  quad(at(-0.45 * h, -0.6 * h), at(0.45 * h, -0.6 * h), at(0.45 * h, -0.1 * h), at(-0.45 * h, -0.1 * h), PALETTE.landerWindow)
  quad(at(-1.3 * h, 0.5 * h), at(1.3 * h, 0.5 * h), at(1.3 * h, 0.9 * h), at(-1.3 * h, 0.9 * h), PALETTE.landerBase)
}

/** Landing practice: gravity, thrust and fuel. The end shows what to review; it is not a score. */
export function LandingGame() {
  const { t, locale } = useI18n()
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const ctxRef = useRef<CanvasRenderingContext2D | null>(null)
  const pixelsRef = useRef<PixelBuffer | null>(null)
  // The first landing is made once, in state, so no ref is read while rendering.
  const [initial] = useState(() => createLanding())
  const lander = useRef<LanderState>(initial)
  const { controls, pressed, hold } = useControls()
  const [hud, setHud] = useState<Hud>(() => toHud(initial))
  const shown = useRef(hud)
  const [reasons, setReasons] = useState<LandingReason[]>([])

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
    const input: LanderInput = { left: controls.current.left, right: controls.current.right, thrust: controls.current.thrust }
    step(lander.current, input, dt)
    drawFrame(pixels, lander.current, input.thrust && lander.current.fuel > 0, performance.now())
    pixels.present(ctx)
    const next = toHud(lander.current)
    if (!sameHud(next, shown.current)) {
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

  const oneDecimal = new Intl.NumberFormat(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 })
  const whole = new Intl.NumberFormat(locale, { maximumFractionDigits: 0 })
  const limit = (value: string) => t('landing.hud.limit', { value })
  const overLabel = t('landing.hud.over')
  const verticalLimit = SAFE_VERTICAL / UNITS_PER_METRE
  const lateralLimit = SAFE_LATERAL / UNITS_PER_METRE
  const angleLimit = Math.round((SAFE_ANGLE * 180) / Math.PI)
  const landed = hud.status === 'landed'
  const over = hud.status !== 'flying'
  const buttons: ControlButton[] = [
    { name: 'left', label: t('landing.control.left'), glyph: '←' },
    { name: 'thrust', label: t('landing.control.thrust'), glyph: '↑' },
    { name: 'right', label: t('landing.control.right'), glyph: '→' },
  ]

  return (
    <main className={styles.root}>
      <div className={styles.stage}>
        <canvas ref={canvasRef} className={styles.canvas} role="img" aria-label={t('games.landing.title')} />
        <div className={styles.overlay}>
          <GameStat label={t('landing.hud.altitude')} value={oneDecimal.format(hud.altitude)} unit="m" />
          <GameStat
            label={t('landing.hud.vertical')}
            value={oneDecimal.format(Math.abs(hud.vertical))}
            unit="m/s"
            note={limit(oneDecimal.format(verticalLimit))}
            over={Math.abs(hud.vertical) > verticalLimit}
            overLabel={overLabel}
          />
          <GameStat
            label={t('landing.hud.lateral')}
            value={oneDecimal.format(Math.abs(hud.lateral))}
            unit="m/s"
            note={limit(oneDecimal.format(lateralLimit))}
            over={Math.abs(hud.lateral) > lateralLimit}
            overLabel={overLabel}
          />
          <GameStat label={t('landing.hud.fuel')} value={whole.format(hud.fuel)} unit="%" />
          <GameStat
            label={t('landing.hud.angle')}
            value={whole.format(hud.angle)}
            unit="°"
            note={limit(`${whole.format(angleLimit)}°`)}
            over={Math.abs(hud.angle) > angleLimit}
            overLabel={overLabel}
          />
        </div>
      </div>
      {over ? (
        <div className={styles.panel}>
          <p className={styles.panelTitle}>{landed ? t('landing.landed') : t('landing.crashed')}</p>
          <div className={styles.resultRow}>
            <span>{t('landing.hud.fuel')}</span>
            <span className={styles.resultValue}>{whole.format(hud.fuel)}%</span>
          </div>
          <div className={styles.resultRow}>
            <span>{t('landing.hud.vertical')}</span>
            <span className={styles.resultValue}>
              {oneDecimal.format(Math.abs(hud.vertical))} m/s
            </span>
          </div>
          <div className={styles.resultRow}>
            <span>{t('landing.hud.angle')}</span>
            <span className={styles.resultValue}>{whole.format(hud.angle)}°</span>
          </div>
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
        <GameControls buttons={buttons} pressed={pressed} hold={hold} />
      )}
    </main>
  )
}
