import '@testing-library/jest-dom/vitest'

import { cleanup } from '@testing-library/react'
import { afterAll, afterEach, beforeAll } from 'vitest'

import { server } from './msw'

// jsdom lacks these browser APIs; sonner and Radix use them. (Some suites run in node.)
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

beforeAll(() => {
  server.listen({ onUnhandledRequest: 'error' })
})

afterEach(() => {
  cleanup()
  server.resetHandlers()
  if (typeof localStorage !== 'undefined') localStorage.clear()
})

afterAll(() => {
  server.close()
})
