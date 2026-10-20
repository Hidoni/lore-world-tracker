import { ApiError } from '@/data'

/** Problems of a time point (`/time/resolve` items, time-model.md §6) in plain words. */
const MESSAGES: Record<string, string> = {
  unresolved_ref: 'The target has no moment (not set, purged, or hidden).',
  time_cycle: 'This would make a cycle: the target depends on this time point.',
  unknown_slot: 'That edge doesn’t exist.',
  slot_not_referenceable: 'That edge can’t be referenced.',
  not_supported: 'Only events have occurrences.',
  out_of_bounds: 'This falls outside the dimension (before its inception or after its end).',
  invalid_date: 'Not a valid date.',
  reform_gap: 'This date was skipped by a calendar reform.',
  reform_ambiguous: 'This date exists twice across a calendar reform.',
  calendar_error: 'The calendar doesn’t compile.',
  range_invalid:
    'The range doesn’t hold: its latest date comes before its earliest, or the best estimate lies outside it.',
  unmapped:
    'The target is in another dimension, and no correspondence says what happens here then.',
}

export function timeProblemMessage(code: string, fallback: string): string {
  return MESSAGES[code] ?? fallback
}

/**
 * A refused time write in plain words (time-model.md §7.2): `409 time_cycle` names the cycle's
 * path, `422 time_constraint` the broken checks (an end before its start, out of bounds). `null`
 * for other errors.
 */
export function timeWriteProblem(error: unknown): string | null {
  if (!(error instanceof ApiError)) return null
  if (error.code === 'time_cycle') {
    const path = Array.isArray(error.context.path)
      ? error.context.path.filter((step): step is string => typeof step === 'string')
      : []
    return path.length > 0
      ? `This would make a cycle: ${path.join(' → ')}.`
      : 'This would make a cycle of time points.'
  }
  if (error.code === 'time_constraint') {
    const records = Array.isArray(error.context.records) ? error.context.records : []
    const codes = records.flatMap((record: unknown) =>
      record !== null &&
      typeof record === 'object' &&
      typeof (record as { code?: unknown }).code === 'string'
        ? [(record as { code: string }).code]
        : [],
    )
    if (codes.includes('end_before_start')) return 'The end would come before the start.'
    if (codes.includes('out_of_bounds')) return MESSAGES.out_of_bounds ?? null
    if (codes.includes('range_invalid')) return MESSAGES.range_invalid ?? null
    return error.detail
  }
  return null
}
