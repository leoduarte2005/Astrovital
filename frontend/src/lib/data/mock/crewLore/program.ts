import type { CastMember, ProgramMonth } from './types'

/** Fictional launch. Mission day 1 = 2026-10-05; day 42 = 2026-11-15. */
export const LAUNCH_DATE = '2026-10-05'

export const CAST: CastMember[] = [
  { id: 'okafor', name: 'Cmdr. Adaeze Okafor', role: 'Backup commander', agency: 'NASA', hint: 'Veteran who jokes about her own perfectionism; trains in a pair with Silva.' },
  { id: 'lindqvist', name: 'Dr. Erik Lindqvist', role: 'Backup flight surgeon', agency: 'ESA', hint: 'Says little and cooks a lot; Costa\'s friendly rival at diagnosis chess.' },
  { id: 'ramirez', name: 'Eng. Paula Ramírez', role: 'Backup flight engineer', agency: 'NASA', hint: 'Competitive at the gym; first friction with Silva in survival training.' },
  { id: 'haddad', name: 'Capt. Samir Haddad', role: 'Astronaut from another crew, CAPCOM in the simulations', agency: 'MBRSC', hint: 'Calm voice in the communication-delay sims; storyteller by the campfire.' },
  { id: 'kowalski', name: 'Maj. Tom Kowalski', role: 'Veteran ISS mentor', agency: 'NASA', hint: 'Amateur radio operator; takes Silva to the radio club.' },
  { id: 'iyer', name: 'Dr. Priya Iyer', role: 'Behavioural health psychologist (BHP)', agency: 'NASA', hint: 'Leads the month 18 mediation and the calibration interviews.' },
  { id: 'walsh', name: 'Bryn Walsh', role: 'NBL dive lead', agency: 'NASA', hint: 'Demanding; praises rarely and precisely.' },
  { id: 'beaumont', name: 'Claire Beaumont', role: 'Strength and rehabilitation trainer (ASCR)', agency: 'NASA', hint: 'Adapts programmes to old injuries; does not accept "all good".' },
  { id: 'nguyen', name: 'Linh Nguyen', role: 'Simulation coordinator', agency: 'NASA', hint: 'Designs the sim failures; likes to catch the crew by surprise.' },
]

export const PROGRAM: ProgramMonth[] = [
  { month: 1, period: '2024-10', phase: 'Integration', location: 'Houston (JSC)', summary: 'Crew announcement, move to Houston, first classes and the first lunch together.' },
  { month: 2, period: '2024-11', phase: 'Systems', location: 'Houston (JSC)', summary: 'Spacecraft and life-support (ECLSS) fundamentals, with weekly exams.' },
  { month: 3, period: '2024-12', phase: 'NBL', location: 'Houston (NBL pool)', summary: 'First EVA certification in the Neutral Buoyancy Laboratory.' },
  { month: 4, period: '2025-01', phase: 'Physical and medical baseline', location: 'Houston (ASCR and clinic)', summary: 'Full baseline tests and individual strength programmes.' },
  { month: 5, period: '2025-02', phase: 'Centrifuge', location: 'Human centrifuge', summary: 'Launch and re-entry profiles up to 6 G, with anti-G technique.' },
  { month: 6, period: '2025-03', phase: 'Survival', location: 'Gulf of Mexico and cold-weather training', summary: 'Water landing, capsule egress and shelter in cold weather.' },
  { month: 7, period: '2025-04', phase: 'Robotics', location: 'Houston (robotics bay)', summary: 'Robotic arm operation and cargo capture.' },
  { month: 8, period: '2025-05', phase: 'Parabolic flight', location: 'Ellington Field', summary: 'Two days of parabolas: real microgravity in 20 s blocks.' },
  { month: 9, period: '2025-06', phase: 'Field geology', location: 'Arizona', summary: 'Sampling, outcrop description and nights camping.' },
  { month: 10, period: '2025-07', phase: 'Isolation', location: 'Habitat analogue (30 days)', summary: 'Thirty days sealed in, with communication delay and restricted sleep for part of the time.' },
  { month: 11, period: '2025-08', phase: 'Recovery', location: 'Houston', summary: 'Decompression, post-analogue reviews and short breaks.' },
  { month: 12, period: '2025-09', phase: 'Mid-programme', location: 'Houston', summary: 'Mid-term review and medical cross-training with Costa.' },
  { month: 13, period: '2025-10', phase: 'Advanced EVA', location: 'Houston (NBL pool)', summary: 'Six-hour pool runs; load on the shoulders and hands.' },
  { month: 14, period: '2025-11', phase: 'Life-support failures', location: 'Houston (test chamber)', summary: 'Simulated leak, high CO₂ and water loss in a chamber.' },
  { month: 15, period: '2025-12', phase: 'Break and communication delay', location: 'Home and Houston', summary: 'Year-end break and, on return, sims with up to 20 min of delay.' },
  { month: 16, period: '2026-01', phase: 'Radiation', location: 'Houston', summary: 'Solar particle events and setting up the storm shelter.' },
  { month: 17, period: '2026-02', phase: 'Integrated simulation', location: 'Houston (simulator)', summary: 'Seventy-two continuous hours of mission, with cascading failures.' },
  { month: 18, period: '2026-03', phase: 'Cohesion', location: 'Houston', summary: 'Friction after a wrong decision in the sim and a mediation session with the BHP.' },
  { month: 19, period: '2026-04', phase: 'Medical emergencies', location: 'Houston (medbay)', summary: 'Emergency rehearsals with each crew member as patient and as rescuer.' },
  { month: 20, period: '2026-05', phase: 'AI calibration', location: 'Houston', summary: 'Profile and preference interviews and the baseline for the individual model.' },
  { month: 21, period: '2026-06', phase: 'Family and media', location: 'Houston', summary: 'Family day in the hangar and a schedule of interviews.' },
  { month: 22, period: '2026-07', phase: 'Final simulations', location: 'Houston (simulator)', summary: 'Complete end-to-end missions, with no advance warning of failures.' },
  { month: 23, period: '2026-08', phase: 'Readiness', location: 'Houston', summary: 'Final medical and technical reviews, readiness sign-off.' },
  { month: 24, period: '2026-09', phase: 'Quarantine and launch', location: 'Quarantine (HSP) and launch site', summary: 'Health stabilisation programme and launch on 5 October.' },
]
