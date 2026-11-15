import { pixelColor } from './pixels'

/**
 * 8-bit palette for the games' action screen (the canvas) only. Requested by the user: colourful and outside
 * the kit, limited to inside the canvas. HUD, buttons and panels around the canvas keep the kit tokens.
 */
export const PALETTE = {
  space: pixelColor('#05060f'),
  stars: [pixelColor('#ffffff'), pixelColor('#c9d6ff'), pixelColor('#7ad7ff')],
  // Asteroids
  ship: pixelColor('#3cf0ff'),
  shipCore: pixelColor('#ffffff'),
  flame: pixelColor('#ff9f1c'),
  flameCore: pixelColor('#ffe066'),
  shot: pixelColor('#ff4d6d'),
  rock: { 3: pixelColor('#9c5a2c'), 2: pixelColor('#c97a3d'), 1: pixelColor('#e8a25c') },
  rockShade: pixelColor('#5e3418'),
  // Landing
  earthBlue: pixelColor('#2d6cc0'),
  earthGreen: pixelColor('#3f9d4e'),
  earthCloud: pixelColor('#e6eef8'),
  mountain: pixelColor('#4c515c'),
  mountainRidge: pixelColor('#7d828c'),
  groundEdge: pixelColor('#8f949e'),
  ground: pixelColor('#33373f'),
  pad: pixelColor('#c9ced8'),
  pole: pixelColor('#b8bcc6'),
  flag: pixelColor('#4fb3a0'),
  lander: pixelColor('#c3c9d4'),
  landerWindow: pixelColor('#3da4ff'),
  landerBase: pixelColor('#8a5a2b'),
  landerLegs: pixelColor('#8e95a3'),
} as const

/** Low-resolution buffer of every game: 16:9, scaled up by CSS. */
export const PIXEL_W = 320
export const PIXEL_H = 180
