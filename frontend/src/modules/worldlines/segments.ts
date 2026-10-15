import type { TimePoint } from '@lore/chronology'

import type { SegmentIn, WireTimePoint, WorldlineSegment } from '@/data'

/** An absolute time point at `t`. */
export function absolute(t: bigint): TimePoint {
  return { anchor: { kind: 'absolute', t: t.toString() }, precision: 'base', approximate: false }
}

const wire = (point: TimePoint): WireTimePoint => point as WireTimePoint

/**
 * A segment as the PUT takes it: its own time points (an implicit worldline's segments have
 * none: their moments, absolute).
 */
export function toInput(segment: WorldlineSegment): SegmentIn {
  const point = (spec: WorldlineSegment['start'], t: bigint | null): WireTimePoint =>
    spec !== null ? (spec as WireTimePoint) : wire(absolute(t ?? 0n))
  return {
    dimension_id: segment.dimension_id,
    timeline_id: segment.timeline_id ?? '',
    start: point(segment.start, segment.start_t),
    end: point(segment.end, segment.end_t),
    rate: segment.rate,
    departure_event_id: segment.departure_event_id,
    arrival_event_id: segment.arrival_event_id,
    note: segment.note,
    visibility: segment.visibility,
  }
}

/** The segments with the one at `index` split at `at` (two halves of the same visit). */
export function split(segments: readonly SegmentIn[], index: number, at: TimePoint): SegmentIn[] {
  const target = segments[index]
  if (target === undefined) return [...segments]
  const first: SegmentIn = { ...target, end: wire(at), departure_event_id: null }
  const second: SegmentIn = { ...target, start: wire(at), arrival_event_id: null }
  return [...segments.slice(0, index), first, second, ...segments.slice(index + 1)]
}

/** The segments with the one at `index` moved by `delta` places (worldline order). */
export function move(segments: readonly SegmentIn[], index: number, delta: number): SegmentIn[] {
  const to = index + delta
  if (to < 0 || to >= segments.length || index < 0 || index >= segments.length) {
    return [...segments]
  }
  const next = [...segments]
  const [moved] = next.splice(index, 1)
  if (moved !== undefined) next.splice(to, 0, moved)
  return next
}

/** A rational rate as text ("×2", "×1/2"); empty for 1. */
export function rateText(rate: { num: string; den: string }): string {
  if (rate.num === rate.den) return ''
  return rate.den === '1' ? `×${rate.num}` : `×${rate.num}/${rate.den}`
}
