/**
 * Tiny pixel renderer for the 8-bit look. Draws into a low-resolution buffer (one ImageData, written as
 * 32-bit words) and puts it on the canvas once per frame; CSS scales the canvas up with
 * `image-rendering: pixelated`. Every shape is rasterised by hand, so there is no anti-aliasing.
 */

/** '#rrggbb' to the 32-bit pixel word ImageData uses on little-endian machines (ABGR). */
export function pixelColor(hex: string): number {
  const value = Number.parseInt(hex.slice(1), 16)
  const r = (value >> 16) & 0xff
  const g = (value >> 8) & 0xff
  const b = value & 0xff
  return ((0xff << 24) | (b << 16) | (g << 8) | r) >>> 0
}

export class PixelBuffer {
  readonly image: ImageData
  private readonly data: Uint32Array

  constructor(
    readonly width: number,
    readonly height: number,
  ) {
    this.image = new ImageData(width, height)
    this.data = new Uint32Array(this.image.data.buffer)
  }

  clear(color: number): void {
    this.data.fill(color)
  }

  set(x: number, y: number, color: number): void {
    const px = Math.round(x)
    const py = Math.round(y)
    if (px < 0 || py < 0 || px >= this.width || py >= this.height) return
    this.data[py * this.width + px] = color
  }

  rect(x: number, y: number, w: number, h: number, color: number): void {
    const x0 = Math.max(0, Math.round(x))
    const y0 = Math.max(0, Math.round(y))
    const x1 = Math.min(this.width, Math.round(x + w))
    const y1 = Math.min(this.height, Math.round(y + h))
    for (let py = y0; py < y1; py++) this.data.fill(color, py * this.width + x0, py * this.width + x1)
  }

  /** Filled circle. */
  disc(cx: number, cy: number, r: number, color: number): void {
    const rr = r * r
    for (let dy = -Math.ceil(r); dy <= Math.ceil(r); dy++) {
      const span = Math.floor(Math.sqrt(Math.max(0, rr - dy * dy)))
      this.rect(cx - span, cy + dy, span * 2 + 1, 1, color)
    }
  }

  /** Straight line (Bresenham). */
  line(x0: number, y0: number, x1: number, y1: number, color: number): void {
    let x = Math.round(x0)
    let y = Math.round(y0)
    const xe = Math.round(x1)
    const ye = Math.round(y1)
    const dx = Math.abs(xe - x)
    const dy = -Math.abs(ye - y)
    const sx = x < xe ? 1 : -1
    const sy = y < ye ? 1 : -1
    let err = dx + dy
    for (let guard = 0; guard < 4096; guard++) {
      this.set(x, y, color)
      if (x === xe && y === ye) return
      const e2 = 2 * err
      if (e2 >= dy) {
        err += dy
        x += sx
      }
      if (e2 <= dx) {
        err += dx
        y += sy
      }
    }
  }

  /** Filled quadrilateral (corners in order), drawn as two triangles. */
  quad(ax: number, ay: number, bx: number, by: number, cx: number, cy: number, dx: number, dy: number, color: number): void {
    this.triangle(ax, ay, bx, by, cx, cy, color)
    this.triangle(ax, ay, cx, cy, dx, dy, color)
  }

  /** Filled triangle: every pixel whose centre is inside the three edges. */
  triangle(ax: number, ay: number, bx: number, by: number, cx: number, cy: number, color: number): void {
    const minX = Math.max(0, Math.floor(Math.min(ax, bx, cx)))
    const maxX = Math.min(this.width - 1, Math.ceil(Math.max(ax, bx, cx)))
    const minY = Math.max(0, Math.floor(Math.min(ay, by, cy)))
    const maxY = Math.min(this.height - 1, Math.ceil(Math.max(ay, by, cy)))
    const area = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
    if (area === 0) return
    for (let py = minY; py <= maxY; py++) {
      for (let px = minX; px <= maxX; px++) {
        const x = px + 0.5
        const y = py + 0.5
        const w0 = ((bx - x) * (cy - y) - (by - y) * (cx - x)) / area
        const w1 = ((cx - x) * (ay - y) - (cy - y) * (ax - x)) / area
        const w2 = 1 - w0 - w1
        if (w0 >= 0 && w1 >= 0 && w2 >= 0) this.data[py * this.width + px] = color
      }
    }
  }

  present(ctx: CanvasRenderingContext2D): void {
    ctx.putImageData(this.image, 0, 0)
  }
}

/** A fixed starfield, so the stars do not jump between frames. */
export function makeStars(width: number, height: number, count: number, random: () => number = Math.random) {
  return Array.from({ length: count }, () => ({
    x: Math.floor(random() * width),
    y: Math.floor(random() * height),
    tone: Math.floor(random() * 3),
  }))
}
