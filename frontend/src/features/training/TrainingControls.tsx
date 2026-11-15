import type { Ref } from 'react'
import { useI18n } from '@/lib/i18n'
import { IconButton } from '@/ui/IconButton'
import { TRAINING_MONTHS, periodOf } from './behaviour'
import styles from './TrainingControls.module.css'

interface TrainingControlsProps {
  /** 0..23. */
  monthIndex: number
  playing: boolean
  onMonthChange: (monthIndex: number) => void
  onTogglePlay: () => void
  /** Text of the simulated date and time, written by the scene each simulated minute (not React state). */
  clockRef: Ref<HTMLSpanElement>
}

/** Month as "February 2025" in the active locale (from the training period). */
function monthLabel(monthIndex: number, locale: string): string {
  const [year, month] = periodOf(monthIndex).split('-').map(Number)
  return new Intl.DateTimeFormat(locale, { month: 'long', year: 'numeric', timeZone: 'UTC' }).format(
    Date.UTC(year ?? 2024, (month ?? 1) - 1, 1),
  )
}

/**
 * Timeline of the training hangar: which of the 24 months before the mission is on screen, play and pause of the
 * accelerated days, and the simulated clock. Fixed at the bottom centre, over the scene.
 */
export function TrainingControls({ monthIndex, playing, onMonthChange, onTogglePlay, clockRef }: TrainingControlsProps) {
  const { t, locale } = useI18n()
  const last = TRAINING_MONTHS - 1
  return (
    <div className={styles.root}>
      <div className={styles.panel} role="group" aria-label={t('training.controls.label')}>
        <div className={styles.row}>
          <IconButton icon="back" label={t('training.controls.previous')} onClick={() => onMonthChange(monthIndex - 1)} disabled={monthIndex <= 0} />
          <div className={styles.month}>
            <span className={styles.number}>{t('training.controls.month', { n: monthIndex + 1 })}</span>
            <span className={styles.period}>{monthLabel(monthIndex, locale)}</span>
          </div>
          <IconButton icon="next" label={t('training.controls.next')} onClick={() => onMonthChange(monthIndex + 1)} disabled={monthIndex >= last} />
          <IconButton icon={playing ? 'pause' : 'play'} label={t(playing ? 'training.controls.pause' : 'training.controls.play')} onClick={onTogglePlay} />
          <span ref={clockRef} className={styles.clock} role="timer" aria-label={t('training.controls.clock')} />
        </div>
        <input
          className={styles.slider}
          type="range"
          min={1}
          max={TRAINING_MONTHS}
          step={1}
          value={monthIndex + 1}
          onChange={(event) => onMonthChange(Number(event.target.value) - 1)}
          aria-label={t('training.controls.slider')}
        />
      </div>
    </div>
  )
}
