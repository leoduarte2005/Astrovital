import type { StationModule } from './corridors'

/**
 * Environmental sensors of the station, shown only in focus, presentation only (no click). They sit on the walls of
 * the corridors and rooms (see `wall.ts`), never on the guide lines. Mock data: names and positions are placeholders
 * until the central reports real devices.
 *
 * Each category has a place in the station (`SENSOR_PLAN`). A device goes only where its category belongs:
 * - a room sensor sits in a module of the category's `zone`;
 * - a corridor sensor sits on a corridor whose both ends are in the `zone`.
 */

export const SENSOR_KINDS = ['temperature', 'humidity', 'o2', 'co2', 'light', 'pressure'] as const
export type SensorKind = (typeof SENSOR_KINDS)[number]

/** Marker colours per kind: none is the kit's white, which the sections use. */
export const SENSOR_COLOR: Record<SensorKind, string> = {
  temperature: '#ff9f43',
  humidity: '#5b8cff',
  o2: '#ff6b9d',
  co2: '#c792ea',
  light: '#ffe066',
  pressure: '#9aa5b1',
}

const HABITABLE: readonly StationModule[] = [
  'Unity Node',
  'Destiny Space Laboratory',
  'Harmony Node',
  'Columbus Space Laboratory',
  'Kibo Space Laboratory (PSM) Pressurized Module',
  'Tranquility Node',
]
const CREW_QUARTERS: readonly StationModule[] = [
  'Harmony Node',
  'Columbus Space Laboratory',
  'Kibo Space Laboratory (PSM) Pressurized Module',
  'Destiny Space Laboratory',
]
const WINDOWS: readonly StationModule[] = ['Cupola', 'Destiny Space Laboratory']
const HATCHES: readonly StationModule[] = [
  'Pressurized Mating Adapter 1',
  'Pressurized Mating Adapter 2',
  'Pressurized Mating Adapter 3',
  'Quest Airlock',
  'Zarya',
  'Zvezda (SM)',
]

/**
 * Where each category belongs, and the direction it reads from on the walls: an angle in the cross-section, 0 is the
 * station's ceiling, a quarter turn is one side. Categories have different angles, so two of them in one room never
 * share a wall point.
 */
export const SENSOR_PLAN: Record<SensorKind, { zone: readonly StationModule[]; angleDeg: number }> = {
  temperature: { zone: HABITABLE, angleDeg: 0 },
  humidity: { zone: HABITABLE, angleDeg: 60 },
  o2: { zone: HABITABLE, angleDeg: 120 },
  co2: { zone: CREW_QUARTERS, angleDeg: 180 },
  light: { zone: WINDOWS, angleDeg: 240 },
  pressure: { zone: HATCHES, angleDeg: 300 },
}

/** Corridors of the station as module pairs (the GLB's assembly links; see `stationGraph.ts`). */
export const STATION_LINKS: readonly (readonly [StationModule, StationModule])[] = [
  ['Unity Node', 'Pressurized Mating Adapter 1'],
  ['Pressurized Mating Adapter 1', 'Zarya'],
  ['Zarya', 'Zvezda (SM)'],
  ['Zarya', 'Rassvet'],
  ['Unity Node', 'Destiny Space Laboratory'],
  ['Destiny Space Laboratory', 'Harmony Node'],
  ['Harmony Node', 'Pressurized Mating Adapter 2'],
  ['Harmony Node', 'Columbus Space Laboratory'],
  ['Harmony Node', 'Kibo Space Laboratory (PSM) Pressurized Module'],
  ['Unity Node', 'Quest Airlock'],
  ['Unity Node', 'Tranquility Node'],
  ['Tranquility Node', 'Pressurized Mating Adapter 3'],
  ['Tranquility Node', 'Cupola'],
  ['Unity Node', 'Leonardo'],
]

/** Short labels of the modules, for the sensor chips. */
export const SHORT_NAME: Partial<Record<StationModule, string>> = {
  'Unity Node': 'Unity',
  'Pressurized Mating Adapter 1': 'PMA 1',
  Zarya: 'Zarya',
  'Zvezda (SM)': 'Zvezda',
  Rassvet: 'Rassvet',
  'Destiny Space Laboratory': 'Destiny',
  'Harmony Node': 'Harmony',
  'Pressurized Mating Adapter 2': 'PMA 2',
  'Columbus Space Laboratory': 'Columbus',
  'Kibo Space Laboratory (PSM) Pressurized Module': 'Kibo',
  'Quest Airlock': 'Quest',
  'Tranquility Node': 'Tranquility',
  'Pressurized Mating Adapter 3': 'PMA 3',
  Cupola: 'Cupola',
  Leonardo: 'Leonardo',
}

export type SensorSite =
  /** On a corridor's wall, halfway along it (`t` = 0.5). */
  | { kind: 'corridor'; from: StationModule; to: StationModule; t: number }
  /** On a room's wall. */
  | { kind: 'room'; room: StationModule }

export interface StationSensor {
  id: string
  kind: SensorKind
  site: SensorSite
  /** Direction on the wall, in degrees from the station's ceiling (see `SENSOR_PLAN`). */
  angleDeg: number
}

const inZone = (zone: readonly StationModule[], module: StationModule) => zone.includes(module)

/**
 * The sensors, generated from the plan: for each category, one per module of its zone, and one per corridor between
 * two modules of its zone. Mock devices, but every one is where its category belongs.
 */
export const STATION_SENSORS: readonly StationSensor[] = SENSOR_KINDS.flatMap((kind) => {
  const { zone, angleDeg } = SENSOR_PLAN[kind]
  const rooms: StationSensor[] = zone.map((room, i) => ({
    id: `${kind}-room-${i}`,
    kind,
    site: { kind: 'room', room },
    angleDeg,
  }))
  const corridors: StationSensor[] = STATION_LINKS.filter(
    ([from, to]) => inZone(zone, from) && inZone(zone, to),
  ).map(([from, to], i) => ({
    id: `${kind}-corridor-${i}`,
    kind,
    site: { kind: 'corridor', from, to, t: 0.5 },
    angleDeg,
  }))
  return [...rooms, ...corridors]
})

/** Where a sensor is, for its chip: the module (or the corridor between two modules). */
export function sensorLocation(sensor: StationSensor): string {
  const short = (room: StationModule) => SHORT_NAME[room] ?? room
  return sensor.site.kind === 'room' ? short(sensor.site.room) : `${short(sensor.site.from)} – ${short(sensor.site.to)}`
}
