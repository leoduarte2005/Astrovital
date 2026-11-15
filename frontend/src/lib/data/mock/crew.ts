import type { CrewMember } from '@/lib/model/crew'

/**
 * The central's test crew (`GET /api/crew`): same ids, names, roles, mission days and calibration flags.
 * Nationality, skin, accent and sharing are not sent by the central: they are local example values.
 */
export const MOCK_CREW: CrewMember[] = [
  {
    crewId: 'crew_001',
    fullName: 'Cmdr. Silva',
    role: 'COMMANDER',
    accent: '#f2b35e',
    skinTone: '#a56f45',
    shares: ['activity', 'garden'],
    nationality: 'BR',
    missionDay: 42,
    calibrationRequired: false,
  },
  {
    crewId: 'crew_002',
    fullName: 'Dr. Costa',
    role: 'FLIGHT_SURGEON',
    accent: '#7aa7f0',
    skinTone: '#ecc9a6',
    shares: ['activity', 'garden'],
    nationality: 'JP',
    missionDay: 42,
    calibrationRequired: false,
  },
  {
    crewId: 'crew_003',
    fullName: 'Eng. Sato',
    role: 'FLIGHT_ENGINEER',
    accent: '#7fd6c8',
    skinTone: '#d8aa80',
    shares: [],
    nationality: 'US',
    missionDay: 42,
    calibrationRequired: true,
  },
]
