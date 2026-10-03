// chrono-exec: runs conformance ops against the TypeScript engine for differential testing
// (backend/tests/chronology/differential/, docs/architecture/testing.md §6).
//
// Reads JSON lines from stdin, one op each, in the shape of a conformance case plus its calendar:
//   {"op": "<op>", "calendar": {"definition": …, "context": …} | null, "input": {…}}
// and writes one JSON line per op to stdout, in order:
//   {"result": <the README's result shape, or {"error": "<code>"}>}  or  {"crash": "<message>"}
// A crash is anything but an engine error (a bug, or an op this engine doesn't implement).
//
// Node can't run the engine source directly (extensionless imports), so the CLI is bundled first:
//   npm run build:exec -w @lore/chronology     → packages/chronology/dist/chrono-exec.mjs
//   node packages/chronology/dist/chrono-exec.mjs < ops.jsonl
import { createInterface } from 'node:readline'

import { type CalendarDocument, type Op, runOp } from './ops'

interface Request {
  op: Op
  calendar: CalendarDocument | null
  input: Record<string, unknown>
}

/** Requests in a batch usually share their calendar: reuse the parsed document so that it's
 * compiled once (`runOp` caches compiled calendars per document object). */
const CALENDARS = new Map<string, CalendarDocument>()
const MAX_CALENDARS = 64

function calendarOf(request: Request): CalendarDocument | null {
  if (request.calendar === null) return null
  const key = JSON.stringify(request.calendar)
  let calendar = CALENDARS.get(key)
  if (calendar === undefined) {
    if (CALENDARS.size >= MAX_CALENDARS) CALENDARS.clear()
    calendar = request.calendar
    CALENDARS.set(key, calendar)
  }
  return calendar
}

function execute(line: string): string {
  try {
    const request = JSON.parse(line) as Request
    const result = runOp(request.op, calendarOf(request), request.input)
    return JSON.stringify({ result })
  } catch (error) {
    const message = error instanceof Error ? `${error.name}: ${error.message}` : String(error)
    return JSON.stringify({ crash: message })
  }
}

const lines = createInterface({ input: process.stdin, crlfDelay: Infinity })
for await (const line of lines) {
  if (line.trim() === '') continue
  process.stdout.write(execute(line) + '\n')
}
