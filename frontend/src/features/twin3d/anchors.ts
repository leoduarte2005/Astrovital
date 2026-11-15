import type { MessageKey } from '@/lib/i18n/types'

/** Anatomy layers the twin can render (GLB files under /models/anatomy/). */
export const TWIN_LAYER_IDS = ['skin', 'bones', 'organs', 'heart', 'brain', 'lungs'] as const
export type TwinLayerId = (typeof TWIN_LAYER_IDS)[number]

/** Layers shown when no marker is selected. */
export const DEFAULT_TWIN_LAYERS: readonly TwinLayerId[] = ['skin', 'bones']

export type TwinAnchorId = 'heart' | 'brain' | 'lungs'

export interface TwinAnchor {
  id: TwinAnchorId
  labelKey: MessageKey
  /** Metres from the middle of the GLB (canvas origin), model units, Y up. */
  offset: { x: number; y: number; z: number }
  /** Layers rendered when this marker is selected. */
  layers: readonly TwinLayerId[]
}

/**
 * Points on the body that get an HTML marker. They turn with the model and are projected every frame.
 * X < 0 is the viewer's left when the front faces the camera; Z > 0 is the chest front (+Z, to verify).
 */
export const TWIN_ANCHORS: readonly TwinAnchor[] = [
  { id: 'heart', labelKey: 'twin.marker.heart', offset: { x: 0.02, y: 0.45, z: 0.02 }, layers: ['heart'] },
  // Brain: at the brain's centre. Lungs: on the viewer's left lobe, so it does not sit on the heart marker.
  { id: 'brain', labelKey: 'twin.marker.brain', offset: { x: 0, y: 0.78, z: -0.02 }, layers: ['brain'] },
  { id: 'lungs', labelKey: 'twin.marker.lungs', offset: { x: -0.08, y: 0.4, z: 0 }, layers: ['lungs'] },
]
