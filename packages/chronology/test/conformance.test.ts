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

import {
  CompiledCalendar,
  DateError,
  dateFieldsToJson,
  fromFields,
  type Overflow,
  toFields,
  validateCalendar,
} from '../src/calendar'
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
    const options = { regime: d.regime as string | undefined, overflow: d.overflow as Overflow }
    return { t: fromFields(compiled(calendar), fields, str(d, 'precision'), options).toString() }
  },
}

/** op → issue that implements it in the TypeScript engine. */
const PENDING: Partial<Record<Op, number>> = {
  unit_bounds: 24,
  ordinal: 24,
  from_ordinal: 24,
  options: 24,
  cycle_value: 24,
  era_of: 24,
  overlay_phase: 24,
  next_phase_at: 24,
  add: 25,
  diff: 25,
  format: 25,
  format_span: 25,
  format_absolute: 25,
  preset_instantiate: 25,
  expand: 26,
  series_bounds: 26,
  occurrence: 26,
  count_in_window: 26,
  occurrence_number: 26,
  occurrence_at: 26,
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
    if (error instanceof NumberError || error instanceof DateError) return { error: error.code }
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

interface DefinitionShape {
  regimes?: { cycles?: unknown[] }[]
  eras?: unknown[]
  overlays?: unknown[]
}

function definitionOf(calendarName: string | null): DefinitionShape {
  if (calendarName === null) return {}
  return CALENDARS.get(calendarName)?.definition ?? {}
}

/** Whether a calendar file defines parallel cycles in any regime. */
function hasCycles(calendarName: string | null): boolean {
  return (definitionOf(calendarName).regimes ?? []).some(
    (regime) => (regime.cycles ?? []).length > 0,
  )
}

function hasOverlays(calendarName: string | null): boolean {
  return (definitionOf(calendarName).overlays ?? []).length > 0
}

function hasEras(calendarName: string | null): boolean {
  return (definitionOf(calendarName).eras ?? []).length > 0
}

/** Cases that need eras, era input or local anchors (era and regime starts) in this engine. */
const ERAS_AND_LOCAL_ANCHORS = new Set([
  'eras/astronomical::from-fields-era-without-eras',
  ...[
    'showa-64-jan-7',
    'showa-64-jan-8',
    'heisei-1-jan-8',
    'heisei-1-jan-7',
    'heisei-31-apr-30',
    'heisei-31-may-1',
    'reiwa-1-may-1',
    'reiwa-1-apr-30',
    'reiwa-1-year',
    'heisei-1-january',
    'before-1-dec-24',
    'before-1-dec-25',
    'reiwa-0',
    'showa-1-year',
    'reiwa-1-may',
    'heisei-31-year',
  ].map((id) => `eras/japanese-eras::from-fields-${id}`),
  ...[
    'reform-day',
    'reform-gap',
    'late-1582',
    'bc-1',
    'bc-2',
    'ides-of-march-bc',
    'ad-2024',
    'ad-0',
    'bc-0',
    'unknown-era',
    'era-year-slot-id',
  ].map((id) => `regimes/julian-gregorian::from-fields-${id}`),
  ...[
    'regime-local-not-increasing',
    'regime-local-invalid-date',
    'era-local-invalid-date',
    'era-local-precision',
    'era-local-unknown-regime',
    'era-local-not-increasing',
  ].map((id) => `validate/error-codes::${id}`),
])

/**
 * Cases of implemented ops that need a feature this engine doesn't have yet → issue. They run
 * normally and must still fail (`test.fails`); once the feature lands they pass, which breaks the
 * run until the rule is removed (README "Runners and pending ops").
 */
const PENDING_CASES: {
  issue: number
  applies: (file: string, calendar: string | null, vector: Case) => boolean
}[] = [
  // to_fields' `cycles`, `era` and `overlays` members.
  {
    issue: 24,
    applies: (_, c, v) => v.op === 'to_fields' && (hasCycles(c) || hasEras(c) || hasOverlays(c)),
  },
  { issue: 24, applies: (file, _, v) => ERAS_AND_LOCAL_ANCHORS.has(`${file}::${v.id}`) },
]

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
