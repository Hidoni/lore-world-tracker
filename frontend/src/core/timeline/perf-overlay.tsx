import { useEffect, useState } from 'react'

/** Whether the performance overlay is on: `?perf=1`, or `lore.debug.perf` in localStorage. */
export function perfEnabled(search: { perf?: unknown }): boolean {
  if (search.perf === '1' || search.perf === 1) return true
  try {
    return localStorage.getItem('lore.debug.perf') === '1'
  } catch {
    return false
  }
}

/**
 * The timeline's performance budget instrumentation (testing.md §4): frames per second over the
 * last second (from `requestAnimationFrame`) and how many times the view rendered.
 */
export function PerfOverlay({ renders }: { renders: () => number }) {
  const [fps, setFps] = useState(0)
  const [count, setCount] = useState(0)
  useEffect(() => {
    let frames = 0
    let since = performance.now()
    let handle = requestAnimationFrame(function tick(now) {
      frames += 1
      if (now - since >= 1000) {
        setFps(Math.round((frames * 1000) / (now - since)))
        setCount(renders())
        frames = 0
        since = now
      }
      handle = requestAnimationFrame(tick)
    })
    return () => {
      cancelAnimationFrame(handle)
    }
  }, [renders])
  return (
    <div
      role="status"
      aria-label="Performance"
      className="pointer-events-none absolute top-2 right-2 rounded bg-black/70 px-2 py-1 font-mono text-[11px] text-white"
    >
      {fps} fps · {count} renders
    </div>
  )
}
