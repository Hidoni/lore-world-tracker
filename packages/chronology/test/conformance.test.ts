// Conformance runner: every vector in spec/chronology/conformance/ against the TypeScript engine.
//
// The format and the ops are documented in spec/chronology/conformance/README.md. Ops that this
// engine doesn't implement yet are listed in PENDING with the issue that implements them. Their
// cases must fail with NotImplementedError (`test.fails`), so implementing an op means adding its
// handler to HANDLERS and removing it from PENDING.
import { readdirSync, readFileSync, statSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, test } from 'vitest'

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

const CONFORMANCE_DIR = fileURLToPath(
  new URL('../../../spec/chronology/conformance', import.meta.url),
)

const NUMBER_OPS = [
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
const OPS = [
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
type Op = (typeof OPS)[number]

const CALENDAR_FREE_OPS: readonly Op[] = [
  ...NUMBER_OPS,
  'validate',
  'format_absolute',
  'preset_instantiate',
  'map',
  'compose',
]
const RECURRENCE_OPS: readonly Op[] = [
  'expand',
  'series_bounds',
  'occurrence',
  'count_in_window',
  'occurrence_number',
  'occurrence_at',
]

interface CalendarFile {
  description: string
  definition: unknown
  context: unknown
}

interface CaseFile {
  description: string
  calendar: string | null
  generated: boolean
  verification: string
  cases: Case[]
}

interface Case {
  id: string
  op: Op
  input: Record<string, unknown>
  expected: unknown
  note?: string
}

type Handler = (calendar: CalendarFile | null, input: Record<string, unknown>) => unknown

class NotImplementedError extends Error {
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

const COMPILED = new Map<CalendarFile, CompiledCalendar>()

function compiled(calendar: CalendarFile | null): CompiledCalendar {
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
  calendar: CalendarFile | null,
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

/** op → engine call returning the result in the README's JSON shape (errors as `{error}`). */
// Inputs named n/a/b are deliberately parsed without validation (they may be out of range).
const HANDLERS: Partial<Record<Op, Handler>> = {
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
}

/** op → issue that implements it in the TypeScript engine. */
const PENDING: Partial<Record<Op, number>> = {
  map: 27,
  compose: 27,
}

function readJson(file: string): unknown {
  return JSON.parse(readFileSync(file, 'utf8'))
}

function listFiles(dir: string): string[] {
  return readdirSync(dir)
    .map((name) => path.join(dir, name))
    .flatMap((file) => (statSync(file).isDirectory() ? listFiles(file) : [file]))
    .sort()
}

const calendarFiles = listFiles(path.join(CONFORMANCE_DIR, 'calendars')).filter((file) =>
  file.endsWith('.json'),
)
const CALENDARS = new Map(
  calendarFiles.map((file) => [path.basename(file, '.json'), readJson(file) as CalendarFile]),
)

const casesDir = path.join(CONFORMANCE_DIR, 'cases')
const CASE_FILES = listFiles(casesDir)
  .filter((file) => file.endsWith('.json'))
  .map((file) => ({
    name: path
      .relative(casesDir, file)
      .replace(/\\/g, '/')
      .replace(/\.json$/, ''),
    document: readJson(file) as CaseFile,
  }))

function run(op: Op, calendarName: string | null, input: Record<string, unknown>): unknown {
  const handler = HANDLERS[op]
  if (handler === undefined) throw new NotImplementedError(op)
  const calendar = calendarName === null ? null : (CALENDARS.get(calendarName) ?? null)
  try {
    return handler(calendar, input)
  } catch (error) {
    if (
      error instanceof NumberError ||
      error instanceof DateError ||
      error instanceof RecurrenceError ||
      error instanceof PresetError
    ) {
      return { error: error.code }
    }
    throw error
  }
}

interface ErrorItem {
  code: string
  path: string
}

/** `validate` errors compare as a set of (code, path) pairs (README). */
function normalized(op: Op, value: unknown): unknown {
  const errors = (value as { errors?: unknown } | null)?.errors
  if (op !== 'validate' || !Array.isArray(errors)) return value
  const key = (e: ErrorItem): string => `${e.path}\u0000${e.code}`
  return { errors: [...(errors as ErrorItem[])].sort((a, b) => (key(a) < key(b) ? -1 : 1)) }
}

/**
 * Cases of implemented ops that need a feature this engine doesn't have yet → issue. They run
 * normally and must still fail (`test.fails`); once the feature lands they pass, which breaks the
 * run until the rule is removed (README "Runners and pending ops").
 */
const PENDING_CASES: {
  issue: number
  applies: (file: string, calendar: string | null, vector: Case) => boolean
}[] = []

describe.each(CASE_FILES)('$name', ({ name, document }) => {
  for (const vector of document.cases) {
    const issue = PENDING[vector.op]
    const pendingCase = PENDING_CASES.find((rule) => rule.applies(name, document.calendar, vector))
    const check = () => {
      const result = run(vector.op, document.calendar, vector.input)
      expect(normalized(vector.op, result)).toStrictEqual(normalized(vector.op, vector.expected))
    }
    if (issue !== undefined) {
      // Strict expected failure: only NotImplementedError counts. A result (right or wrong) or
      // any other error means the op was implemented without being removed from PENDING.
      test.fails(`${name}::${vector.id} [pending #${issue}]`, () => {
        try {
          run(vector.op, document.calendar, vector.input)
        } catch (error) {
          if (error instanceof NotImplementedError) throw error
        }
      })
    } else if (pendingCase !== undefined) {
      test.fails(`${name}::${vector.id} [pending #${pendingCase.issue}]`, check)
    } else {
      test(`${name}::${vector.id}`, check)
    }
  }
})

// --- suite integrity -----------------------------------------------------------------------------

describe('conformance suite', () => {
  test('every op is handled or pending, not both', () => {
    for (const op of OPS) {
      expect([op, HANDLERS[op] !== undefined || PENDING[op] !== undefined]).toEqual([op, true])
      expect([op, HANDLERS[op] !== undefined && PENDING[op] !== undefined]).toEqual([op, false])
    }
    expect(Object.keys(PENDING).every((op) => (OPS as readonly string[]).includes(op))).toBe(true)
  })

  test('vectors are discovered', () => {
    expect(CASE_FILES.length).toBeGreaterThan(0)
    expect(CALENDARS.size).toBeGreaterThan(0)
  })

  test('no stray files', () => {
    for (const file of listFiles(CONFORMANCE_DIR)) {
      const relative = path.relative(CONFORMANCE_DIR, file).replace(/\\/g, '/')
      if (relative === 'README.md') continue
      expect(relative).toMatch(/^(calendars\/[^/]+|cases\/.+)\.json$/)
    }
  })

  test.each([...CALENDARS])('calendar %s has the calendar-file shape', (_, calendar) => {
    expect(Object.keys(calendar).sort()).toEqual(['context', 'definition', 'description'])
  })

  test.each(CASE_FILES)('case file $name has the case-file shape', ({ document }) => {
    expect(Object.keys(document).sort()).toEqual([
      'calendar',
      'cases',
      'description',
      'generated',
      'verification',
    ])
    expect(typeof document.generated).toBe('boolean')
    if (document.calendar !== null) expect(CALENDARS.has(document.calendar)).toBe(true)
    const ids = document.cases.map((vector) => vector.id)
    expect(new Set(ids).size).toBe(ids.length)
    for (const vector of document.cases) {
      const keys = Object.keys(vector).filter((key) => key !== 'note')
      expect(keys.sort()).toEqual(['expected', 'id', 'input', 'op'])
      expect(vector.id).toMatch(/^[a-z0-9]+(-[a-z0-9]+)*$/)
      expect(OPS).toContain(vector.op)
      if (document.calendar === null) {
        expect([...CALENDAR_FREE_OPS, ...RECURRENCE_OPS]).toContain(vector.op)
      }
    }
  })
})
