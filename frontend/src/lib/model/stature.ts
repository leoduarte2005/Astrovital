import type { Nationality } from './crew'

/**
 * Mean adult male height per country, in cm: the latest birth-decade value in the source table
 * (decade differs by country: BR and US 1990; JP, SN and PL 1980).
 * Source: Our World in Data, "Average height of men for selected countries" (Baten and Blum, 2014), CC BY 4.0.
 */
export const MALE_HEIGHT_CM: Record<Nationality, number> = {
  BR: 173,
  JP: 171.66,
  US: 175.2,
  SN: 174.254,
  PL: 177.4,
}

/** Stature in metres for a nationality. */
export function statureM(nationality: Nationality): number {
  return MALE_HEIGHT_CM[nationality] / 100
}
