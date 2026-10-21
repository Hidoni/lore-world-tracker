import '@testing-library/jest-dom/vitest'

import { cleanup } from '@testing-library/react'
import { toast } from 'sonner'
import { afterAll, afterEach, beforeAll } from 'vitest'

import { setPreviewingAsReader } from '@/api/reader-preview'

import { server } from './msw'

// jsdom lacks these browser APIs; sonner, Radix and ProseMirror use them. (Some suites run in node.)
function stub(target: object, name: string, value: unknown): void {
  if ((target as Record<string, unknown>)[name] === undefined) {
    Object.defineProperty(target, name, { value, configurable: true, writable: true })
  }
}

if (typeof window !== 'undefined') {
  stub(window, 'matchMedia', (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  }))
  stub(Element.prototype, 'hasPointerCapture', () => false)
  stub(Element.prototype, 'setPointerCapture', () => undefined)
  stub(Element.prototype, 'releasePointerCapture', () => undefined)
  stub(Element.prototype, 'scrollIntoView', () => undefined)
  // ProseMirror measures ranges (scrolling the selection into view, suggestion menus).
  const rect = () => new DOMRect(0, 0, 0, 0)
  stub(Range.prototype, 'getClientRects', () => [])
  stub(Range.prototype, 'getBoundingClientRect', rect)
  stub(document, 'elementFromPoint', () => null)
  stub(
    globalThis,
    'ResizeObserver',
    class {
      observe = () => undefined
      unobserve = () => undefined
      disconnect = () => undefined
    },
  )
}

// Requests a test leaves running (a save on unmount) are answered by that test's handlers: msw 3
// resolves them after the next test's handlers are in place otherwise.
const pending = new Set<string>()
server.events.on('request:start', ({ requestId }) => pending.add(requestId))
server.events.on('request:end', ({ requestId }) => pending.delete(requestId))

async function settled(): Promise<void> {
  for (let tick = 0; tick < 100; tick++) {
    await new Promise((resolve) => setTimeout(resolve, 0))
    if (pending.size === 0) return
  }
}

beforeAll(() => {
  server.listen({ onUnhandledFrame: 'error' })
})

afterEach(async () => {
  cleanup()
  await settled()
  server.resetHandlers()
  if (typeof localStorage !== 'undefined') localStorage.clear()
  if (typeof sessionStorage !== 'undefined') sessionStorage.clear()
  setPreviewingAsReader(false)
  toast.dismiss() // sonner's store outlives each test's Toaster
})

afterAll(() => {
  server.close()
})
