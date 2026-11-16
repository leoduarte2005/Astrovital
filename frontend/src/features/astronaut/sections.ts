export const ASTRONAUT_PATH = '/astronaut'
export const ASTRONAUT_SECTIONS = ['training', 'medical', 'personal'] as const
export type AstronautSection = (typeof ASTRONAUT_SECTIONS)[number]

/** Child route of a section: `#/astronaut/<section>`. */
export function sectionPath(section: AstronautSection): string {
  return `${ASTRONAUT_PATH}/${section}`
}

/** The section a route belongs to, or null when none is chosen (the overview, `#/astronaut`). */
export function sectionOfPath(path: string): AstronautSection | null {
  return ASTRONAUT_SECTIONS.find((section) => path === sectionPath(section)) ?? null
}
