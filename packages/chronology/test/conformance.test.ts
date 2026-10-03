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
  CALENDAR_FREE_OPS,
  type CalendarDocument,
  HANDLERS,
  NotImplementedError,
  type Op,
  OPS,
  RECURRENCE_OPS,
  runOp,
} from '../bin/ops'

const CONFORMANCE_DIR = fileURLToPath(
  new URL('../../../spec/chronology/conformance', import.meta.url),
)

interface CalendarFile extends CalendarDocument {
  description: string
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

/** op → issue that implements it in the TypeScript engine. */
const PENDING: Partial<Record<Op, number>> = {}

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
  const calendar = calendarName === null ? null : (CALENDARS.get(calendarName) ?? null)
  return runOp(op, calendar, input)
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
