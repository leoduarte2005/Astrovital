import { useEffect, useMemo, useRef } from 'react'
import { useI18n } from '@/lib/i18n'
import { leadTarget } from '@/lib/utils/lead'
import { vitalFeed } from './vitalFeed'
import { useStatusMessage } from './vitalStatus'
import { CO2, HEART_RATE, HRV, HUMIDITY, PRESSURE, RESP_RATE, SPO2, TEMP, type VitalSpec } from './vitalSpecs'
import styles from './VitalsPanel.module.css'

interface Row {
  spec: VitalSpec
  /** Twin anchor the row's lead line points to. */
  lead?: string
}

const VITAL_ROWS: Row[] = [
  { spec: HEART_RATE, lead: 'heart' },
  { spec: HRV, lead: 'heart' },
  { spec: SPO2, lead: 'lungs' },
  { spec: RESP_RATE, lead: 'lungs' },
]

const CABIN_ROWS: Row[] = [{ spec: CO2 }, { spec: TEMP }, { spec: HUMIDITY }, { spec: PRESSURE }]

interface Cells {
  value: HTMLSpanElement | null
  delta: HTMLSpanElement | null
}

function latest(id: string): number | null {
  const { y } = vitalFeed.lineFeed(id).read()
  for (let i = y.length - 1; i >= 0; i--) {
    const value = y[i]
    if (value !== null && value !== undefined) return value
  }
  return null
}

export interface VitalsPanelProps {
  /** The crew member's own baseline by vital id, from the crew context. Rows without one show no comparison. */
  baselines: Partial<Record<string, number>>
}

/**
 * Left column of the medical page: the live vitals against the crew member's own baseline, then the cabin
 * environment. Values are written to the DOM on animation frames, outside React (rules/performance.md).
 * The difference to the baseline is a number with a sign, never a colour.
 */
export function VitalsPanel({ baselines }: VitalsPanelProps) {
  const { t, locale } = useI18n()
  const message = useStatusMessage(t, locale)
  const cells = useRef(new Map<string, Cells>())
  const baselinesRef = useRef(baselines)
  useEffect(() => {
    baselinesRef.current = baselines
  })

  const formats = useMemo(() => {
    const byId = new Map<string, Intl.NumberFormat>()
    for (const { spec } of [...VITAL_ROWS, ...CABIN_ROWS]) {
      byId.set(spec.id, new Intl.NumberFormat(locale, { minimumFractionDigits: spec.decimals, maximumFractionDigits: spec.decimals }))
    }
    const percent = new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 0, signDisplay: 'exceptZero' })
    return { byId, percent }
  }, [locale])

  useEffect(() => {
    let frame = 0
    const render = () => {
      frame = 0
      for (const [id, { value, delta }] of cells.current) {
        const current = latest(id)
        if (value) value.textContent = current === null ? '—' : (formats.byId.get(id)?.format(current) ?? String(current))
        const base = baselinesRef.current[id]
        if (delta) delta.textContent = current === null || !base ? '' : ` · ${formats.percent.format((current - base) / base)}`
      }
    }
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(render)
    }
    render()
    // Every line feed shares one change signal: one subscription covers all rows.
    const unsubscribe = vitalFeed.lineFeed(HEART_RATE.id).subscribe(schedule)
    return () => {
      cancelAnimationFrame(frame)
      unsubscribe()
    }
  }, [formats])

  const cellRef = (id: string, key: keyof Cells) => (element: HTMLSpanElement | null) => {
    const entry = cells.current.get(id) ?? { value: null, delta: null }
    entry[key] = element
    cells.current.set(id, entry)
  }

  const renderRow = ({ spec, lead }: Row) => {
    const base = baselines[spec.id]
    return (
      <div key={spec.id} className={styles.row} {...(lead ? leadTarget(lead) : {})}>
        <dt className={styles.label}>{t(spec.labelKey)}</dt>
        <dd className={styles.value}>
          <span ref={cellRef(spec.id, 'value')}>—</span>
          <span className={styles.unit}>{spec.unit}</span>
        </dd>
        {base !== undefined && (
          <dd className={styles.base}>
            {t('chart.baseline', { value: formats.byId.get(spec.id)?.format(base) ?? String(base) })}
            <span ref={cellRef(spec.id, 'delta')} />
          </dd>
        )}
      </div>
    )
  }

  return (
    <div className={styles.root}>
      <section className={styles.section} aria-labelledby="vitals-panel-title">
        <h2 id="vitals-panel-title" className={styles.heading}>
          {t('cockpit.vitals.title')}
        </h2>
        {message !== null && <p className={styles.message}>{message}</p>}
        <dl className={styles.list}>{VITAL_ROWS.map(renderRow)}</dl>
      </section>
      <section className={styles.section} aria-labelledby="cabin-panel-title">
        <h2 id="cabin-panel-title" className={styles.heading}>
          {t('cockpit.cabin.title')}
        </h2>
        <dl className={styles.list}>{CABIN_ROWS.map(renderRow)}</dl>
      </section>
    </div>
  )
}
