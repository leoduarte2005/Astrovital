import { LEAD_ATTR, LEAD_SCOPE_ATTR } from '@/lib/utils/lead'
import type { AnchorPoints } from './renderer'
import type { TwinAnchorId } from './anchors'

/** Longest horizontal run before the line turns toward the anchor, in CSS pixels. */
const ELBOW_PX = 56
/** Half side of the square drawn where a line leaves its panel. */
const DOT_PX = 2.5

/**
 * Draws one HUD line per lead target (`lib/utils/lead.ts`) to its anchor. A line is skipped while its row is
 * scrolled out of its scope panel. Each line goes horizontal from the target's edge that faces the twin,
 * then straight to the anchor. All lines share one path and all start squares another, so a frame is two
 * attribute writes. Called by the renderer's projection, outside React.
 */
export function drawLeadLines(lines: SVGPathElement, dots: SVGPathElement, points: AnchorPoints): void {
  let lineData = ''
  let dotData = ''
  for (const target of document.querySelectorAll<HTMLElement>(`[${LEAD_ATTR}]`)) {
    const anchor = points[target.getAttribute(LEAD_ATTR) as TwinAnchorId]
    if (!anchor) continue
    const box = target.getBoundingClientRect()
    if (box.width === 0 || box.height === 0) continue
    const y = box.top + box.height / 2
    const scope = target.closest(`[${LEAD_SCOPE_ATTR}]`)?.getBoundingClientRect()
    if (scope && (y < scope.top || y > scope.bottom)) continue
    const fromLeft = box.left + box.width / 2 < anchor.x
    const x = fromLeft ? box.right : box.left
    const run = Math.min(ELBOW_PX, Math.abs(anchor.x - x) / 2)
    const elbow = fromLeft ? anchor.x - run : anchor.x + run
    lineData += `M${x.toFixed(1)} ${y.toFixed(1)}H${elbow.toFixed(1)}L${anchor.x.toFixed(1)} ${anchor.y.toFixed(1)}`
    dotData += `M${(x - DOT_PX).toFixed(1)} ${(y - DOT_PX).toFixed(1)}h${DOT_PX * 2}v${DOT_PX * 2}h${-DOT_PX * 2}z`
  }
  lines.setAttribute('d', lineData)
  dots.setAttribute('d', dotData)
}
