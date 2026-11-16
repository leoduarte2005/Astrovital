import { useEffect, useRef } from 'react'
import { getDataSource } from '@/lib/data'
import { useI18n } from '@/lib/i18n'
import type { CrewMember } from '@/lib/model/crew'
import { CardItem } from '@/ui/CardItem'
import { Readout } from '@/ui/Readout'
import { Stack } from '@/ui/Stack'

interface CrewStackProps {
  crew: CrewMember[]
  onSelect: (member: CrewMember) => void
}

/** Crew selection as a stack of cards, one per member. Each card shows that member's heart rate. */
export function CrewStack({ crew, onSelect }: CrewStackProps) {
  const { t } = useI18n()
  return (
    <Stack label={t('crew.stack.label')} width="15rem">
      {crew.map((member) => (
        <CrewStackCard key={member.crewId} member={member} onSelect={onSelect} />
      ))}
    </Stack>
  )
}

interface CrewStackCardProps {
  member: CrewMember
  onSelect: (member: CrewMember) => void
}

/** Without a reading for this long, the card shows the placeholder instead of an old value. */
const STALE_MS = 5000
/** How often the card checks whether its last reading has gone stale. */
const STALE_CHECK_MS = 1000
/** The placeholder shown while there is no current reading (the same one as `Readout` before a value). */
const PLACEHOLDER = '--'

function CrewStackCard({ member, onSelect }: CrewStackCardProps) {
  const { t } = useI18n()
  const valueRef = useRef<HTMLSpanElement>(null)

  // The heart-rate link of this member lives only while the card is on screen and the tab is visible: it opens
  // with the first reading wanted, closes when the page is left or hidden, and reopens when it is shown again.
  // Readings are written straight to the DOM, not through React state (see performance.md).
  useEffect(() => {
    const source = getDataSource()
    let unwatch: (() => void) | null = null
    let lastAt = 0

    const show = (bpm: number) => {
      lastAt = Date.now()
      if (valueRef.current) valueRef.current.textContent = String(Math.round(bpm))
    }
    const start = () => {
      if (!unwatch) unwatch = source.watchHeartRate(member.crewId, show)
    }
    const stop = () => {
      unwatch?.()
      unwatch = null
      lastAt = 0
      if (valueRef.current) valueRef.current.textContent = PLACEHOLDER
    }
    const onVisibility = () => (document.visibilityState === 'visible' ? start() : stop())

    onVisibility()
    document.addEventListener('visibilitychange', onVisibility)

    // A reading older than STALE_MS is not shown: the card falls back to the placeholder, with no alarm.
    const staleCheck = window.setInterval(() => {
      if (!valueRef.current || lastAt === 0 || Date.now() - lastAt <= STALE_MS) return
      lastAt = 0
      valueRef.current.textContent = PLACEHOLDER
    }, STALE_CHECK_MS)

    return () => {
      window.clearInterval(staleCheck)
      document.removeEventListener('visibilitychange', onVisibility)
      stop()
    }
  }, [member.crewId])

  return (
    <CardItem
      icon="user"
      title={member.fullName}
      label={t('crew.card.select', { name: member.fullName })}
      onClick={() => onSelect(member)}
      trailing={<Readout valueRef={valueRef} unit={t('crew.stack.bpm')} title={t('vital.heartRate')} />}
    />
  )
}
