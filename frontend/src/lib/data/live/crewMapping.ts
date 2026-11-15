import type { CrewMember, CrewRole, ShareScope, Nationality } from '@/lib/model/crew'
import type { CrewSummary } from '@/lib/model/live'
import { MOCK_CREW } from '../mock/crew'

/** Fields the central does not send: personal or device-side, kept in the app (rules/crew.md). */
type LocalProfile = Pick<CrewMember, 'accent' | 'skinTone' | 'shares' | 'nationality'>

const pickLocal = (member: CrewMember): LocalProfile => ({
  accent: member.accent,
  skinTone: member.skinTone,
  shares: member.shares,
  nationality: member.nationality,
})

/** Neutral values for crew the device does not know yet. */
const DEFAULT_LOCAL: { accent: string; skinTone: string; shares: ShareScope[]; nationality: Nationality } = {
  accent: '#9dbaf7',
  skinTone: '#c8a27e',
  shares: [],
  nationality: 'BR',
}

/** Test crew of the handoff (crew_001..crew_003) take the mock's local profiles in order. Temporary. */
const LOCAL_BY_CREW_ID: Record<string, LocalProfile> = Object.fromEntries(
  MOCK_CREW.slice(0, 3).map((member, index) => [`crew_00${index + 1}`, pickLocal(member)]),
)

const ROLE_BY_TITLE: Record<string, CrewRole> = {
  commander: 'COMMANDER',
  'flight engineer': 'FLIGHT_ENGINEER',
  'flight surgeon': 'FLIGHT_SURGEON',
  'mission specialist': 'MISSION_SPECIALIST',
  cmo: 'CMO',
  'chief medical officer': 'CMO',
}

function roleFromTitle(title: string | undefined): CrewRole {
  const role: CrewRole | undefined = ROLE_BY_TITLE[(title ?? '').trim().toLowerCase()]
  if (!role) console.warn('live: unknown crew role, shown as mission specialist')
  return role ?? 'MISSION_SPECIALIST'
}

/** Maps the central's summary to the app's member. */
export function toCrewMember(summary: CrewSummary): CrewMember {
  return {
    crewId: summary.crew_id,
    fullName: summary.name,
    role: roleFromTitle(summary.role),
    missionDay: summary.mission_day ?? null,
    calibrationRequired: summary.calibration_required,
    ...(LOCAL_BY_CREW_ID[summary.crew_id] ?? DEFAULT_LOCAL),
  }
}
