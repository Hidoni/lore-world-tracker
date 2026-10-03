/**
 * Formatting dates and spans (chronology-engine.md §3.11, §10). The Python twin is
 * backend/src/lore/chronology/calendar/formatting.py.
 *
 * A date is rendered with the pattern for its precision: `formats[<precision>]`, or
 * `formats.intercalary[<precision>]` when the deepest named unit at or above the precision is
 * intercalary, else a pattern generated from the levels. Numbers use the calendar's `display`
 * options: up to 4 digits they are plain, longer ones are grouped, and from `scientific_threshold`
 * digits on they switch to scientific notation.
 */
import { floorDiv, formatInteger } from '../numbers'
import type { BaseUnit, DisplayOptions } from '../schema.gen'
import { type CompiledCalendar, DateError, defined } from './compiled'
import { type DateFields, type UnitValue, toFields } from './convert'
import { type Piece, type Token, parsePattern, token } from './formats'

/** The precision finer than every level: exact moments. */
export const BASE = 'base'

/** Date numbers with at most this many digits are never grouped (2024, not 2,024). */
const PLAIN_DIGITS = 4

/** A resolved time point to display: moment, precision (level id or `base`), circa. */
export interface DisplayPoint {
  readonly t: bigint
  readonly precision: string
  readonly approximate?: boolean
}

/** The `display` options with their defaults (§3.11). */
export type Display = Required<DisplayOptions>

export function displayOptions(options: DisplayOptions | null | undefined): Display {
  return {
    circa: options?.circa ?? 'c. ',
    digit_group: options?.digit_group ?? ',',
    scientific_threshold: options?.scientific_threshold ?? 16,
    significant_digits: options?.significant_digits ?? 4,
    range_separator: options?.range_separator ?? ' – ',
  }
}

// --- calendar layout (cached per compiled calendar) ----------------------------------------------

interface Layout {
  readonly display: Display
  /** Levels with named slots in some template of some regime. */
  readonly named: ReadonlySet<number>
  /** Levels `0 … clock-1` form the clock of default formats (unnamed, numbered from 0). */
  readonly clock: number
  /** Some level-0 unit spans several base units, so `base` precision shows the remainder. */
  readonly baseSuffix: boolean
  readonly cycleLevels: ReadonlyMap<string, number>
}

const LAYOUTS = new WeakMap<CompiledCalendar, Layout>()

function layoutOf(calendar: CompiledCalendar): Layout {
  const cached = LAYOUTS.get(calendar)
  if (cached !== undefined) return cached
  const templates = calendar.regimes.flatMap((regime) => [...regime.templates.values()])
  const named = new Set(
    templates
      .filter((template) => template.segments.some((segment) => segment.slotId !== null))
      .map((template) => template.level - 1),
  )
  const top = calendar.levels.length - 1
  let clock = 0
  while (clock < top && !named.has(clock) && calendar.numberingStarts[clock] === 0n) clock++
  const layout: Layout = {
    display: displayOptions(calendar.definition.display),
    named,
    clock,
    baseSuffix: templates.some((template) => template.level === 0 && template.length > 1n),
    cycleLevels: new Map(
      calendar.regimes.flatMap((regime) => regime.cycles.map((c) => [c.id, c.level] as const)),
    ),
  }
  LAYOUTS.set(calendar, layout)
  return layout
}

// --- one date ------------------------------------------------------------------------------------

interface DateAt {
  readonly fields: DateFields
  /** Index of the precision level (0 for `base`). */
  readonly level: number
  /** The precision is `base`. */
  readonly base: boolean
}

function dateAt(calendar: CompiledCalendar, t: bigint, precision: string): DateAt {
  if (precision === BASE) return { fields: toFields(calendar, t), level: 0, base: true }
  const level = calendar.levelIndex(precision)
  if (level < 0) throw new DateError('invalid_date', `unknown precision ${precision}`, precision)
  return { fields: toFields(calendar, t), level, base: false }
}

/** §10 `format`: the date of `t` at `precision`, with the circa prefix if approximate. */
export function formatDate(
  calendar: CompiledCalendar,
  t: bigint,
  precision: string,
  options: { readonly approximate?: boolean } = {},
): string {
  const date = dateAt(calendar, t, precision)
  return circa(calendar, render(calendar, date, patternOf(calendar, date)), options.approximate)
}

function circa(calendar: CompiledCalendar, text: string, approximate = false): string {
  return approximate ? layoutOf(calendar).display.circa + text : text
}

function unitAt(date: DateAt, levelId: string): UnitValue {
  return defined(date.fields.levels.get(levelId))
}

/** The deepest named unit at or above the precision is intercalary. */
function intercalary(calendar: CompiledCalendar, date: DateAt): boolean {
  for (let level = date.level; level < calendar.levels.length - 1; level++) {
    const value = unitAt(date, defined(calendar.levels[level]))
    if (value.slotId !== null) return value.intercalary
  }
  return false
}

/** The pieces of the pattern used for `date` (custom or generated, §3.11). */
function patternOf(calendar: CompiledCalendar, date: DateAt): Piece[] {
  const levelId = defined(calendar.levels[date.level])
  const custom = calendar.definition.formats
  let pattern: string | undefined
  if (custom != null) {
    if (intercalary(calendar, date)) {
      pattern = custom.intercalary?.[levelId]
    } else {
      const value = levelId === 'intercalary' ? undefined : custom[levelId]
      pattern = typeof value === 'string' ? value : undefined
    }
  }
  const pieces = pattern === undefined ? defaultPattern(calendar, date) : parsePattern(pattern)
  const hasBase = pieces.some((piece) => typeof piece !== 'string' && piece.kind === 'base')
  if (date.base && layoutOf(calendar).baseSuffix && !hasBase) {
    pieces.push(' + ', token('base'), ` ${calendar.context.base_unit.abbr}`)
  }
  return pieces
}

/**
 * The generated pattern: the date fine → coarse (names for named levels, the year with its era),
 * then a clock of the numeric 0-based levels; only children are left out.
 */
function defaultPattern(calendar: CompiledCalendar, date: DateAt): Piece[] {
  const layout = layoutOf(calendar)
  const levels = calendar.levels
  const parts: Piece[][] = []
  for (let level = Math.max(date.level, layout.clock); level < levels.length - 1; level++) {
    const levelId = defined(levels[level])
    if (!unitAt(date, levelId).onlyChild) {
      parts.push([token('level', levelId, layout.named.has(level) ? 'name' : null)])
    }
  }
  const era = date.fields.era
  if (era === null) {
    parts.push([token('year')])
  } else if (defined(calendar.eras.find((e) => e.id === era.id)).abbrPosition === 'prefix') {
    parts.push([token('era'), ' ', token('era_year')])
  } else {
    parts.push([token('era_year'), ' ', token('era')])
  }
  const pieces = join(parts, ' ')
  if (date.level < layout.clock) {
    if (layout.clock - 1 === date.level) {
      const unit = defined(calendar.definition.levels[date.level])
      pieces.push(', ', token('level', unit.id), ` ${unit.abbr ?? unit.label}`)
    } else {
      const clock: Piece[][] = []
      for (let level = layout.clock - 1; level >= date.level; level--) {
        clock.push([token('level', defined(levels[level]), null, 'pad2')])
      }
      pieces.push(', ', ...join(clock, ':'))
    }
  }
  return pieces
}

function join(parts: readonly Piece[][], separator: string): Piece[] {
  return parts.flatMap((part, i) => (i === 0 ? part : [separator, ...part]))
}

/** The text of `pieces`; runs of spaces left by empty values collapse, ends are trimmed. */
function render(calendar: CompiledCalendar, date: DateAt, pieces: readonly Piece[]): string {
  const text = pieces
    .map((piece) => (typeof piece === 'string' ? piece : valueOf(calendar, date, piece)))
    .join('')
  return text.replace(/ {2,}/g, ' ').trim()
}

function valueOf(calendar: CompiledCalendar, date: DateAt, piece: Token): string {
  const fields = date.fields
  const display = layoutOf(calendar).display
  switch (piece.kind) {
    case 'level':
      return levelText(unitAt(date, defined(piece.id)), display, piece)
    case 'cycle':
      return cycleText(calendar, date, piece)
    case 'overlay': {
      const overlay = defined(fields.overlays.get(defined(piece.id)))
      if (piece.attr !== 'fraction') return overlay.name
      // .fraction truncates, so it never shows 1.00
      const hundredths = floorDiv(overlay.phase.num * 100n, overlay.phase.den)
      return `0.${hundredths.toString().padStart(2, '0')}`
    }
    case 'era':
      if (fields.era === null) return ''
      return piece.attr === 'name' ? fields.era.name : fields.era.abbr
    case 'year':
    case 'era_year':
    case 'base': {
      const year = defined(unitAt(date, defined(calendar.levels.at(-1))).n)
      const number =
        piece.kind === 'base'
          ? fields.base
          : piece.kind === 'era_year' && fields.era !== null
            ? fields.era.year
            : year
      return numberText(number, display, piece.modifier)
    }
  }
}

/** A level token: the number, or slot information falling back to the number. */
function levelText(value: UnitValue, display: Display, piece: Token): string {
  const number = value.n === null ? '' : numberText(value.n, display, piece.modifier)
  const fallbacks: Record<string, (string | null)[]> = {
    name: [value.name],
    abbr: [value.abbr, value.name],
    id: [value.slotId],
  }
  const found = (fallbacks[piece.attr ?? ''] ?? []).find((text) => text !== null && text !== '')
  return found ?? number
}

/**
 * A cycle's name (number without names), abbreviation or number; empty where excluded or in a
 * regime without the cycle.
 */
function cycleText(calendar: CompiledCalendar, date: DateAt, piece: Token): string {
  const value = date.fields.cycles.get(defined(piece.id))
  if (value == null) return ''
  if (piece.attr === 'n') return String(value.n)
  if (piece.attr === 'abbr') {
    const regime = defined(calendar.regimes.find((r) => r.id === date.fields.regime))
    const abbrs = defined(regime.cycles.find((c) => c.id === piece.id)).abbrs
    if (abbrs !== null) return defined(abbrs[value.index])
  }
  return value.name ?? String(value.n)
}

/** A date number: plain up to 4 digits, else grouped, scientific from the threshold on. */
function numberText(n: bigint, display: Display, modifier: Token['modifier']): string {
  const digits = (n < 0n ? -n : n).toString()
  const text = formatInteger(n, {
    digitGroup: digits.length > PLAIN_DIGITS ? display.digit_group : '',
    scientificThreshold: display.scientific_threshold,
    significantDigits: display.significant_digits,
  })
  if ((modifier === 'pad2' || modifier === 'pad3') && text === n.toString()) {
    return (n < 0n ? '-' : '') + digits.padStart(modifier === 'pad2' ? 2 : 3, '0')
  }
  if (modifier === 'ordinal' && digits.length < display.scientific_threshold) {
    return text + ordinalSuffix(digits) // a suffix on "10^8" would misread as "10 to the 8th"
  }
  return text
}

function ordinalSuffix(digits: string): string {
  const lastTwo = Number(digits.slice(-2))
  if (lastTwo >= 11 && lastTwo <= 13) return 'th'
  return { '1': 'st', '2': 'nd', '3': 'rd' }[digits.slice(-1)] ?? 'th'
}

// --- spans ---------------------------------------------------------------------------------------

/**
 * §10 `formatSpan`: start and end with the shared coarse parts written once. Collapsing needs
 * both ends to use the same pattern (same precision, same intercalary choice). The parts that
 * differ are the tokens at or below the coarsest differing level; if they all come before the
 * shared ones, the start keeps only them ("12 – 15 March 2024"); if they all come after, the end
 * does ("15 March 2024, 14:30 – 16:00"). Both ends in the same unit (and equally approximate)
 * give a single date. An open end (`null`) is `?`.
 */
export function formatSpan(
  calendar: CompiledCalendar,
  start: DisplayPoint | null,
  end: DisplayPoint | null,
): string {
  const separator = layoutOf(calendar).display.range_separator
  if (start === null || end === null) {
    return [start, end]
      .map((point) =>
        point === null
          ? '?'
          : formatDate(calendar, point.t, point.precision, { approximate: point.approximate }),
      )
      .join(separator)
  }
  const first = dateAt(calendar, start.t, start.precision)
  const last = dateAt(calendar, end.t, end.precision)
  const pattern = patternOf(calendar, first)
  const endPattern = patternOf(calendar, last)
  let startPieces: readonly Piece[] = pattern
  let endPieces: readonly Piece[] = endPattern
  if (start.precision === end.precision && samePieces(pattern, endPattern)) {
    const differing = differingLevel(calendar, first, last)
    const startCirca = start.approximate ?? false
    if (differing === null && startCirca === (end.approximate ?? false)) {
      return circa(calendar, render(calendar, first, pattern), startCirca)
    }
    if (differing !== null) [startPieces, endPieces] = collapse(calendar, pattern, differing)
  }
  return [
    circa(calendar, render(calendar, first, startPieces), start.approximate),
    circa(calendar, render(calendar, last, endPieces), end.approximate),
  ].join(separator)
}

function samePieces(a: readonly Piece[], b: readonly Piece[]): boolean {
  return JSON.stringify(a) === JSON.stringify(b)
}

function sameUnit(a: UnitValue, b: UnitValue): boolean {
  return (
    a.n === b.n &&
    a.slotId === b.slotId &&
    a.name === b.name &&
    a.intercalary === b.intercalary &&
    a.abbr === b.abbr &&
    a.onlyChild === b.onlyChild
  )
}

/**
 * The coarsest level at which two dates of one precision differ (the top level + 1 for a
 * different era, or for equal fields in different regimes; -1 for the base remainder), or `null`
 * for the same unit.
 */
function differingLevel(calendar: CompiledCalendar, first: DateAt, last: DateAt): number | null {
  const a = first.fields
  const b = last.fields
  const top = calendar.levels.length - 1
  if ((a.era?.id ?? null) !== (b.era?.id ?? null)) return top + 1
  for (let level = top; level >= first.level; level--) {
    const levelId = defined(calendar.levels[level])
    if (!sameUnit(unitAt(first, levelId), unitAt(last, levelId))) return level
  }
  if (first.base && a.base !== b.base) return -1
  return a.regime !== b.regime ? top + 1 : null
}

/** The level a token's value depends on (-1: finer than level 0). */
function rank(calendar: CompiledCalendar, piece: Token): number {
  const top = calendar.levels.length - 1
  switch (piece.kind) {
    case 'level':
      return calendar.levelIndex(defined(piece.id))
    case 'year':
    case 'era_year':
      return top
    case 'era':
      return top + 1
    case 'cycle':
      return defined(layoutOf(calendar).cycleLevels.get(defined(piece.id)))
    case 'base':
    case 'overlay':
      return -1
  }
}

/** (start pieces, end pieces) with the shared tokens dropped from one end, if possible. */
function collapse(
  calendar: CompiledCalendar,
  pattern: readonly Piece[],
  differing: number,
): [readonly Piece[], readonly Piece[]] {
  const varying: number[] = []
  const shared: number[] = []
  pattern.forEach((piece, i) => {
    if (typeof piece === 'string') return
    ;(rank(calendar, piece) <= differing ? varying : shared).push(i)
  })
  if (varying.length > 0 && shared.length > 0) {
    if (Math.max(...varying) < Math.min(...shared)) {
      return [pattern.slice(0, Math.max(...varying) + 1), pattern]
    }
    if (Math.min(...varying) > Math.max(...shared)) {
      return [pattern, pattern.slice(Math.min(...varying))]
    }
  }
  return [pattern, pattern]
}

// --- the Absolute calendar -----------------------------------------------------------------------

/** §10: the virtual Absolute calendar, `t = <grouped or scientific> <abbr>`. */
export function formatAbsolute(
  t: bigint,
  baseUnit: BaseUnit,
  display?: DisplayOptions | null,
  options: { readonly approximate?: boolean } = {},
): string {
  const resolved = displayOptions(display)
  const number = formatInteger(t, {
    digitGroup: resolved.digit_group,
    scientificThreshold: resolved.scientific_threshold,
    significantDigits: resolved.significant_digits,
  })
  const text = `t = ${number} ${baseUnit.abbr}`
  return options.approximate === true ? resolved.circa + text : text
}
