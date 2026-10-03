// The conformance ops (spec/chronology/conformance/README.md) as calls into the TypeScript engine,
// shared by the conformance runner (test/conformance.test.ts) and the differential-testing CLI
// (bin/chrono-exec.ts). Inputs and results are the README's JSON shapes.
import { PRESETS } from '../src/preset-library'
import {
  add,
  type Bounds,
  CompiledCalendar,
  cycleValue,
  DateError,
  dateFieldsToJson,
  diff,
  differenceToJson,
  type DisplayPoint,
  formatAbsolute,
  formatDate,
  formatSpan,
  eraOf,
  eraValueToJson,
  fromFields,
  fromOrdinal,
  nextPhaseAt,
  options,
  optionsToJson,
  ordinal,
  type Overflow,
  overlayPhase,
  overlayValueToJson,
  toFields,
  unitBounds,
  validateCalendar,
} from '../src/calendar'
import {
  compose,
  CorrespondenceError,
  type Direction,
  type Step,
  validateCorrespondence,
} from '../src/correspondence'
import { instantiatePreset, PresetError } from '../src/presets'
import {
  countInWindow,
  expand,
  expansionToJson,
  occurrence,
  occurrenceAt,
  occurrenceNumber,
  occurrenceToJson,
  type RecurrenceContext,
  RecurrenceError,
  seriesBounds,
  seriesBoundsToJson,
} from '../src/recurrence'
import type { BaseUnit, Duration, EndSpec, RecurrenceRule } from '../src/schema.gen'
import {
  type BigRational,
  floorDiv,
  floorMod,
  formatInteger,
  formatMoment,
  formatRational,
  formatSigned,
  fromSortableKey,
  type IntegerDisplayOptions,
  NumberError,
  parseMoment,
  parseRational,
  parseSigned,
  rationalAdd,
  rationalCompare,
  rationalDiv,
  rationalFloor,
  rationalFrac,
  rationalFromInt,
  rationalMul,
  rationalSub,
  sortableKey,
} from '../src/numbers'

export const NUMBER_OPS = [
  'parse_moment',
  'format_moment',
  'parse_signed',
  'format_signed',
  'sortable_key',
  'from_sortable_key',
  'floor_div',
  'floor_mod',
  'rational_normalize',
  'rational_from_int',
  'rational_add',
  'rational_sub',
  'rational_mul',
  'rational_div',
  'rational_compare',
  'rational_floor',
  'rational_frac',
  'format_integer',
] as const

/** Every op documented in the conformance README. */
export const OPS = [
  ...NUMBER_OPS,
  'validate',
  'to_fields',
  'from_fields',
  'unit_bounds',
  'ordinal',
  'from_ordinal',
  'options',
  'cycle_value',
  'era_of',
  'overlay_phase',
  'next_phase_at',
  'add',
  'diff',
  'format',
  'format_span',
  'format_absolute',
  'preset_instantiate',
  'expand',
  'series_bounds',
  'occurrence',
  'count_in_window',
  'occurrence_number',
  'occurrence_at',
  'map',
  'compose',
] as const
export type Op = (typeof OPS)[number]

export const CALENDAR_FREE_OPS: readonly Op[] = [
  ...NUMBER_OPS,
  'validate',
  'format_absolute',
  'preset_instantiate',
  'map',
  'compose',
]
export const RECURRENCE_OPS: readonly Op[] = [
  'expand',
  'series_bounds',
  'occurrence',
  'count_in_window',
  'occurrence_number',
  'occurrence_at',
]

/** A calendar file of spec/chronology/conformance/calendars/ (`description` is not needed). */
export interface CalendarDocument {
  readonly definition: unknown
  readonly context: unknown
}

type Handler = (calendar: CalendarDocument | null, input: Record<string, unknown>) => unknown

export class NotImplementedError extends Error {
  constructor(op: string) {
    super(`${op} is not implemented in @lore/chronology yet`)
    this.name = 'NotImplementedError'
  }
}

type Json = Record<string, unknown>
const str = (data: Json, key: string): string => data[key] as string
const rat = (data: unknown): BigRational => {
  const { num, den } = data as { num: string; den: string }
  return parseRational(num, den)
}
const binary =
  (operation: (a: BigRational, b: BigRational) => BigRational): Handler =>
  (_, d) =>
    formatRational(operation(rat(d.a), rat(d.b)))

function displayOptions(d: Json): IntegerDisplayOptions {
  const options: IntegerDisplayOptions = {}
  if ('digit_group' in d) options.digitGroup = d.digit_group as string
  if ('scientific_threshold' in d) options.scientificThreshold = d.scientific_threshold as number
  if ('significant_digits' in d) options.significantDigits = d.significant_digits as number
  if ('plain' in d) options.plain = d.plain as boolean
  return options
}

const bounds = ({ start, end }: Bounds) => ({ start: start.toString(), end: end.toString() })

function displayPoint(data: unknown): DisplayPoint | null {
  if (data === null) return null
  const { t, precision, approximate } = data as Json
  return {
    t: BigInt(t as string),
    precision: precision as string,
    approximate: approximate as boolean,
  }
}

const COMPILED = new WeakMap<CalendarDocument, CompiledCalendar>()

function compiled(calendar: CalendarDocument | null): CompiledCalendar {
  if (calendar === null) throw new Error("this op needs the case file's calendar")
  let result = COMPILED.get(calendar)
  if (result === undefined) {
    const outcome = validateCalendar(calendar.definition, calendar.context)
    if (!(outcome instanceof CompiledCalendar)) throw new Error(JSON.stringify(outcome))
    result = outcome
    COMPILED.set(calendar, result)
  }
  return result
}

/** The rule and context of a recurrence case (README "Recurrence ops"). */
function recurrence(
  calendar: CalendarDocument | null,
  d: Json,
): readonly [RecurrenceRule, RecurrenceContext] {
  const dimensionDuration =
    calendar === null
      ? BigInt(str(d, 'dimension_duration'))
      : BigInt((calendar.context as Json).dimension_duration as string)
  const resolved = Object.fromEntries(
    Object.entries(d.resolved as Record<string, string>).map(([key, t]) => [key, BigInt(t)]),
  )
  const ctx: RecurrenceContext = {
    seriesStart: BigInt(str(d, 'series_start')),
    end: d.end as EndSpec,
    dimensionDuration,
    calendar: calendar === null ? null : compiled(calendar),
    resolved,
  }
  return [d.rule as RecurrenceRule, ctx]
}

const windowOf = (d: Json): readonly [bigint, bigint] => {
  const [w0, w1] = d.window as [string, string]
  return [BigInt(w0), BigInt(w1)]
}

/** A correspondence of a `map` / `compose` input (README "`map`"). */
function correspondence(data: unknown) {
  const { extrapolation, rate_before, rate_after, points } = data as Json
  return validateCorrespondence(
    (points as { a: string; b: string }[]).map(({ a, b }) => [BigInt(a), BigInt(b)] as const),
    {
      extrapolation: extrapolation as 'none' | 'rate',
      rateBefore: rate_before === null ? null : rat(rate_before),
      rateAfter: rate_after === null ? null : rat(rate_after),
    },
  )
}

const momentOrNull = (t: bigint | null) => ({ t: t === null ? null : t.toString() })

/** op → engine call returning the result in the README's JSON shape (errors as `{error}`). */
// Inputs named n/a/b are deliberately parsed without validation (they may be out of range).
export const HANDLERS: Partial<Record<Op, Handler>> = {
  parse_moment: (_, d) => ({ value: parseMoment(str(d, 'text')).toString() }),
  parse_signed: (_, d) => ({ value: parseSigned(str(d, 'text')).toString() }),
  format_moment: (_, d) => ({ text: formatMoment(BigInt(str(d, 'n'))) }),
  format_signed: (_, d) => ({ text: formatSigned(BigInt(str(d, 'n'))) }),
  sortable_key: (_, d) => ({ key: sortableKey(BigInt(str(d, 'n'))) }),
  from_sortable_key: (_, d) => ({ n: fromSortableKey(str(d, 'key')).toString() }),
  floor_div: (_, d) => ({ value: floorDiv(BigInt(str(d, 'a')), BigInt(str(d, 'b'))).toString() }),
  floor_mod: (_, d) => ({ value: floorMod(BigInt(str(d, 'a')), BigInt(str(d, 'b'))).toString() }),
  rational_normalize: (_, d) => formatRational(rat(d)),
  rational_from_int: (_, d) => formatRational(rationalFromInt(BigInt(str(d, 'n')))),
  rational_add: binary(rationalAdd),
  rational_sub: binary(rationalSub),
  rational_mul: binary(rationalMul),
  rational_div: binary(rationalDiv),
  rational_compare: (_, d) => ({ value: rationalCompare(rat(d.a), rat(d.b)) }),
  rational_floor: (_, d) => ({ value: rationalFloor(rat(d.a)).toString() }),
  rational_frac: (_, d) => formatRational(rationalFrac(rat(d.a))),
  format_integer: (_, d) => ({ text: formatInteger(BigInt(str(d, 'n')), displayOptions(d)) }),
  validate: (_, d) => {
    const result = validateCalendar(d.definition, d.context)
    const errors = result instanceof CompiledCalendar ? [] : result
    return { errors: errors.map(({ code, path }) => ({ code, path })) }
  },
  to_fields: (calendar, d) => dateFieldsToJson(toFields(compiled(calendar), BigInt(str(d, 't')))),
  from_fields: (calendar, d) => {
    const fields = d.fields as Record<string, string>
    const settings = {
      era: d.era as string | undefined,
      regime: d.regime as string | undefined,
      overflow: d.overflow as Overflow,
    }
    return { t: fromFields(compiled(calendar), fields, str(d, 'precision'), settings).toString() }
  },
  unit_bounds: (calendar, d) =>
    bounds(unitBounds(compiled(calendar), BigInt(str(d, 't')), str(d, 'level'))),
  ordinal: (calendar, d) => {
    const found = ordinal(compiled(calendar), BigInt(str(d, 't')), str(d, 'level'))
    return { ordinal: found.value.toString(), intercalary: !found.counted }
  },
  from_ordinal: (calendar, d) =>
    bounds(fromOrdinal(compiled(calendar), str(d, 'level'), BigInt(str(d, 'ordinal')))),
  options: (calendar, d) => {
    const fields = d.fields as Record<string, string>
    return { options: optionsToJson(options(compiled(calendar), fields, str(d, 'level'))) }
  },
  cycle_value: (calendar, d) => {
    const value = cycleValue(compiled(calendar), BigInt(str(d, 't')), str(d, 'cycle'))
    return value === null ? null : { ...value }
  },
  era_of: (calendar, d) => {
    const value = eraOf(compiled(calendar), BigInt(str(d, 't')))
    return value === null ? null : eraValueToJson(value)
  },
  overlay_phase: (calendar, d) =>
    overlayValueToJson(overlayPhase(compiled(calendar), BigInt(str(d, 't')), str(d, 'overlay'))),
  add: (calendar, d) => {
    const overflow = (d.overflow ?? 'constrain') as Overflow
    const t = add(compiled(calendar), BigInt(str(d, 't')), d.duration as Duration, overflow)
    return { t: t.toString() }
  },
  diff: (calendar, d) => {
    const [t1, t2] = [BigInt(str(d, 't1')), BigInt(str(d, 't2'))]
    return differenceToJson(diff(compiled(calendar), t1, t2, str(d, 'largest'), str(d, 'smallest')))
  },
  format: (calendar, d) => {
    const approximate = d.approximate as boolean
    const t = BigInt(str(d, 't'))
    return { text: formatDate(compiled(calendar), t, str(d, 'precision'), { approximate }) }
  },
  format_span: (calendar, d) => ({
    text: formatSpan(compiled(calendar), displayPoint(d.start), displayPoint(d.end)),
  }),
  format_absolute: (_, d) => {
    const display = d.display ?? null
    const approximate = (d.approximate ?? false) as boolean
    const text = formatAbsolute(BigInt(str(d, 't')), d.base_unit as BaseUnit, display, {
      approximate,
    })
    return { text }
  },
  preset_instantiate: (_, d) => {
    const preset = PRESETS.get(str(d, 'preset'))
    if (preset === undefined) throw new Error(`no preset ${str(d, 'preset')}`)
    const origin = BigInt((d.origin ?? '0') as string)
    return { definition: instantiatePreset(preset, rat(d.seconds_per_base_unit), { origin }) }
  },
  next_phase_at: (calendar, d) => {
    const t = nextPhaseAt(compiled(calendar), BigInt(str(d, 't')), str(d, 'overlay'), rat(d.phase))
    return { t: t.toString() }
  },
  expand: (calendar, d) => {
    const [rule, ctx] = recurrence(calendar, d)
    return expansionToJson(expand(rule, ctx, windowOf(d), d.max_items as number))
  },
  series_bounds: (calendar, d) => seriesBoundsToJson(seriesBounds(...recurrence(calendar, d))),
  occurrence: (calendar, d) =>
    occurrenceToJson(occurrence(...recurrence(calendar, d), str(d, 'key'))),
  count_in_window: (calendar, d) => {
    const found = countInWindow(...recurrence(calendar, d), windowOf(d))
    return { count: found.count.toString(), exact: found.exact }
  },
  occurrence_number: (calendar, d) => ({
    number: occurrenceNumber(...recurrence(calendar, d), str(d, 'key')).toString(),
  }),
  occurrence_at: (calendar, d) => ({
    key: occurrenceAt(...recurrence(calendar, d), BigInt(str(d, 't'))),
  }),
  map: (_, d) => {
    const found = correspondence(d.correspondence)
    const t = BigInt(str(d, 't'))
    return momentOrNull(found.map(t, d.direction as Direction, BigInt(str(d, 'target_duration'))))
  },
  compose: (_, d) => {
    const path = (d.path as Json[]).map((step): Step => ({
      correspondence: correspondence(step.correspondence),
      direction: step.direction as Direction,
      targetDuration: BigInt(str(step, 'target_duration')),
    }))
    return momentOrNull(compose(path, BigInt(str(d, 't'))))
  },
}

/**
 * Run `op` with the case's calendar: the result, `{error: code}` for an engine error, or
 * NotImplementedError for an op without a handler. Calendars are compiled once per object.
 */
export function runOp(
  op: Op,
  calendar: CalendarDocument | null,
  input: Record<string, unknown>,
): unknown {
  const handler = HANDLERS[op]
  if (handler === undefined) throw new NotImplementedError(op)
  try {
    return handler(calendar, input)
  } catch (error) {
    if (
      error instanceof NumberError ||
      error instanceof DateError ||
      error instanceof RecurrenceError ||
      error instanceof PresetError ||
      error instanceof CorrespondenceError
    ) {
      return { error: error.code }
    }
    throw error
  }
}
