import { z } from 'zod'

/**
 * URL search params (frontend.md §4). Values stay strings: TanStack Router's default parser turns
 * `?at=123` into a number (and long digit strings into lossy floats), but moments are exact
 * integers carried as decimal strings (CLAUDE.md rule 1). Only JSON arrays and objects (filters),
 * and strings quoted because they look like those, are parsed.
 */
const STRUCTURED = /^[[{"]/

function parseValue(value: string): unknown {
  if (STRUCTURED.test(value)) {
    try {
      return JSON.parse(value) as unknown
    } catch {
      // Not JSON after all: keep the text.
    }
  }
  return value
}

export function parseSearch(searchStr: string): Record<string, unknown> {
  const search: Record<string, unknown> = {}
  for (const [key, value] of new URLSearchParams(searchStr)) search[key] = parseValue(value)
  return search
}

function stringifyValue(value: unknown): string {
  if (typeof value === 'string') {
    // A string that would parse as JSON is quoted so it reads back as the same string.
    return STRUCTURED.test(value) && parseValue(value) !== value ? JSON.stringify(value) : value
  }
  if (typeof value === 'object') return JSON.stringify(value)
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint') {
    return String(value)
  }
  return ''
}

export function stringifySearch(search: Record<string, unknown>): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(search)) {
    if (value !== undefined && value !== null) params.set(key, stringifyValue(value))
  }
  const text = params.toString()
  return text ? `?${text}` : ''
}

/** A moment as a non-negative decimal string (never a number). */
const momentString = z.string().regex(/^(0|[1-9][0-9]*)$/)

/**
 * Global search params on every route: `tl` (timeline id), `at` (`present`, `all` or a moment)
 * and `cal` (display calendar id). Invalid values are dropped rather than failing the route.
 */
export const globalSearchSchema = z.object({
  tl: z.string().min(1).optional().catch(undefined),
  at: z
    .union([z.literal('present'), z.literal('all'), momentString])
    .optional()
    .catch(undefined),
  cal: z.string().min(1).optional().catch(undefined),
})

export type GlobalSearch = z.infer<typeof globalSearchSchema>
