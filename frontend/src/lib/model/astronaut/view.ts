/**
 * How the astronaut is framed on `#/astronaut`. The twin's intro starts from this same view and zooms to its own framing,
 * so the two screens connect. Shared here because `features/astronaut` and `features/twin3d` cannot import each other.
 */

/** Height of the model box on that page, as a fraction of the screen (`pages/astronaut` CSS: 50%). */
export const ASTRONAUT_BOX_FRACTION = 0.5
/** The model fills its box's height divided by this margin. */
export const ASTRONAUT_FIT_MARGIN = 1.1
/** Camera height above the floor, as a fraction of the framed distance: the grid reads as a floor. */
export const ASTRONAUT_CAMERA_LIFT = 0.22
/** Fraction of the screen height the figure occupies on that page. */
export const ASTRONAUT_SCREEN_FRACTION = ASTRONAUT_BOX_FRACTION / ASTRONAUT_FIT_MARGIN

/**
 * The studio light of the astronaut and the twin, the same in both scenes: the suit must look the same before and
 * after the cut. Taken from the twin (see rules/twin3d.md). Scene values, not UI tokens.
 */
export const STUDIO_LIGHT = {
  paper: 0xf9f8f2,
  ground: 0x353a3e,
  hemisphere: 0.35,
  key: 1.1,
  keyFrom: [2, 3, 4] as const,
  rim: 0.7,
  rimFrom: [-3, 2, -3] as const,
  exposure: 0.8,
}
