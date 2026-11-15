/**
 * The pressurised modules of the station: its rooms. Each is matched by GLB node name (spaces, underscores and case
 * ignored). The corridors are not listed by hand: in the GLB every module hangs from the module it was assembled onto,
 * which is the real topology of the station (Unity joins PMA 1, Destiny, Quest, Tranquility and Leonardo; Destiny joins
 * Harmony; Harmony joins Columbus, Kibo and PMA 2; PMA 1 joins Zarya, which joins Zvezda). See `stationGraph.ts`.
 */
export const STATION_MODULES = [
  'Unity Node',
  'Pressurized Mating Adapter 1',
  'Zarya',
  'Zvezda (SM)',
  'Rassvet',
  'Destiny Space Laboratory',
  'Harmony Node',
  'Pressurized Mating Adapter 2',
  'Columbus Space Laboratory',
  'Kibo Space Laboratory (PSM) Pressurized Module',
  'Quest Airlock',
  'Tranquility Node',
  'Pressurized Mating Adapter 3',
  'Cupola',
  'Leonardo',
] as const

export type StationModule = (typeof STATION_MODULES)[number]
