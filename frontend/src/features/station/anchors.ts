import type { StationModule } from './corridors'

/**
 * Sections of the station: the junctions where the guide lines meet (modules with two or more corridors, from the
 * GLB topology: Unity, PMA 1, Zarya, Destiny, Harmony, Tranquility). Each is a clickable marker that focuses the
 * section. `key` is the module's name in `corridors.ts`; `name` is the label, a proper name (data, not translated).
 */
export const STATION_SECTIONS: readonly { key: StationModule; id: string; name: string }[] = [
  { key: 'Unity Node', id: 'unity', name: 'Unity (Node 1)' },
  { key: 'Pressurized Mating Adapter 1', id: 'pma1', name: 'PMA 1' },
  { key: 'Zarya', id: 'zarya', name: 'Zarya (FGB)' },
  { key: 'Destiny Space Laboratory', id: 'destiny', name: 'Destiny (Lab)' },
  { key: 'Harmony Node', id: 'harmony', name: 'Harmony (Node 2)' },
  { key: 'Tranquility Node', id: 'tranquility', name: 'Tranquility (Node 3)' },
]

export type SectionId = (typeof STATION_SECTIONS)[number]['id']
