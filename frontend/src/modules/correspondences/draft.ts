import {
  add,
  rational,
  validateCorrespondence,
  type BigRational,
  type Correspondence,
  type TimePoint,
} from '@lore/chronology'

import { pointMoment, type Lens } from '@/core/time'

/** A sync point being edited: a time point per side (`null`: not entered yet). */
export interface PointDraft {
  key: string
  a: TimePoint | null
  b: TimePoint | null
}

/** A rate being edited: numerator and denominator (both empty: the adjacent segment's slope). */
export interface RateDraft {
  num: bigint | null
  den: bigint | null
}

export const NO_RATE: RateDraft = { num: null, den: null }

/** A draft rate as a rational (`null`: none, or incomplete). */
export function rateOf(draft: RateDraft): BigRational | null {
  if (draft.num === null || draft.den === null || draft.den <= 0n) return null
  return rational(draft.num, draft.den)
}

export function rateDraft(value: { num: string; den: string } | null): RateDraft {
  return value === null ? NO_RATE : { num: BigInt(value.num), den: BigInt(value.den) }
}

/** What the editor's preview (chart, tester) can show of a draft. */
export type Preview =
  | { kind: 'ok'; correspondence: Correspondence }
  /** Sync points the browser can't place yet (relative anchors resolve on save). */
  | { kind: 'pending' }
  | { kind: 'invalid'; message: string }

/**
 * The draft compiled by the TS engine when every sync point's moments are known in the browser
 * (absolute or calendar anchors): the same validation the server runs after resolution.
 */
export function previewOf(
  points: readonly PointDraft[],
  lensesA: readonly Lens[],
  lensesB: readonly Lens[],
  extrapolation: 'none' | 'rate',
  before: RateDraft,
  after: RateDraft,
): Preview {
  const moments: (readonly [bigint, bigint])[] = []
  for (const point of points) {
    const a = point.a === null ? null : pointMoment(point.a, lensesA)
    const b = point.b === null ? null : pointMoment(point.b, lensesB)
    if (a === null || b === null) return { kind: 'pending' }
    moments.push([a, b])
  }
  if (moments.length === 0) return { kind: 'pending' }
  try {
    return {
      kind: 'ok',
      correspondence: validateCorrespondence(moments, {
        extrapolation,
        rateBefore: rateOf(before),
        rateAfter: rateOf(after),
      }),
    }
  } catch (error) {
    return { kind: 'invalid', message: error instanceof Error ? error.message : String(error) }
  }
}

/** The base units of one `level` of a calendar starting at `at` (Absolute: one base unit). */
export function levelLength(lens: Lens, level: string | null, at: bigint): bigint | null {
  if (lens.calendar === null || level === null) return 1n
  try {
    const end = add(lens.calendar, at, {
      kind: 'calendar',
      calendar_id: lens.id,
      amounts: { [level]: '1' },
      sign: 1,
    })
    return end > at ? end - at : null
  } catch {
    return null
  }
}

/**
 * "`here` × (a level here) = `there` × (a level there)": the rate in base units of there per base
 * unit of here (`null` when a side is empty or not positive).
 */
export function helperRate(
  here: bigint,
  hereLength: bigint,
  there: bigint,
  thereLength: bigint,
): BigRational | null {
  if (here <= 0n || there <= 0n || hereLength <= 0n || thereLength <= 0n) return null
  return rational(there * thereLength, here * hereLength)
}

/**
 * Where the mapping chart samples `a`: from the first to the last sync point, widened by half
 * that span on each side when extrapolating (or around a single point), within `[0, D_A]`.
 */
export function chartRange(c: Correspondence, durationA: bigint): readonly [bigint, bigint] {
  const first = c.points[0]?.[0] ?? 0n
  const last = c.points.at(-1)?.[0] ?? durationA
  const span = last - first
  const margin = c.extrapolate ? (span > 0n ? span / 2n : first > 0n ? first : 10n) : 0n
  const lo = first - margin < 0n ? 0n : first - margin
  const hi = last + margin > durationA ? durationA : last + margin
  return hi > lo ? [lo, hi] : [lo, lo + 1n]
}

/** `count + 1` evenly spaced samples `(a, b)` of the mapping over `[lo, hi]`, plus every sync
 * point inside it (`b` null: no corresponding moment), sorted by `a`. */
export function chartSamples(
  c: Correspondence,
  lo: bigint,
  hi: bigint,
  durationB: bigint,
  count = 120,
): (readonly [bigint, bigint | null])[] {
  const xs = new Set<bigint>()
  const steps = BigInt(count)
  for (let i = 0n; i <= steps; i++) xs.add(lo + ((hi - lo) * i) / steps)
  for (const [a] of c.points) if (a >= lo && a <= hi) xs.add(a)
  return [...xs].sort((x, y) => (x < y ? -1 : x > y ? 1 : 0)).map((a) => [a, c.mapAB(a, durationB)])
}
