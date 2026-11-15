import { useLayoutEffect, useState } from 'react'
import { TwinCanvas, type TwinAnchorId } from '@/features/twin3d'
import { CrewInfoCard, ShelterOverlay } from '@/features/crew'
import { hasOrganCharts, MetricsPanel, OrganCharts, vitalFeed } from '@/features/vitals'
import { statureM } from '@/lib/model/stature'
import { getDataSource } from '@/lib/data'
import { crewStateStore, useCrewState } from '@/lib/data/crewState'
import { useSession } from '@/lib/data/session'
import { useI18n } from '@/lib/i18n'
import { Button } from '@/ui/Button'
import styles from './HomePage.module.css'

export default function HomePage() {
  const { t } = useI18n()
  const crew = useSession((state) => state.activeCrew)
  const crewId = crew?.crewId ?? null
  const confirmedCrewId = useCrewState((state) => state.crewId)
  const missionMode = useCrewState((state) => state.missionMode)
  const switchFailed = useCrewState((state) => state.switchFailed)
  // Selected twin marker: its chart group (features/vitals/organGroups.ts) shows on the right.
  const [selected, setSelected] = useState<TwinAnchorId | null>(null)

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
            <TwinCanvas skinTone={crew.skinTone} heightM={statureM(crew.nationality)} onSelect={setSelected} />
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
