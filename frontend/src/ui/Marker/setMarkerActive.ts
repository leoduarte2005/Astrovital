/**
 * Keeps a marker's leader line and name chip visible without hover (e.g. the selected marker).
 * Driven by a data attribute, so no React state is involved.
 */
export function setMarkerActive(element: HTMLElement, active: boolean): void {
  element.dataset.active = active ? 'true' : 'false'
}
