import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { createPortal } from 'react-dom'
import { getDataSource } from '@/lib/data'
import type { CrewId, CrewLore } from '@/lib/data/mock/crewLore'
import { useSession } from '@/lib/data/session'
import { useI18n } from '@/lib/i18n'
import { CORNER_SLOT_ID } from '@/lib/utils/cornerSlot'
import type { CrewMember } from '@/lib/model/crew'
import { statureM } from '@/lib/model/stature'
import { Marker } from '@/ui/Marker'
import { ROUTINES, dateOf } from './behaviour'
import { mountHangar, type HangarHandle, type SimClock, type TrainingCrew } from './renderer'
import { TrainingControls } from './TrainingControls'
import { TrainingLog } from './TrainingLog'
import styles from './TrainingScene.module.css'

const CREW_IDS: ReadonlySet<string> = new Set(['crew_001', 'crew_002', 'crew_003'])
const isCrewId = (id: string): id is CrewId => CREW_IDS.has(id)

interface SceneData {
  lore: CrewLore[]
  crew: TrainingCrew[]
  names: { crewId: CrewId; name: string }[]
}

/** "12 Feb, 14:30" in the active locale, for a simulated day and minute. */
function formatClock(clock: SimClock, locale: string): string {
  const [year, month, day] = dateOf(clock.monthIndex, clock.dayIndex).date.split('-').map(Number)
  const when = Date.UTC(year ?? 2024, (month ?? 1) - 1, day ?? 1, Math.floor(clock.minute / 60), clock.minute % 60)
  return new Intl.DateTimeFormat(locale, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'UTC' }).format(when)
}

interface TrainingSceneProps {
  /** Accessible name of the scene (translated). */
  label: string
}

/**
 * The training hangar full screen, with the three crew members living the chosen month of the 24 before the mission
 * in accelerated time, and the timeline controls. The camera follows the active crew member, and the top left shows
 * what happened to him in the month. Lore and crew come from the DataSource. Only positions, names and the month's
 * story of the followed member are shown: no health figures, notes or reasons of absence (rules/training.md).
 */
export function TrainingScene({ label }: TrainingSceneProps) {
  const { t, locale } = useI18n()
  const activeId = useSession((state) => state.activeCrew?.crewId ?? null)
  const followId = activeId && isCrewId(activeId) ? activeId : null
  const hostRef = useRef<HTMLDivElement>(null)
  const markerRefs = useRef<Partial<Record<CrewId, HTMLSpanElement | null>>>({})
  const clockRef = useRef<HTMLSpanElement>(null)
  const handleRef = useRef<HangarHandle | null>(null)
  const localeRef = useRef(locale)
  const [data, setData] = useState<SceneData | null>(null)
  const [failed, setFailed] = useState(false)
  const [monthIndex, setMonthIndex] = useState(0)
  // The top left column's slot (App): the month text goes there, under the crew card. The column is mounted before this
  // page loads, so the element is there when the scene renders.
  const corner = useSyncExternalStore(
    () => () => {},
    () => document.getElementById(CORNER_SLOT_ID),
    () => null,
  )
  // Reduced motion: the days do not run by themselves; play starts them.
  const [playing, setPlaying] = useState(() => !window.matchMedia('(prefers-reduced-motion: reduce)').matches)
  // Initial values for the mount; later changes go through the handle (no remount).
  const startRef = useRef({ monthIndex, playing, follow: followId })

  useEffect(() => {
    localeRef.current = locale
  })

  useEffect(() => {
    let alive = true
    const source = getDataSource()
    Promise.all([source.listCrewLore(), source.listCrew()])
      .then(([lore, members]) => {
        if (!alive) return
        const crew: TrainingCrew[] = []
        const names: SceneData['names'] = []
        for (const member of members as CrewMember[]) {
          if (!isCrewId(member.crewId)) continue
          crew.push({
            crewId: member.crewId,
            skinTone: member.skinTone,
            shirt: member.accent,
            heightM: statureM(member.nationality),
            walkSpeed: ROUTINES[member.crewId].walkSpeed,
          })
          names.push({ crewId: member.crewId, name: member.fullName })
        }
        setData({ lore, crew, names })
      })
      .catch((error: unknown) => {
        console.warn('training data failed', error)
        if (alive) setFailed(true)
      })
    return () => {
      alive = false
    }
  }, [])

  useEffect(() => {
    const host = hostRef.current
    if (!host || !data) return
    let alive = true
    let unsubscribe: (() => void) | null = null
    const markers: Partial<Record<CrewId, HTMLElement>> = {}
    for (const { crewId } of data.names) {
      const element = markerRefs.current[crewId]
      if (element) markers[crewId] = element
    }
    mountHangar(host, { lore: data.lore, crew: data.crew, markers, ...startRef.current })
      .then((handle) => {
        // Unmounted while the scene was loading: release it at once.
        if (!alive) {
          handle.dispose()
          return
        }
        handleRef.current = handle
        unsubscribe = handle.onClock((clock) => {
          if (clockRef.current) clockRef.current.textContent = formatClock(clock, localeRef.current)
        })
      })
      .catch((error: unknown) => {
        console.warn('training hangar failed', error)
        if (alive) setFailed(true)
      })
    return () => {
      alive = false
      unsubscribe?.()
      handleRef.current?.dispose()
      handleRef.current = null
    }
  }, [data])

  useEffect(() => {
    startRef.current.monthIndex = monthIndex
    handleRef.current?.setMonth(monthIndex)
  }, [monthIndex])

  useEffect(() => {
    startRef.current.playing = playing
    handleRef.current?.setPlaying(playing)
  }, [playing])

  // The camera follows the active crew member; changing the active member re-aims it at once.
  useEffect(() => {
    startRef.current.follow = followId
    handleRef.current?.setFollow(followId)
  }, [followId])

  return (
    <>
      <div ref={hostRef} className={styles.root} role="img" aria-label={label}>
        {data?.names.map(({ crewId, name }) => (
          <Marker
            key={crewId}
            label={name}
            clickable={false}
            showLabel
            ref={(element) => {
              markerRefs.current[crewId] = element
            }}
          />
        ))}
        {!data && !failed && <p className={styles.status}>{t('common.loading')}</p>}
        {failed && <p className={styles.status}>{t('training.hangar.error')}</p>}
      </div>
      {corner && createPortal(<TrainingLog monthIndex={monthIndex} crewId={followId} />, corner)}
      <TrainingControls
        monthIndex={monthIndex}
        playing={playing}
        onMonthChange={(index) => setMonthIndex(Math.min(23, Math.max(0, index)))}
        onTogglePlay={() => setPlaying((value) => !value)}
        clockRef={clockRef}
      />
    </>
  )
}
