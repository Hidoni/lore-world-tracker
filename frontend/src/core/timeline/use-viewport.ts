import { rational, type BigRational } from '@lore/chronology'
import {
  centerOn,
  clamp,
  fit,
  panBy,
  toLinear,
  toLogScale,
  viewport,
  zoomAt,
  type Viewport,
} from '@lore/chronology/viewport'
import { useNavigate, useSearch } from '@tanstack/react-router'
import { useCallback, useEffect, useRef, useState } from 'react'

/** How long the URL waits for the viewport to settle (frontend.md §9.2). */
export const URL_DEBOUNCE_MS = 250
/** Free pixels on each side when the whole dimension is fitted. */
const FIT_PADDING_PX = 24

const SIGNED = /^-?(0|[1-9][0-9]*)$/

/** `from`/`to` of the URL as a range, when both are integers with `to > from`. */
export function rangeOf(search: { from?: string; to?: string }): [bigint, bigint] | null {
  if (search.from === undefined || search.to === undefined) return null
  if (!SIGNED.test(search.from) || !SIGNED.test(search.to)) return null
  const from = BigInt(search.from)
  const to = BigInt(search.to)
  return to > from ? [from, to] : null
}

/** A zoom factor as an exact rational (`2^steps`, to 1/1024). */
export function zoomFactor(steps: number): BigRational {
  return rational(BigInt(Math.max(1, Math.round(2 ** steps * 1024))), 1024n)
}

export interface ViewportControls {
  viewport: Viewport
  /** Zoom by `factor` around pixel `x` (below 1 zooms in). */
  zoom: (x: number, factor: BigRational) => void
  /** Move `dx` pixels later in time. */
  pan: (dx: number) => void
  /** Show `[start, end]` (with padding), or the whole dimension. */
  show: (start: bigint, end: bigint) => void
  fitAll: () => void
  /** Center the view on `t`, keeping the span. */
  center: (t: bigint) => void
  /** Whether the axis is logarithmic (#153): decades since inception, URL `scale=log`. */
  logScale: boolean
  /** Switch between the linear and the logarithmic axis, keeping the range shown. */
  toggleScale: () => void
}

/**
 * The timeline's viewport (chronology-engine.md §12): bigint-exact, clamped to the dimension,
 * `widthPx` wide, initialized from the URL's `from`/`to` (else the whole dimension) and written
 * back to it after `URL_DEBOUNCE_MS` of calm (replacing the history entry).
 */
export function useViewport(D: bigint, widthPx: number): ViewportControls {
  const search: { from?: string; to?: string; scale?: string } = useSearch({ strict: false })
  const navigate = useNavigate()
  const [state, setState] = useState<Viewport>(() => {
    const range = rangeOf(search)
    const base = viewport(0n, D > 0n ? D : 1n, widthPx)
    const linear =
      range === null
        ? fit(base, 0n, D, FIT_PADDING_PX)
        : viewport(range[0], range[1] - range[0], widthPx)
    return clamp(search.scale === 'log' ? toLogScale(linear) : linear, D)
  })
  // The width follows the container; the span stays (the scale changes).
  const current = state.widthPx === widthPx ? state : { ...state, widthPx }
  const update = useCallback(
    (change: (v: Viewport) => Viewport) => {
      setState((previous) => clamp(change({ ...previous, widthPx }), D))
    },
    [D, widthPx],
  )

  // The URL follows once the view settles; a URL changed elsewhere (back/forward) moves the view.
  const written = useRef<string | null>(null)
  const scale = current.log === undefined ? undefined : ('log' as const)
  const key = `${current.start}:${current.start + current.span}:${scale ?? ''}`
  useEffect(() => {
    const timer = setTimeout(() => {
      if (written.current === key) return
      written.current = key
      void navigate({
        to: '.',
        search: (previous: Record<string, unknown>) => ({
          ...previous,
          from: current.start.toString(),
          to: (current.start + current.span).toString(),
          scale,
        }),
        replace: true,
      })
    }, URL_DEBOUNCE_MS)
    return () => {
      clearTimeout(timer)
    }
  }, [key, current.start, current.span, scale, navigate])
  const range = rangeOf(search)
  const urlKey = range === null ? null : `${range[0]}:${range[1]}:${search.scale ?? ''}`
  useEffect(() => {
    if (range === null || urlKey === written.current) return
    written.current = urlKey
    const linear = viewport(range[0], range[1] - range[0], widthPx)
    setState(clamp(search.scale === 'log' ? toLogScale(linear) : linear, D))
    // Only an outside change of the URL moves the view.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlKey])

  return {
    viewport: current,
    zoom: (x, factor) => {
      update((v) => zoomAt(v, x, factor))
    },
    pan: (dx) => {
      update((v) => panBy(v, dx))
    },
    show: (start, end) => {
      update((v) => fit(v, start, end, FIT_PADDING_PX))
    },
    fitAll: () => {
      update((v) => fit(v, 0n, D, FIT_PADDING_PX))
    },
    center: (t) => {
      update((v) => centerOn(v, t))
    },
    logScale: current.log !== undefined,
    toggleScale: () => {
      update((v) => (v.log === undefined ? toLogScale(v) : toLinear(v)))
    },
  }
}
