import type { Correspondence } from '@lore/chronology'
import { toLogPx, toPx, viewport } from '@lore/chronology/viewport'
import { useId, useState } from 'react'

import { chartRange, chartSamples } from '../draft'

const WIDTH = 480
const HEIGHT = 220
const PAD = { left: 8, right: 8, top: 10, bottom: 34 }
const PLOT_W = WIDTH - PAD.left - PAD.right
const PLOT_H = HEIGHT - PAD.top - PAD.bottom

/**
 * The mapping preview (docs/modules/correspondences.md, UI): moments of dimension A across,
 * the corresponding moments of B up, one 2px line per stretch where the mapping is defined, the
 * sync points as markers, with a linear or logarithmic scale. Hovering shows the pair under the
 * pointer; the sync points' list in the editor is the table view.
 */
export function MappingChart({
  correspondence,
  durationA,
  durationB,
  nameA,
  nameB,
  formatA,
  formatB,
}: {
  correspondence: Correspondence
  durationA: bigint
  durationB: bigint
  nameA: string
  nameB: string
  formatA: (t: bigint) => string
  formatB: (t: bigint) => string
}) {
  const id = useId()
  const [log, setLog] = useState(false)
  const [hover, setHover] = useState<number | null>(null)
  const [lo, hi] = chartRange(correspondence, durationA)
  const samples = chartSamples(correspondence, lo, hi, durationB)
  const ys = samples.flatMap(([, b]) => (b === null ? [] : [b]))
  const yLo = ys.reduce((min, b) => (b < min ? b : min), ys[0] ?? 0n)
  const yHiRaw = ys.reduce((max, b) => (b > max ? b : max), ys[0] ?? 1n)
  const yHi = yHiRaw > yLo ? yHiRaw : yLo + 1n
  const vx = viewport(lo, hi - lo, PLOT_W)
  const vy = viewport(yLo, yHi - yLo, PLOT_H)
  const x = (a: bigint) => PAD.left + (log ? toLogPx(lo, hi, PLOT_W, a) : toPx(vx, a))
  const y = (b: bigint) => PAD.top + PLOT_H - (log ? toLogPx(yLo, yHi, PLOT_H, b) : toPx(vy, b))

  // Defined stretches, each one polyline.
  const runs: string[][] = []
  let run: string[] | null = null
  for (const [a, b] of samples) {
    if (b === null) {
      run = null
      continue
    }
    if (run === null) {
      run = []
      runs.push(run)
    }
    run.push(`${x(a).toFixed(1)},${y(b).toFixed(1)}`)
  }
  const shown = hover === null ? null : samples[hover]

  return (
    <figure className="flex flex-col gap-1" aria-labelledby={`${id}-caption`}>
      <div className="flex items-center gap-2">
        <figcaption id={`${id}-caption`} className="text-sm font-medium">
          {nameA} → {nameB}
        </figcaption>
        <div className="flex-1" />
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={log}
            onChange={(event) => {
              setLog(event.target.checked)
            }}
          />
          Log scale
        </label>
      </div>
      <svg
        role="img"
        aria-label={`How moments of ${nameA} map to ${nameB}`}
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="w-full touch-none select-none"
        data-testid="mapping-chart"
        onPointerMove={(event) => {
          const box = event.currentTarget.getBoundingClientRect()
          const px = ((event.clientX - box.left) / box.width) * WIDTH
          let best = 0
          samples.forEach(([a], index) => {
            const [bestA] = samples[best] ?? [a]
            if (Math.abs(x(a) - px) < Math.abs(x(bestA) - px)) best = index
          })
          setHover(best)
        }}
        onPointerLeave={() => {
          setHover(null)
        }}
      >
        {/* Recessive frame: the plot's baseline and left edge. */}
        <line
          x1={PAD.left}
          x2={PAD.left + PLOT_W}
          y1={PAD.top + PLOT_H}
          y2={PAD.top + PLOT_H}
          className="stroke-border"
        />
        <line
          x1={PAD.left}
          x2={PAD.left}
          y1={PAD.top}
          y2={PAD.top + PLOT_H}
          className="stroke-border"
        />
        {runs.map((points, index) => (
          <polyline
            key={index}
            points={points.join(' ')}
            fill="none"
            strokeWidth={2}
            strokeLinejoin="round"
            strokeLinecap="round"
            className="stroke-primary"
            data-testid="mapping-run"
          />
        ))}
        {correspondence.points.map(([a, b]) =>
          a < lo || a > hi ? null : (
            <circle
              key={a.toString()}
              cx={x(a)}
              cy={y(b)}
              r={4}
              strokeWidth={2}
              className="fill-primary stroke-background"
              data-testid="sync-marker"
            />
          ),
        )}
        {shown !== undefined && shown !== null && (
          <g pointerEvents="none">
            <line
              x1={x(shown[0])}
              x2={x(shown[0])}
              y1={PAD.top}
              y2={PAD.top + PLOT_H}
              className="stroke-muted-foreground/60"
              strokeDasharray="3 3"
            />
            {shown[1] !== null && (
              <circle
                cx={x(shown[0])}
                cy={y(shown[1])}
                r={4}
                strokeWidth={2}
                className="fill-background stroke-primary"
              />
            )}
          </g>
        )}
        <text x={PAD.left} y={HEIGHT - 18} className="fill-muted-foreground text-[10px]">
          {formatA(lo)}
        </text>
        <text
          x={PAD.left + PLOT_W}
          y={HEIGHT - 18}
          textAnchor="end"
          className="fill-muted-foreground text-[10px]"
        >
          {formatA(hi)}
        </text>
        <text
          x={PAD.left + PLOT_W / 2}
          y={HEIGHT - 4}
          textAnchor="middle"
          className="fill-muted-foreground text-[10px]"
        >
          {nameA}
        </text>
      </svg>
      <p className="min-h-5 text-xs text-muted-foreground" aria-live="polite">
        {shown === undefined || shown === null
          ? `${nameB} from ${formatB(yLo)} to ${formatB(yHi)}`
          : `${formatA(shown[0])} in ${nameA} → ${
              shown[1] === null ? 'nothing' : formatB(shown[1])
            } in ${nameB}`}
      </p>
    </figure>
  )
}
