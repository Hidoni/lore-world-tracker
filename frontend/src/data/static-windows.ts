import {
  type CalendarDefinition,
  type CompileContext,
  type CompiledCalendar,
  compileCalendar,
  countInWindow,
  type EndSpec,
  expand,
  type Occurrence,
  occurrenceNumber,
  type RecurrenceContext,
  RecurrenceError,
  type RecurrenceRule,
} from '@lore/chronology'

import type { components } from '@/api'

import { NotInExport, StaticProblem, type Handler, type Load } from './static-core'
import { replay, type Refused } from './static-time'

/**
 * Timeline windows and series occurrences of a static export (#375, ADR 0016). A window has a free
 * range and pixel budget, so it is computed here the way the server computes it
 * (`lore/core/time/window.py`, `series.py` `occurrences`), from the rows the builder exports
 * (`lore/static_export/windows.py`). Series are expanded with `@lore/chronology`, the engine with
 * the server's semantics (chronology-engine.md, recurrence.md). The parity tests compare both.
 */

type Schemas = components['schemas']
type Item = Schemas['WindowItemOut']

const MAX_ITEMS = 2000
const PX_PER_BUCKET = 4
const CANCELLED = 'cancelled'

/** A row of the timeline's view (one of a root's candidates, nearest timeline first). */
interface Candidate {
  id: string
  start: string | null
  end: string | null
  importance: number
  category: string | null
  recurs: boolean
  cancelled: boolean
  item: Item
}

interface Materialized {
  key: string | null
  timeline: string
  start: string | null
  end: string | null
  entity_id: string
  state: string | null
}

/** A series row: its rule and what the engine needs besides it. */
interface SeriesRow {
  rule: RecurrenceRule
  series_start: string
  end: EndSpec
  resolved: Record<string, string>
  calendar: string | null
  duration: string
  bounds: [string | null, string | null]
  /** Keys of its materialized occurrences in the timeline's lineage (windows). */
  own: string[]
  materialized: Materialized[]
  /** The row's timeline (occurrences). */
  timeline?: string
}

interface WindowFile {
  has_series: boolean
  roots: Candidate[][]
  series: Record<string, SeriesRow>
}

interface EventFilters {
  tags: string[]
  participants: string[]
  kinds: string[]
  ancestors: string[]
}

interface SeriesFile {
  rows: Record<string, SeriesRow>
  timelines: Record<string, string | Refused>
}

interface IndexFile {
  entities: Record<string, { summary: { kind: string } }>
  timelines: Record<string, unknown>
}

interface CalendarFile {
  definition: CalendarDefinition
  context: CompileContext
}

/** A window row: an event row or a computed occurrence (`<row id>:<key>`). */
interface Row {
  id: string
  start: bigint
  end: bigint
  importance: number
  item: Item
}

const cmp = (a: bigint, b: bigint): number => (a < b ? -1 : a > b ? 1 : 0)
const text = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0)
const max = (a: bigint, b: bigint): bigint => (a > b ? a : b)
const min = (a: bigint, b: bigint): bigint => (a < b ? a : b)

function notFound(detail: string): StaticProblem {
  return new StaticProblem(404, 'not_found', 'Not found', detail)
}

function emptyWindow(): StaticProblem {
  const message = 'The window must end after it starts.'
  return new StaticProblem(422, 'validation_error', 'Validation error', message, [
    { path: 'to', code: 'invalid_value', message },
  ])
}

function flag(params: URLSearchParams, name: string, fallback: boolean): boolean {
  const value = params.get(name)
  return value === null ? fallback : value === 'true' || value === '1'
}

/** `time-model.md` §2.1 overlap of a span (or instant) and `[w0, w1)`. */
function overlaps(start: bigint, end: bigint, w0: bigint, w1: bigint): boolean {
  return start === end ? w0 <= start && start < w1 : start < w1 && w0 < end
}

/** The first moment index at or after `key` (`bisect_left`). */
function bisectLeft(sorted: readonly bigint[], key: bigint): number {
  let lo = 0
  let hi = sorted.length
  while (lo < hi) {
    const mid = (lo + hi) >> 1
    if ((sorted[mid] ?? 0n) < key) lo = mid + 1
    else hi = mid
  }
  return lo
}

/** The first moment index after `key` (`bisect_right`). */
function bisectRight(sorted: readonly bigint[], key: bigint): number {
  let lo = 0
  let hi = sorted.length
  while (lo < hi) {
    const mid = (lo + hi) >> 1
    if ((sorted[mid] ?? 0n) <= key) lo = mid + 1
    else hi = mid
  }
  return lo
}

const CALENDARS = new WeakMap<CalendarFile, CompiledCalendar | null>()

function compiled(file: CalendarFile): CompiledCalendar | null {
  let found = CALENDARS.get(file)
  if (found === undefined) {
    const result = compileCalendar(file.definition, file.context)
    found = Array.isArray(result) ? null : result
    CALENDARS.set(file, found)
  }
  return found
}

/** The engine's context of a series row (`null`: its calendar doesn't compile here). */
async function contextOf(
  load: Load,
  vault: string,
  row: SeriesRow,
): Promise<RecurrenceContext | null> {
  let calendar: CompiledCalendar | null = null
  if (row.calendar !== null) {
    const calendars = (await load(`vaults/${vault}/static/calendars`)) as Record<
      string,
      CalendarFile
    >
    const file = calendars[row.calendar]
    calendar = file === undefined ? null : compiled(file)
    if (calendar === null) return null
  }
  return {
    seriesStart: BigInt(row.series_start),
    end: row.end,
    dimensionDuration: BigInt(row.duration),
    calendar,
    resolved: Object.fromEntries(
      Object.entries(row.resolved).map(([pointer, t]) => [pointer, BigInt(t)]),
    ),
  }
}

/** A series' occurrences in the window, or the count of a truncated expansion (`window.py`
 * `_occurrences_in`); `null` when the rule doesn't evaluate. */
function occurrencesIn(
  row: SeriesRow,
  ctx: RecurrenceContext,
  window: readonly [bigint, bigint],
  limit: number,
): readonly Occurrence[] | bigint | null {
  try {
    const counted = countInWindow(row.rule, ctx, window)
    if (counted.exact && counted.count > BigInt(limit)) return counted.count
    const expansion = expand(row.rule, ctx, window, limit)
    if (expansion.truncated) return expansion.estimatedCount ?? 0n
    return expansion.items
  } catch (error) {
    if (error instanceof RecurrenceError) return null
    throw error
  }
}

/** LOD: the `keep` rows ranked first by importance, then duration (longest first), start, id. */
function keepOf(rows: readonly Row[], keep: number): Set<string> {
  const tiers = new Map<number, Row[]>()
  for (const row of rows) {
    const tier = tiers.get(row.importance)
    if (tier) tier.push(row)
    else tiers.set(row.importance, [row])
  }
  const kept = new Set<string>()
  for (const importance of [...tiers.keys()].sort((a, b) => b - a)) {
    const tier = tiers.get(importance) ?? []
    const room = keep - kept.size
    if (room <= 0) break
    if (tier.length <= room) {
      for (const row of tier) kept.add(row.id)
      continue
    }
    const ranked = [...tier].sort(
      (a, b) => cmp(a.start - a.end, b.start - b.end) || cmp(a.start, b.start) || text(a.id, b.id),
    )
    for (const row of ranked.slice(0, room)) kept.add(row.id)
  }
  return kept
}

/** `window.py` `bucket_bounds`: the `n + 1` boundaries of `n` equal buckets. */
function bucketBounds(start: bigint, end: bigint, px: number): bigint[] {
  const width = end - start
  const count = max(1n, min(BigInt(Math.floor(px / PX_PER_BUCKET)), width))
  const bounds: bigint[] = []
  for (let i = 0n; i <= count; i++) bounds.push(start + (i * width) / count)
  return bounds
}

function bucketsOf(culled: readonly Row[], start: bigint, end: bigint, px: number) {
  const bounds = bucketBounds(start, end, px)
  const sorted = (values: bigint[]) => values.sort(cmp)
  const starts = sorted(culled.map((row) => row.start))
  const spanEnds = sorted(culled.filter((row) => row.start !== row.end).map((row) => row.end))
  const instants = sorted(culled.filter((row) => row.start === row.end).map((row) => row.start))
  const before = bounds.map((bound) => bisectLeft(starts, bound))
  before[0] = 0
  before[before.length - 1] = starts.length
  const buckets = []
  for (let i = 0; i < bounds.length - 1; i++) {
    const lo = bounds[i] ?? 0n
    const next = before[i + 1] ?? 0
    const count = next - (before[i] ?? 0)
    const ended = i ? bisectRight(spanEnds, lo) + bisectLeft(instants, lo) : 0
    const active = next - ended
    if (count || active) {
      buckets.push({ from: String(lo), to: String(bounds[i + 1] ?? 0n), starts: count, active })
    }
  }
  return buckets
}

/** `window.py` `_order`: by start, the later end first, row id, occurrence key. */
function itemOrder(a: Item, b: Item): number {
  const key = (item: Item) => {
    const [head = '', tail = ''] = (item.occurrence_key ?? '').split('.', 2)
    return [head === '' ? -1n : BigInt(head), tail] as const
  }
  const [aHead, aTail] = key(a)
  const [bHead, bTail] = key(b)
  return (
    cmp(BigInt(a.start_t ?? -1), BigInt(b.start_t ?? -1)) ||
    cmp(BigInt(b.end_t ?? -1), BigInt(a.end_t ?? -1)) ||
    text(a.row_id, b.row_id) ||
    cmp(aHead, bHead) ||
    text(aTail, bTail)
  )
}

const timelineWindow: Handler = async (load, _route, params, [vault = '', timeline = '']) => {
  const index = (await load(`vaults/${vault}/static/index`)) as IndexFile
  if (!(timeline in index.timelines)) throw notFound(`No entity ${timeline}.`)
  const parent = params.get('parent')
  if (parent !== null) {
    const kind = index.entities[parent]?.summary.kind
    if (kind === undefined) throw notFound(`No entity ${parent}.`)
    if (kind !== 'event') throw notFound(`No event ${parent}.`)
  }
  const w0 = BigInt(params.get('from') ?? '0')
  const w1 = BigInt(params.get('to') ?? '0')
  if (w0 >= w1) throw emptyWindow()
  const px = Number(params.get('px') ?? '1')
  const minImportance = params.get('min_importance')
  const categories = params.getAll('category')
  const tags = params.getAll('tag')
  const participants = params.getAll('participant')
  const participantKinds = params.getAll('participant_kind')
  const includeSeries = flag(params, 'include_series', true)
  const includeCancelled = flag(params, 'include_cancelled', false)
  const file = (await load(`vaults/${vault}/static/windows/${timeline}`)) as WindowFile
  const filters = (await load(`vaults/${vault}/static/events`)) as Record<string, EventFilters>

  const passes = (row: Candidate): boolean => {
    const found = filters[row.item.entity_id]
    if (minImportance !== null && row.importance < Number(minImportance)) return false
    if (categories.length && (row.category === null || !categories.includes(row.category))) {
      return false
    }
    if (!found) return tags.length + participants.length + participantKinds.length === 0
    if (!tags.every((tag) => found.tags.includes(tag))) return false
    if (participants.length && !participants.some((p) => found.participants.includes(p))) {
      return false
    }
    if (participantKinds.length && !participantKinds.some((k) => found.kinds.includes(k))) {
      return false
    }
    return parent === null || found.ancestors.includes(parent)
  }

  const rows: Row[] = []
  for (const candidates of file.roots) {
    // The window's start bound applies before resolution (`TimelineView.select`).
    const row = candidates.find((c) => c.start !== null && BigInt(c.start) < w1)
    if (row?.start == null || row.end === null) continue
    const start = BigInt(row.start)
    const end = BigInt(row.end)
    if (!(start < w1 && (end > w0 || (end === w0 && start === w0)))) continue
    if (row.recurs || (!includeCancelled && row.cancelled) || !passes(row)) continue
    rows.push({ id: row.id, start, end, importance: row.importance, item: row.item })
  }
  const limit = Math.min(px, MAX_ITEMS)
  const bands: Schemas['SeriesBandOut'][] = []
  if (includeSeries && file.has_series) {
    for (const candidates of file.roots) {
      const row = candidates.find((c) => c.recurs)
      const series = row && file.series[row.id]
      if (row === undefined || series === undefined) continue
      const [first, last] = series.bounds
      if (first === null || last === null || !(BigInt(first) < w1 && BigInt(last) >= w0)) continue
      if (!passes(row)) continue
      const ctx = await contextOf(load, vault, series)
      if (ctx === null) continue
      const found = occurrencesIn(series, ctx, [w0, w1], limit)
      if (found === null) continue
      if (typeof found === 'bigint') {
        bands.push({
          entity_id: row.item.entity_id,
          row_id: row.id,
          name: row.item.name,
          visibility: row.item.visibility,
          importance: row.importance,
          category: row.category,
          from: String(max(w0, BigInt(first))) as Schemas['SeriesBandOut']['from'],
          to: String(min(w1, BigInt(last))) as Schemas['SeriesBandOut']['to'],
          estimated_count: String(found) as Schemas['SeriesBandOut']['estimated_count'],
        })
        continue
      }
      const own = new Set(series.own)
      for (const occurrence of found) {
        if (own.has(occurrence.key)) continue
        rows.push({
          id: `${row.id}:${occurrence.key}`,
          start: occurrence.start,
          end: occurrence.end,
          importance: row.importance,
          item: {
            ...row.item,
            start_t: String(occurrence.start) as Item['start_t'],
            end_t: String(occurrence.end) as Item['end_t'],
            occurrence_key: occurrence.key,
            series_id: row.item.entity_id,
            // An occurrence is at its own moment, without the start's range (`window.py`).
            start_extent: null,
            end_extent: null,
          },
        })
      }
    }
    bands.sort((a, b) => cmp(BigInt(a.from), BigInt(b.from)) || text(a.row_id, b.row_id))
  }

  const kept = keepOf(rows, limit)
  const culled = rows.filter((row) => !kept.has(row.id))
  return {
    items: rows
      .filter((row) => kept.has(row.id))
      .map((row) => row.item)
      .sort(itemOrder),
    buckets: bucketsOf(culled, w0, w1, px),
    series_bands: bands,
    total: rows.length,
    culled: culled.length,
  }
}

/** `series.py` `occurrences`: `expand`, merged with the materialized occurrences (§7). */
const occurrences: Handler = async (load, _route, params, [vault = '', event = '']) => {
  let file: SeriesFile
  try {
    file = (await load(`vaults/${vault}/static/series/${event}`)) as SeriesFile
  } catch (error) {
    if (!(error instanceof NotInExport)) throw error
    const index = (await load(`vaults/${vault}/static/index`)) as IndexFile
    const kind = index.entities[event]?.summary.kind
    if (kind === undefined) throw notFound(`No entity ${event}.`)
    if (kind !== 'event') throw notFound(`No event ${event}.`)
    throw new StaticProblem(
      409,
      'not_a_series',
      'Not a recurring event',
      "The event doesn't recur.",
    )
  }
  const timeline = params.get('timeline') ?? ''
  const found = file.timelines[timeline]
  if (found === undefined) throw notFound(`No entity ${timeline}.`)
  const row = typeof found === 'string' ? file.rows[found] : replay(found, 'occurrences')
  if (row === undefined || !('rule' in row)) throw notFound(`No event ${event}.`)
  const w0 = BigInt(params.get('from') ?? '0')
  const w1 = BigInt(params.get('to') ?? '0')
  if (w0 >= w1) throw emptyWindow()
  const limit = Number(params.get('limit') ?? '100')
  const includeCancelled = flag(params, 'include_cancelled', false)
  const conflict = (error: unknown) =>
    new StaticProblem(
      409,
      'conflict',
      'Conflict',
      `The recurrence rule can't be evaluated: ${error instanceof Error ? error.message : ''}`,
    )
  const ctx = await contextOf(load, vault, row)
  if (ctx === null) throw conflict(new Error("the rule's calendar doesn't compile"))
  let expansion
  try {
    expansion = expand(row.rule, ctx, [w0, w1], limit)
  } catch (error) {
    if (error instanceof RecurrenceError) throw conflict(error)
    throw error
  }
  if (expansion.truncated) {
    return { items: [], truncated: true, estimated_count: String(expansion.estimatedCount) }
  }
  const listed = new Map<string, { start: bigint; end: bigint; own: Materialized | null }>()
  for (const item of expansion.items) {
    listed.set(item.key, { start: item.start, end: item.end, own: null })
  }
  const byKey = new Map<string, Materialized>()
  for (const own of row.materialized) {
    if (own.timeline === row.timeline && own.key !== null) byKey.set(own.key, own)
  }
  for (const [key, own] of byKey) {
    if (own.start === null || own.end === null) continue
    const start = BigInt(own.start)
    const end = BigInt(own.end)
    const shown = own.state !== CANCELLED || includeCancelled
    if (shown && overlaps(start, end, w0, w1)) listed.set(key, { start, end, own })
    else listed.delete(key)
  }
  if (listed.size > limit) {
    return { items: [], truncated: true, estimated_count: String(listed.size) }
  }
  const keyOrder = (key: string) => {
    const [head = '0', tail] = key.split('.', 2)
    return [BigInt(head), tail === undefined ? -1n : BigInt(tail)] as const
  }
  const items = [...listed].map(([key, { start, end, own }]) => {
    let number: number | null
    try {
      // An ordinal, not a moment: the server answers it as a JSON number too.
      // eslint-disable-next-line lore/no-number-moment
      number = Number(occurrenceNumber(row.rule, ctx, key))
    } catch (error) {
      if (!(error instanceof RecurrenceError)) throw error
      number = null
    }
    return {
      key,
      start,
      end,
      number,
      entity_id: own?.entity_id ?? null,
      state: own?.state ?? null,
    }
  })
  items.sort((a, b) => {
    const [aHead, aTail] = keyOrder(a.key)
    const [bHead, bTail] = keyOrder(b.key)
    return cmp(a.start, b.start) || cmp(b.end, a.end) || cmp(aHead, bHead) || cmp(aTail, bTail)
  })
  return {
    items: items.map(({ start, end, ...item }) => ({
      ...item,
      start_t: String(start),
      end_t: String(end),
    })),
    truncated: false,
    estimated_count: null,
  }
}

const V = '^vaults/([^/]+)'

/** The window reads of a static export, by route. */
export const WINDOW_HANDLERS: readonly (readonly [RegExp, Handler])[] = [
  [new RegExp(`${V}/timelines/([^/]+)/window$`), timelineWindow],
  [new RegExp(`${V}/events/([^/]+)/occurrences$`), occurrences],
]
