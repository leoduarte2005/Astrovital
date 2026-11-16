import { useI18n } from '@/lib/i18n'
import type { CrewMember } from '@/lib/model/crew'
import { missionPhase, type CrewContext } from '@/lib/model/crewContext'
import { IconButton } from '@/ui/IconButton'
import styles from './CrewContextPanel.module.css'

interface CrewContextPanelProps {
  member: CrewMember
  /** Null while the context loads: the identity shows at once, the watch list after. */
  context: CrewContext | null
  onSwitch: () => void
}

/**
 * Top cell of the medical page's left column: who is on screen, the phase and day of the mission, and what the
 * assistant watches more closely for this person (from the crew context). Replaces the floating corner card there.
 */
export function CrewContextPanel({ member, context, onSwitch }: CrewContextPanelProps) {
  const { t, locale } = useI18n()
  const country = new Intl.DisplayNames([locale], { type: 'region' }).of(member.nationality)
  const phase = missionPhase(member.missionDay)

  return (
    <div className={styles.root}>
      <section className={styles.section} aria-label={t('crew.summary.label')}>
        <div className={styles.header}>
          <h2 className={styles.name}>{member.fullName}</h2>
          <IconButton icon="swap" size="sm" label={t('home.switchCrew')} onClick={onSwitch} />
        </div>
        <p className={styles.line}>
          {t(`enum.crewRole.${member.role}`)} · {country}
        </p>
        <p className={styles.mission}>
          {t(`cockpit.phase.${phase}`)}
          {member.missionDay !== null && member.missionDay > 0 && ` · ${t('cockpit.missionDay', { day: member.missionDay })}`}
        </p>
      </section>
      {context && context.watchlist.length > 0 && (
        <section className={styles.section} aria-labelledby="crew-watch-title">
          <h2 id="crew-watch-title" className={styles.heading}>
            {t('cockpit.watch.title')}
          </h2>
          {/* Free text from the crew context: not translated (rules/i18n.md). */}
          <ul className={styles.list}>
            {context.watchlist.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
