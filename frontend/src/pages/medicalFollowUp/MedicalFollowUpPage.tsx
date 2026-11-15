import { useLayoutEffect, useState } from 'react'
import { ASTRONAUT_PATH, sectionPath } from '@/features/astronaut'
import { TwinCanvas, type TwinAnchorId } from '@/features/twin3d'
import { CrewInfoCard, ShelterOverlay } from '@/features/crew'
import { hasOrganCharts, MetricsPanel, OrganCharts, vitalFeed } from '@/features/vitals'
import { statureM } from '@/lib/model/stature'
import { getDataSource } from '@/lib/data'
import { crewStateStore, useCrewState } from '@/lib/data/crewState'
import { useSession } from '@/lib/data/session'
import { useI18n } from '@/lib/i18n'
import { previousRoute, useHashRoute } from '@/lib/utils/hashRoute'
import { Button } from '@/ui/Button'
import styles from './MedicalFollowUpPage.module.css'

export default function MedicalFollowUpPage() {
  const { t } = useI18n()
  const crew = useSession((state) => state.activeCrew)
  const crewId = crew?.crewId ?? null
  const confirmedCrewId = useCrewState((state) => state.crewId)
  const missionMode = useCrewState((state) => state.missionMode)
  const switchFailed = useCrewState((state) => state.switchFailed)
  // Selected twin marker: its chart group (features/vitals/organGroups.ts) shows on the right.
  const [selected, setSelected] = useState<TwinAnchorId | null>(null)
  // The suit-fragmentation intro plays only when coming from `#/astronaut` to its medical tab; any other way in (reload,
  // another tab, the home) shows the twin at once. Decided once, when the page mounts.
  const path = useHashRoute()
  const [intro] = useState(() => path === sectionPath('medical') && previousRoute() === ASTRONAUT_PATH)

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

  return (
    <main className={styles.root}>
      <section className={styles.stage}>
        {confirmed ? (
          <>
            <TwinCanvas skinTone={crew.skinTone} heightM={statureM(crew.nationality)} onSelect={setSelected} intro={intro} />
            <div className={styles.floating}>
              <CrewInfoCard member={crew}>
                <MetricsPanel />
              </CrewInfoCard>
            </div>
            {selected !== null && hasOrganCharts(selected) && (
              <div className={styles.charts}>
                <OrganCharts organ={selected} />
              </div>
            )}
          </>
        ) : switchFailed ? (
          <div className={styles.status}>
            <p className={styles.statusText}>{t('home.switch.failed')}</p>
            <Button onClick={retrySwitch}>{t('common.retry')}</Button>
          </div>
        ) : (
          <p className={styles.statusText}>{t('home.switch.loading')}</p>
        )}
      </section>
      {confirmed && missionMode === 'MODE_RADIATION_ALERT' && <ShelterOverlay />}
    </main>
  )
}
