import {
  nextPhaseAt,
  parseRational,
  rationalCompare,
  rationalFloor,
  rationalMul,
  rationalSub,
  rationalFromInt,
  type BigRational,
  type CompiledCalendar,
} from '@lore/chronology'
import { toPx, type Viewport } from '@lore/chronology/viewport'

export const OVERLAY_ROW_HEIGHT = 18
/** Phases closer together than this on screen hide the overlay. */
export const MIN_PHASE_PX = 18
/** Marks drawn per overlay at most. */
const MAX_MARKS = 400

/** Glyphs for a phase, by its start in eighths of the cycle (new → full → new). */
const GLYPHS: Record<string, string> = {
  '0': '🌑',
  '1': '🌒',
  '2': '🌓',
  '3': '🌔',
  '4': '🌕',
  '5': '🌖',
  '6': '🌗',
  '7': '🌘',
}

/** The glyph of a phase starting at `from` (a fraction of the cycle): the nearest eighth. */
export function phaseGlyph(from: BigRational): string {
  const eighths = ((from.num * 16n) / from.den + 1n) / 2n
  return GLYPHS[(eighths % 8n).toString()] ?? '•'
}

/** A phase starting at `t`. */
export interface PhaseMark {
  t: bigint
  x: number
  name: string
  glyph: string
}

export interface OverlayRow {
  id: string
  name: string
  marks: PhaseMark[]
}

/** The phases' starts, with the shortest phase (a fraction of the cycle; 1 for a single one). */
function phasesOf(phases: readonly { name: string; from: { num: string; den: string } }[]) {
  const starts = phases.map((phase) => ({
    name: phase.name,
    from: parseRational(phase.from.num, phase.from.den),
  }))
  let shortest = rationalFromInt(1n)
  starts.forEach((phase, i) => {
    const next = starts[i + 1]?.from ?? rationalFromInt(1n)
    const length = rationalSub(next, phase.from)
    if (length.num > 0n && rationalCompare(length, shortest) < 0) shortest = length
  })
  return { starts, shortest }
}

/**
 * The display calendar's overlays (chronology-engine.md §3.9) zoomed in enough to show their
 * phases: each phase start in the view, where the phase's name changes. Overlays whose shortest
 * phase is narrower than `MIN_PHASE_PX` are left out.
 */
export function overlayRows(calendar: CompiledCalendar | null, v: Viewport): OverlayRow[] {
  if (calendar === null) return []
  const end = v.start + v.span
  return (calendar.definition.overlays ?? []).flatMap((overlay) => {
    const { starts, shortest } = phasesOf(overlay.phases)
    const period = parseRational(overlay.period.num, overlay.period.den)
    const units = rationalFloor(rationalMul(shortest, period))
    if (toPx(v, v.start + units) - toPx(v, v.start) < MIN_PHASE_PX) return []
    const marks: PhaseMark[] = []
    try {
      starts.forEach((phase, i) => {
        const previous = starts.at(i - 1)
        // A phase named like the one before it continues it (a new moon either side of 0).
        if (starts.length > 1 && previous?.name === phase.name) return
        let t = nextPhaseAt(calendar, v.start, overlay.id, phase.from)
        while (t < end && marks.length < MAX_MARKS) {
          marks.push({ t, x: toPx(v, t), name: phase.name, glyph: phaseGlyph(phase.from) })
          t = nextPhaseAt(calendar, t + 1n, overlay.id, phase.from)
        }
      })
    } catch {
      return []
    }
    marks.sort((a, b) => (a.t < b.t ? -1 : a.t > b.t ? 1 : 0))
    return [{ id: overlay.id, name: overlay.name, marks }]
  })
}

/**
 * Astronomical overlays (frontend.md §9.1): a row of phase glyphs per overlay of the display
 * calendar, once zoomed in enough to tell its phases apart; hidden otherwise.
 */
export function OverlayStrip({ v, calendar }: { v: Viewport; calendar: CompiledCalendar | null }) {
  const rows = overlayRows(calendar, v)
  if (rows.length === 0) return null
  return (
    <div className="flex flex-col select-none" style={{ width: v.widthPx }}>
      {rows.map((row) => (
        <div
          key={row.id}
          role="group"
          aria-label={row.name}
          data-testid="overlay-row"
          className="relative overflow-hidden"
          style={{ height: OVERLAY_ROW_HEIGHT }}
        >
          {row.marks.map((mark) => (
            <span
              key={mark.t.toString()}
              data-testid="phase-mark"
              data-t={mark.t.toString()}
              role="img"
              aria-label={`${row.name}: ${mark.name}`}
              title={`${row.name}: ${mark.name}`}
              className="absolute top-0 text-[12px] leading-[18px]"
              style={{ transform: `translateX(${mark.x - 7}px)` }}
            >
              {mark.glyph}
            </span>
          ))}
        </div>
      ))}
    </div>
  )
}
