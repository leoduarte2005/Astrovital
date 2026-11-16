/**
 * Lead lines of the digital twin: an element marked with `leadTarget(anchorId)` gets a line from its edge to
 * that point of the body (drawn by `features/twin3d`). A scrolling panel marked with `leadScope` hides the
 * lines of rows scrolled out of it. Plain DOM attributes, so features stay independent of each other.
 */
export const LEAD_ATTR = 'data-lead'
export const LEAD_SCOPE_ATTR = 'data-lead-scope'

export const leadTarget = (anchorId: string): Record<string, string> => ({ [LEAD_ATTR]: anchorId })
export const leadScope: Record<string, string> = { [LEAD_SCOPE_ATTR]: '' }
