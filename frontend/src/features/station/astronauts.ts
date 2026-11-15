import type { StationModule } from './corridors'
import type { WalkRoute } from './walkers'

type Stop = { room: StationModule; meet?: boolean }
const route = (id: string, stops: readonly Stop[]): WalkRoute => ({ id, stops })

const KIBO = 'Kibo Space Laboratory (PSM) Pressurized Module'

/**
 * Three crew walkers. Each route loops through the station's rooms (the modules of `corridors.ts`), always along the
 * corridors of the graph. `meet: true` marks the points where they gather and talk: Unity and Harmony, the two hubs
 * where the corridors branch.
 */
export const ASTRONAUT_ROUTES: readonly WalkRoute[] = [
  route('a', [
    { room: 'Zarya' },
    { room: 'Unity Node', meet: true },
    { room: 'Destiny Space Laboratory' },
    { room: 'Harmony Node', meet: true },
    { room: 'Columbus Space Laboratory' },
    { room: 'Harmony Node', meet: true },
    { room: 'Pressurized Mating Adapter 2' },
    { room: 'Harmony Node', meet: true },
    { room: 'Destiny Space Laboratory' },
    { room: 'Unity Node', meet: true },
  ]),
  route('b', [
    { room: 'Zvezda (SM)' },
    { room: 'Zarya' },
    { room: 'Rassvet' },
    { room: 'Zarya' },
    { room: 'Unity Node', meet: true },
    { room: 'Quest Airlock' },
    { room: 'Unity Node', meet: true },
    { room: 'Destiny Space Laboratory' },
    { room: 'Harmony Node', meet: true },
    { room: KIBO },
    { room: 'Harmony Node', meet: true },
    { room: 'Destiny Space Laboratory' },
  ]),
  route('c', [
    { room: 'Cupola' },
    { room: 'Tranquility Node' },
    { room: 'Pressurized Mating Adapter 3' },
    { room: 'Tranquility Node' },
    { room: 'Unity Node', meet: true },
    { room: 'Leonardo' },
    { room: 'Unity Node', meet: true },
    { room: 'Destiny Space Laboratory' },
    { room: 'Harmony Node', meet: true },
    { room: KIBO },
    { room: 'Harmony Node', meet: true },
    { room: 'Destiny Space Laboratory' },
    { room: 'Unity Node', meet: true },
    { room: 'Tranquility Node' },
  ]),
]
