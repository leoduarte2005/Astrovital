import type { MessageKey } from '@/lib/i18n/types'

/** Anatomy layers the twin can render (GLB files under /models/). Bones are out of the renderer for now. */
export const TWIN_LAYER_IDS = [
  'skin',
  'eyes',
  'vascular',
  'organs',
  'heart',
  'brain',
  'lungs',
  'kidneys',
  'liver',
  'gut',
  'jugular',
  'spine',
] as const
export type TwinLayerId = (typeof TWIN_LAYER_IDS)[number]

/** Layers shown when no marker is selected: skin with the eyes. */
export const DEFAULT_TWIN_LAYERS: readonly TwinLayerId[] = ['skin', 'eyes']

export type TwinAnchorId = 'heart' | 'brain' | 'lungs' | 'kidneys' | 'liver' | 'gut' | 'jugular' | 'spine' | 'vascular'

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
 * Heart and lungs were tuned by eye. The others start at the organ's bounding-box centre (manifest,
 * minus the body centre) and are adjusted where markers would overlap.
 */
export const TWIN_ANCHORS: readonly TwinAnchor[] = [
  { id: 'heart', labelKey: 'twin.marker.heart', offset: { x: 0.02, y: 0.45, z: 0.02 }, layers: ['heart'] },
  { id: 'brain', labelKey: 'twin.marker.brain', offset: { x: 0, y: 0.78, z: -0.02 }, layers: ['brain'] },
  { id: 'lungs', labelKey: 'twin.marker.lungs', offset: { x: -0.08, y: 0.4, z: 0 }, layers: ['lungs'] },
  { id: 'jugular', labelKey: 'twin.marker.jugular', offset: { x: 0, y: 0.637, z: 0.003 }, layers: ['jugular'] },
  { id: 'liver', labelKey: 'twin.marker.liver', offset: { x: -0.011, y: 0.314, z: 0.024 }, layers: ['liver'] },
  { id: 'gut', labelKey: 'twin.marker.gut', offset: { x: 0.001, y: 0.162, z: 0.01 }, layers: ['gut'] },
  { id: 'kidneys', labelKey: 'twin.marker.kidneys', offset: { x: 0.07, y: 0.25, z: -0.025 }, layers: ['kidneys'] },
  { id: 'spine', labelKey: 'twin.marker.spine', offset: { x: 0, y: 0.5, z: -0.04 }, layers: ['spine'] },
  // Vascular: the model's right hand (viewer's left, X < 0), at the lower end of the arm. Estimated from the
  // arm bounds in the manifest (x ±0,33; y 0,71…1,42); needs a visual check.
  { id: 'vascular', labelKey: 'twin.marker.vascular', offset: { x: -0.26, y: -0.068, z: 0.05 }, layers: ['vascular'] },
]
