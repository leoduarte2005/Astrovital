import { useLayoutEffect, useMemo, useState } from 'react'
import { ASTRONAUT_PATH, sectionPath } from '@/features/astronaut'
import { ChatLog } from '@/features/chat'
import { CrewContextPanel, PrivacyIndicator, ShelterOverlay } from '@/features/crew'
import { TwinCanvas, type TwinAnchorId } from '@/features/twin3d'
import { hasOrganCharts, OrganCharts, SubsystemCharts, vitalFeed, VitalsPanel } from '@/features/vitals'
import { statureM } from '@/lib/model/stature'
import { getDataSource } from '@/lib/data'
import { crewStateStore, useCrewState } from '@/lib/data/crewState'
import { useSession } from '@/lib/data/session'
import { useCrewContext } from '@/lib/data/useCrewContext'
import { useI18n } from '@/lib/i18n'
import { navigate, previousRoute, useHashRoute } from '@/lib/utils/hashRoute'
import { leadScope, leadTarget } from '@/lib/utils/lead'
import { Button } from '@/ui/Button'
import styles from './MedicalFollowUpPage.module.css'

const CREW_PATH = '/crew'

/**
 * Medical follow-up as a telemetry cockpit: one contiguous grid. Left, who is on screen, the live vitals against
 * the crew member's own baseline, the cabin and the privacy statement; centre, the digital twin, with lead lines
 * from the vitals to the body; right, the charts of the selected organ (or the six subsystems) over the assistant.
 */
export default function MedicalFollowUpPage() {
  const { t } = useI18n()
  const crew = useSession((state) => state.activeCrew)
  const crewId = crew?.crewId ?? null
  const context = useCrewContext()
  const confirmedCrewId = useCrewState((state) => state.crewId)
  const missionMode = useCrewState((state) => state.missionMode)
  const switchFailed = useCrewState((state) => state.switchFailed)
  // Selected twin marker: its chart group (features/vitals/organGroups.ts) shows on the right.
  const [selected, setSelected] = useState<TwinAnchorId | null>(null)
  // The suit-fragmentation intro plays only when coming from `#/astronaut` to its medical tab; any other way in (reload,
  // another tab, the home) shows the twin at once. Decided once, when the page mounts.
  const path = useHashRoute()
  const [intro] = useState(() => path === sectionPath('medical') && previousRoute() === ASTRONAUT_PATH)

  // The crew member's own baseline by vital id, for the side panel and the dashed line of the charts.
  const baselines = useMemo<Partial<Record<string, number>>>(
    () =>
      context
        ? { heartRate: context.baseline.hrBpm, hrv: context.baseline.hrvMs, respRate: context.baseline.respBpm }
        : {},
    [context],
  )

  // The live link and the crew switch last as long as the home is mounted (rules/data-layer.md).
  // Layout effect: the mock confirms at once, so the twin mounts before the first paint.
  useLayoutEffect(() => {
    if (!crewId) return
    const source = getDataSource()
    source.open()
    source.setCrew(crewId)
    vitalFeed.start(source)
    return () => {
      vitalFeed.stop()
      source.close()
    }
  }, [crewId])

  if (!crew) return null

  // Name, twin and charts change only after the central confirms the crew member (guide §3C).
  const confirmed = confirmedCrewId === crew.crewId

  const retrySwitch = () => {
    crewStateStore.getState().clearFailure()
    getDataSource().setCrew(crew.crewId)
  }

  const organ = selected !== null && hasOrganCharts(selected) ? selected : null

  return (
    <main className={styles.root}>
      <aside className={`${styles.side} ${styles.left}`} aria-label={t('cockpit.left.label')} {...leadScope}>
        <CrewContextPanel member={crew} context={confirmed ? context : null} onSwitch={() => navigate(CREW_PATH)} />
        {confirmed && <VitalsPanel baselines={baselines} />}
        <div className={styles.fill} />
        <PrivacyIndicator />
      </aside>

      <section className={styles.stage} aria-label={t('cockpit.stage.label')}>
        {confirmed ? (
          <TwinCanvas
            skinTone={crew.skinTone}
            heightM={statureM(crew.nationality)}
            onSelect={setSelected}
            intro={intro}
            leadLines
          />
        ) : switchFailed ? (
          <div className={styles.status}>
            <p className={styles.statusText}>{t('home.switch.failed')}</p>
            <Button onClick={retrySwitch}>{t('common.retry')}</Button>
          </div>
        ) : (
          <p className={`${styles.status} ${styles.statusText}`}>{t('home.switch.loading')}</p>
        )}
      </section>

      <aside className={`${styles.side} ${styles.right}`} aria-label={t('cockpit.right.label')}>
        {confirmed && (
          <section className={styles.charts} {...leadScope}>
            <h2 className={styles.heading} {...(organ ? leadTarget(organ) : {})}>
              {organ ? t(`twin.marker.${organ}`) : t('cockpit.subsystems.title')}
            </h2>
            {organ ? <OrganCharts organ={organ} baselines={baselines} /> : <SubsystemCharts />}
            {!organ && <p className={styles.hint}>{t('cockpit.organ.hint')}</p>}
          </section>
        )}
        <section className={styles.assistant} aria-label={t('chat.drawer.title')}>
          <h2 className={styles.heading}>{t('chat.log.title')}</h2>
          <ChatLog />
        </section>
      </aside>

      {confirmed && missionMode === 'MODE_RADIATION_ALERT' && <ShelterOverlay />}
    </main>
  )
}
