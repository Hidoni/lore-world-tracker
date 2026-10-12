/** Pointer capture where the platform has it (some test environments don't). */
export function capture(element: Element, pointerId: number): void {
  if ('setPointerCapture' in element) element.setPointerCapture(pointerId)
}

export function release(element: Element, pointerId: number): void {
  if ('releasePointerCapture' in element) element.releasePointerCapture(pointerId)
}
