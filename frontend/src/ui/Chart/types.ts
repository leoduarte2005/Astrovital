/**
 * A chart's data source. The chart reads it on animation frames and never copies it into React state
 * (rules/performance.md). Implemented by the feature that owns the data.
 */
export interface ChartFeed<S> {
  read(): S
  /** Called when new data arrives. Returns the unsubscribe function. */
  subscribe(listener: () => void): () => void
}

/** Time in seconds (uPlot time scale). `null` in `y` is a gap: no value, not zero. */
export interface LineSnapshot {
  x: number[]
  y: (number | null)[]
}

/** Minimised cards show only the last readings; the expanded view shows the whole window. */
export const CARD_READINGS = 8

/** The telemetry arrives at 2 Hz: the card's last readings span this many seconds. */
export const CARD_WINDOW_SECONDS = CARD_READINGS / 2

/** The expanded view keeps this many readings; older ones are discarded. */
export const EXPANDED_READINGS = 20
/** The expanded window, in seconds (readings at 2 Hz). */
export const EXPANDED_WINDOW_SECONDS = EXPANDED_READINGS / 2
