// Test helpers: the conformance calendars and JSON-pointer edits of raw documents.
import { readFileSync } from 'node:fs'

import { CompiledCalendar, validateCalendar } from '../src/calendar'

export interface CalendarDocument {
  readonly definition: unknown
  readonly context: unknown
}

/** A calendar file of spec/chronology/conformance/calendars/. */
export function load(name: string): CalendarDocument {
  const url = new URL(
    `../../../spec/chronology/conformance/calendars/${name}.json`,
    import.meta.url,
  )
  return JSON.parse(readFileSync(url, 'utf8')) as CalendarDocument
}

export function compiled(definition: unknown, context: unknown): CompiledCalendar {
  const result = validateCalendar(definition, context)
  if (!(result instanceof CompiledCalendar)) throw new Error(JSON.stringify(result))
  return result
}

/** The validation errors of raw documents as `{code, path}` (without messages). */
export function errorsOf(definition: unknown, context: unknown): { code: string; path: string }[] {
  const result = validateCalendar(definition, context)
  if (result instanceof CompiledCalendar) throw new Error('expected validation errors')
  return result.map(({ code, path }) => ({ code, path }))
}

function parts(pointer: string): string[] {
  return pointer
    .split('/')
    .slice(1)
    .map((part) => part.replace(/~1/g, '/').replace(/~0/g, '~'))
}

type Container = Record<string, unknown> & unknown[]

function walk(document: unknown, keys: readonly string[]): unknown {
  return keys.reduce<unknown>((node, key) => (node as Container)[key as never], document)
}

/** The member of `document` at a JSON pointer. */
export function at(document: unknown, pointer: string): unknown {
  return walk(document, parts(pointer))
}

/** A deep copy of `document` with values set at JSON pointers (`/-` appends to an array). */
export function patched<T>(document: T, patches: Readonly<Record<string, unknown>>): T {
  const copy = structuredClone(document)
  for (const [pointer, value] of Object.entries(patches)) {
    const path = parts(pointer)
    const key = path.at(-1) ?? ''
    const container = walk(copy, path.slice(0, -1)) as Container
    if (Array.isArray(container) && key === '-') container.push(value)
    else (container as Record<string, unknown>)[key] = value
  }
  return copy
}
