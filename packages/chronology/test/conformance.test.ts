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

const CONFORMANCE_DIR = fileURLToPath(
  new URL('../../../spec/chronology/conformance', import.meta.url),
)

/** Every op documented in the conformance README. */
const OPS = [
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
  'add',
  'diff',
  'format',
  'format_span',
  'preset_instantiate',
  'expand',
  'series_bounds',
  'occurrence',
  'count_in_window',
  'map',
] as const
type Op = (typeof OPS)[number]

const CALENDAR_FREE_OPS: readonly Op[] = ['validate', 'preset_instantiate', 'map']
const RECURRENCE_OPS: readonly Op[] = ['expand', 'series_bounds', 'occurrence', 'count_in_window']

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

/** op → engine call returning the result in the README's JSON shape (errors as `{error}`). */
const HANDLERS: Partial<Record<Op, Handler>> = {}

/** op → issue that implements it in the TypeScript engine. */
const PENDING: Partial<Record<Op, number>> = {
  validate: 23,
  to_fields: 23,
  from_fields: 23,
  unit_bounds: 24,
  ordinal: 24,
  from_ordinal: 24,
  options: 24,
  cycle_value: 24,
  era_of: 24,
  overlay_phase: 24,
  add: 25,
  diff: 25,
  format: 25,
  format_span: 25,
  preset_instantiate: 25,
  expand: 26,
  series_bounds: 26,
  occurrence: 26,
  count_in_window: 26,
  map: 27,
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
  return handler(calendar, input)
}

describe.each(CASE_FILES)('$name', ({ name, document }) => {
  for (const vector of document.cases) {
    const issue = PENDING[vector.op]
    if (issue === undefined) {
      test(`${name}::${vector.id}`, () => {
        expect(run(vector.op, document.calendar, vector.input)).toStrictEqual(vector.expected)
      })
    } else {
      // Strict expected failure: only NotImplementedError counts. A result (right or wrong) or
      // any other error means the op was implemented without being removed from PENDING.
      test.fails(`${name}::${vector.id} [pending #${issue}]`, () => {
        try {
          run(vector.op, document.calendar, vector.input)
        } catch (error) {
          if (error instanceof NotImplementedError) throw error
        }
      })
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
