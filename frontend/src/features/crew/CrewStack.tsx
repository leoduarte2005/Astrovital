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

function CrewStackCard({ member, onSelect }: CrewStackCardProps) {
  const { t } = useI18n()
  const valueRef = useRef<HTMLSpanElement>(null)

  // Heart rate at telemetry rate: written straight to the DOM, not through React state (see performance.md).
  useEffect(() => {
    return getDataSource().watchHeartRate(member.crewId, (bpm) => {
      if (valueRef.current) valueRef.current.textContent = String(Math.round(bpm))
    })
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
