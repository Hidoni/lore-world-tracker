import type { KeyboardEvent, PointerEvent } from 'react'

import { SIDEBAR_DEFAULT, SIDEBAR_MAX, SIDEBAR_MIN, useShell } from './shell-store'

const STEP = 16

/** The sidebar's resize handle: drag it, or focus it and use the arrow keys (Home/End). */
export function SidebarResizer() {
  const width = useShell((state) => state.sidebarWidth)
  const setWidth = useShell((state) => state.setSidebarWidth)

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>): void => {
    const next = {
      ArrowLeft: width - STEP,
      ArrowRight: width + STEP,
      Home: SIDEBAR_MIN,
      End: SIDEBAR_MAX,
      Enter: SIDEBAR_DEFAULT,
    }[event.key]
    if (next === undefined) return
    event.preventDefault()
    setWidth(next)
  }

  const onPointerDown = (event: PointerEvent<HTMLDivElement>): void => {
    event.preventDefault()
    const startX = event.clientX
    const startWidth = width
    const target = event.currentTarget
    target.setPointerCapture(event.pointerId)
    const onMove = (move: globalThis.PointerEvent): void => {
      setWidth(startWidth + move.clientX - startX)
    }
    const onUp = (): void => {
      target.removeEventListener('pointermove', onMove)
      target.removeEventListener('pointerup', onUp)
    }
    target.addEventListener('pointermove', onMove)
    target.addEventListener('pointerup', onUp)
  }

  return (
    // A focusable separator is the ARIA "window splitter" pattern: it is interactive.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize sidebar"
      aria-valuenow={width}
      aria-valuemin={SIDEBAR_MIN}
      aria-valuemax={SIDEBAR_MAX}
      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- window splitter (see above)
      tabIndex={0}
      onKeyDown={onKeyDown}
      onPointerDown={onPointerDown}
      className="w-1 shrink-0 cursor-col-resize bg-border/0 transition-colors hover:bg-border focus-visible:bg-ring focus-visible:outline-none"
    />
  )
}
