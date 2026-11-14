/**
 * Moves a marker to CSS-pixel coordinates inside its positioned parent. Uses `transform` only,
 * so it can run every frame without React state. The caller owns the projection.
 */
export function placeMarker(element: HTMLElement, x: number, y: number): void {
  element.style.transform = `translate(${x}px, ${y}px) translate(-50%, -50%)`
  element.style.visibility = 'visible'
}
