/**
 * Parsing typed dates (chronology-engine.md §10.1): the calendar's formats in reverse. The Python
 * twin is backend/src/lore/chronology/calendar/parsing.py.
 *
 * The text is normalized (trimmed, whitespace runs to one space, an optional circa prefix), then
 * matched against the patterns `formatDate` uses, from the finest precision to the top. A space in
 * a pattern matches any number of spaces, tokens match the values they can render (names,
 * abbreviations or ids of slots, numbers, era abbreviations or names, cycle and overlay values),
 * and matching backtracks. The first match that makes a valid date wins: consistent fields, every
 * level known down to the precision (an omitted only child filled in), accepted by `fromFields`,
 * and cycle and overlay tokens that agree with the result.
 */
import { descend } from './arithmetic'
import { type CompiledCalendar, DateError, activeRegime, defined, isNumber } from './compiled'
import { fromFields, toFields } from './convert'
import { type Piece, type Token, parsePattern, token } from './formats'
import { BASE, layoutOf } from './formatting'

/** Most complete matches of one pattern checked for a valid date. */
export const MATCH_LIMIT = 1000

const SPACES = /\s+/g
/** The minus sign, read like a hyphen. */
const MINUS = '−'
const ORDINAL = ['st', 'nd', 'rd', 'th']

export interface ParsedDate {
  /** From the top level down to `precision` (the year era-relative with `era`). */
  readonly fields: Readonly<Record<string, string>>
  readonly era: string | null
  /** A level id, or `base`. */
  readonly precision: string
  readonly approximate: boolean
  readonly t: bigint
}

export function parsedDateToJson(date: ParsedDate): Record<string, unknown> {
  return { ...date, fields: { ...date.fields }, t: date.t.toString() }
}

/** A matched token: [kind, id, value]. */
type Capture = readonly [string, string | null, string]

/** A run of spaces in a pattern: matches any number of spaces. */
const SPACE = Symbol('space')

type Element = string | typeof SPACE | Token

function elements(pieces: readonly Piece[]): Element[] {
  const found: Element[] = []
  for (const piece of pieces) {
    if (typeof piece !== 'string') {
      found.push(piece)
      continue
    }
    for (const char of piece) {
      if (/\s/.test(char)) {
        if (found.at(-1) !== SPACE) found.push(SPACE)
      } else {
        found.push(char.toLowerCase())
      }
    }
  }
  return found
}

function isDigits(text: string): boolean {
  return /^[0-9]+$/.test(text)
}

// --- patterns ------------------------------------------------------------------------------------

/**
 * The generated patterns of a precision, without only-child omissions, with the year as `{year}`
 * (no eras) or as `{era_year} {era}` and `{era} {era_year}`.
 */
function defaults(calendar: CompiledCalendar, level: number): Piece[][] {
  const layout = layoutOf(calendar)
  const levels = calendar.levels
  const date: Piece[] = []
  for (let index = Math.max(level, layout.clock); index < levels.length - 1; index++) {
    date.push(token('level', defined(levels[index]), layout.named.has(index) ? 'name' : null), ' ')
  }
  const years: Piece[][] =
    calendar.eras.length === 0
      ? [[token('year')]]
      : [
          [token('era_year'), ' ', token('era')],
          [token('era'), ' ', token('era_year')],
        ]
  const clock: Piece[] = []
  if (level < layout.clock) {
    if (layout.clock - 1 === level) {
      const unit = defined(calendar.definition.levels[level])
      clock.push(', ', token('level', unit.id), ` ${unit.abbr ?? unit.label}`)
    } else {
      for (let index = layout.clock - 1; index >= level; index--) {
        clock.push(
          index === layout.clock - 1 ? ', ' : ':',
          token('level', defined(levels[index]), null, 'pad2'),
        )
      }
    }
  }
  return years.map((year) => [...date, ...year, ...clock])
}

/** [precision, pieces] in the order they are tried: finest precision first, the regular pattern
 * then the intercalary one. */
function* patterns(calendar: CompiledCalendar): Generator<[string, Piece[]]> {
  const layout = layoutOf(calendar)
  const custom = calendar.definition.formats
  for (let level = -1; level < calendar.levels.length; level++) {
    const index = Math.max(level, 0)
    const levelId = defined(calendar.levels[index])
    const value = custom == null || levelId === 'intercalary' ? undefined : custom[levelId]
    const regular = typeof value === 'string' ? value : undefined
    const intercalary = custom?.intercalary?.[levelId]
    const candidates: Piece[][] = []
    const seen = new Set<string>()
    for (const pattern of [regular, intercalary]) {
      for (const pieces of pattern === undefined
        ? defaults(calendar, index)
        : [parsePattern(pattern)]) {
        const key = JSON.stringify(pieces)
        if (!seen.has(key)) {
          seen.add(key)
          candidates.push(pieces)
        }
      }
    }
    for (const pieces of candidates) {
      const hasBase = pieces.some((p) => typeof p !== 'string' && p.kind === 'base')
      if (level >= 0) yield [levelId, pieces]
      else if (hasBase)
        yield [BASE, pieces] // the level-0 pattern shows the base itself
      else if (layout.baseSuffix) {
        yield [BASE, [...pieces, ' + ', token('base'), ` ${calendar.context.base_unit.abbr}`]]
      }
    }
  }
}

// --- matching ------------------------------------------------------------------------------------

/** End positions of the number starting at `pos` (grouped, then plain), longest first. */
function numberAt(text: string, pos: number, group: string): number[] {
  let i = pos
  if (i < text.length && (text[i] === '-' || text[i] === MINUS)) i++
  let digits = i
  while (digits < text.length && isDigits(text.charAt(digits))) digits++
  if (digits === i) return []
  const ends = [digits]
  if (group !== '' && digits - i <= 3) {
    let grouped = digits
    while (text.startsWith(group, grouped) && threeDigits(text, grouped + group.length)) {
      grouped += group.length + 3
    }
    if (grouped > digits) ends.unshift(grouped)
  }
  return ends
}

function threeDigits(text: string, pos: number): boolean {
  const chunk = text.slice(pos, pos + 3)
  return chunk.length === 3 && isDigits(chunk) && !isDigits(text.slice(pos + 3, pos + 4))
}

function numberValue(text: string, group: string): string {
  const raw = group === '' ? text : text.split(group).join('')
  return BigInt(raw.replace(MINUS, '-')).toString()
}

function byLength<T>(words: Map<string, T>): [string, T][] {
  return [...words].sort((a, b) => b[0].length - a[0].length)
}

/** Per level: [lowercased word, slot id] for every slot name, abbreviation and id, longest first. */
function levelNames(calendar: CompiledCalendar): Map<string, [string, string][]> {
  const found = new Map<string, Map<string, string>>()
  for (const regime of calendar.regimes) {
    for (const template of regime.templates.values()) {
      if (template.level === 0) continue
      const level = defined(calendar.levels[template.level - 1])
      for (const segment of template.segments) {
        if (segment.slotId === null) continue
        let words = found.get(level)
        if (words === undefined) found.set(level, (words = new Map<string, string>()))
        for (const word of [segment.name, segment.abbr, segment.slotId]) {
          if (word && !words.has(word.toLowerCase())) words.set(word.toLowerCase(), segment.slotId)
        }
      }
    }
  }
  return new Map([...found].map(([level, words]) => [level, byLength(words)]))
}

/** Per cycle: [lowercased name, abbreviation or number, index], longest first. */
function cycleNames(calendar: CompiledCalendar): Map<string, [string, number][]> {
  const found = new Map<string, Map<string, number>>()
  for (const regime of calendar.regimes) {
    for (const cycle of regime.cycles) {
      let words = found.get(cycle.id)
      if (words === undefined) found.set(cycle.id, (words = new Map<string, number>()))
      for (let index = 0; index < cycle.length; index++) {
        for (const word of [
          cycle.names?.[index],
          cycle.abbrs?.[index],
          String(index + cycle.numberStart),
        ]) {
          if (word && !words.has(word.toLowerCase())) words.set(word.toLowerCase(), index)
        }
      }
    }
  }
  return new Map([...found].map(([cycle, words]) => [cycle, byLength(words)]))
}

type Alternative = readonly [Capture | null, number]

class Matcher {
  readonly lower: string
  readonly group: string
  readonly names: Map<string, [string, string][]>
  readonly eras: [string, string[]][]
  readonly cycles: Map<string, [string, number][]>
  readonly phases: Map<string, string[]>

  constructor(
    calendar: CompiledCalendar,
    readonly text: string,
  ) {
    this.lower = text.toLowerCase()
    this.group = layoutOf(calendar).display.digit_group
    this.names = levelNames(calendar)
    this.eras = calendar.eras.map((era) => [
      era.id,
      [era.abbr.toLowerCase(), era.name.toLowerCase()],
    ])
    this.cycles = cycleNames(calendar)
    this.phases = new Map(
      (calendar.definition.overlays ?? []).map((overlay) => [
        overlay.id,
        [...new Set(overlay.phases.map((phase) => phase.name.toLowerCase()))].sort(
          (a, b) => b.length - a.length,
        ),
      ]),
    )
  }

  prefixes(pos: number, words: readonly string[]): number[] {
    return words.filter((w) => w !== '' && this.lower.startsWith(w, pos)).map((w) => pos + w.length)
  }

  numbers(pos: number, ordinal: boolean): [string, number][] {
    const found: [string, number][] = []
    for (const end of numberAt(this.text, pos, this.group)) {
      const value = numberValue(this.text.slice(pos, end), this.group)
      if (ordinal)
        found.push(...this.prefixes(end, ORDINAL).map((e): [string, number] => [value, e]))
      found.push([value, end])
    }
    return found
  }

  /** What `token` can match at `pos` (a capture and the end), in the order tried. */
  alternatives(tok: Token, pos: number): Alternative[] {
    const kind = tok.kind
    if (kind === 'year' || kind === 'era_year' || kind === 'base') {
      return this.numbers(pos, tok.modifier === 'ordinal').map(([v, e]) => [[kind, null, v], e])
    }
    const id = tok.id ?? ''
    const found: Alternative[] = []
    if (kind === 'level') {
      if (tok.attr !== null) {
        for (const [word, slot] of this.names.get(id) ?? []) {
          if (this.lower.startsWith(word, pos)) found.push([['level', id, slot], pos + word.length])
        }
      }
      for (const [v, e] of this.numbers(pos, tok.modifier === 'ordinal')) {
        found.push([['level', id, v], e])
      }
    } else if (kind === 'era') {
      for (const [eraId, words] of this.eras) {
        for (const end of this.prefixes(pos, words)) found.push([['era', eraId, eraId], end])
      }
      found.sort((a, b) => b[1] - a[1])
    } else if (kind === 'cycle') {
      for (const [word, index] of this.cycles.get(id) ?? []) {
        if (this.lower.startsWith(word, pos)) {
          found.push([['cycle', id, String(index)], pos + word.length])
        }
      }
    } else if (tok.attr === 'fraction') {
      const chunk = this.text.slice(pos, pos + 4)
      if (chunk.length === 4 && chunk.startsWith('0.') && isDigits(chunk.slice(2))) {
        found.push([['overlay.fraction', id, chunk], pos + 4])
      }
    } else {
      for (const name of this.phases.get(id) ?? []) {
        for (const end of this.prefixes(pos, [name])) found.push([['overlay', id, name], end])
      }
    }
    found.push([null, pos])
    return found
  }

  /** Every full match of `elements` (depth first, alternatives in order). */
  *matches(pattern: readonly Element[]): Generator<readonly Capture[]> {
    const stack: [number, number, readonly Capture[]][] = [[0, 0, []]]
    for (let top = stack.pop(); top !== undefined; top = stack.pop()) {
      const [index, pos, captures] = top
      if (index === pattern.length) {
        if (pos === this.text.length) yield captures
        continue
      }
      const element = defined(pattern[index])
      if (element === SPACE) {
        stack.push([index + 1, pos, captures])
        if (this.text.startsWith(' ', pos)) stack.push([index + 1, pos + 1, captures])
      } else if (typeof element === 'string') {
        if (this.lower.startsWith(element, pos))
          stack.push([index + 1, pos + element.length, captures])
      } else {
        const options = this.alternatives(element, pos)
        for (let i = options.length - 1; i >= 0; i--) {
          const [capture, end] = defined(options[i])
          stack.push([index + 1, end, capture === null ? captures : [...captures, capture]])
        }
      }
    }
  }
}

// --- dates ---------------------------------------------------------------------------------------

/** A match's values (`null`: not matched); `ok` false when two of them disagree. */
interface Values {
  /** Every value matched per level (a slot id and a number may name the same unit). */
  readonly levels: Map<string, string[]>
  year: string | null
  era_year: string | null
  era: string | null
  base: bigint | null
  ok: boolean
}

/** The fields a match names, and its cycle and overlay values to check. */
function values(calendar: CompiledCalendar, captures: readonly Capture[]): [Values, Capture[]] {
  const found: Values = {
    levels: new Map(),
    year: null,
    era_year: null,
    era: null,
    base: null,
    ok: true,
  }
  const checks: Capture[] = []
  const set = (member: 'year' | 'era_year' | 'era', value: string): void => {
    if (found[member] !== null && found[member] !== value) found.ok = false
    found[member] = value
  }
  const top = calendar.levels.at(-1)
  for (const capture of captures) {
    const [kind, id, value] = capture
    if (kind === 'level' && id === top) set('year', value)
    else if (kind === 'level') {
      const matched = found.levels.get(defined(id))
      if (matched === undefined) found.levels.set(defined(id), [value])
      else matched.push(value)
    } else if (kind === 'year' || kind === 'era_year' || kind === 'era') set(kind, value)
    else if (kind === 'base') found.base = BigInt(value)
    else checks.push(capture)
  }
  return [found, checks]
}

/** [year, era]: era-relative with a matched era, else astronomical ("15 March 2024"). */
function yearOf(found: Values): [string, string | null] | null {
  if (found.year !== null) return [found.year, null] // an era token alongside only had to match
  if (found.era_year === null) return null
  return [found.era_year, found.era]
}

/** The valid date of a match, or `null` (§10.1). */
function dateOf(
  calendar: CompiledCalendar,
  precision: string,
  captures: readonly Capture[],
  approximate: boolean,
): ParsedDate | null {
  const levels = calendar.levels
  const [found, checks] = values(calendar, captures)
  const year = found.ok ? yearOf(found) : null
  if (year === null || (precision === BASE && found.base === null)) return null
  const index = precision === BASE ? 0 : calendar.levelIndex(precision)
  const fields: Record<string, string> = { [defined(levels.at(-1))]: year[0] }
  const era = year[1]
  let t: bigint
  try {
    for (let level = levels.length - 2; level >= index; level--) {
      const matched = found.levels.get(defined(levels[level])) ?? []
      // A slot id first: a number names a regular unit only.
      const value =
        matched.find((v) => !isNumber(v)) ??
        matched[0] ??
        onlyChild(calendar, fields, defined(levels[level + 1]), era)
      if (value === null) return null
      fields[defined(levels[level])] = value
    }
    t = fromFields(calendar, fields, defined(levels[index]), { era, overflow: 'reject' })
  } catch (error) {
    if (error instanceof DateError) return null
    throw error
  }
  if (precision === BASE) {
    const base = defined(found.base)
    const unit = descend(calendar, activeRegime(calendar, t), t, 0).template.length
    if (base < 0n || base >= unit) return null
    t += base
  }
  if (!consistent(calendar, t, found.levels)) return null
  if (checks.length > 0 && !agrees(calendar, t, index, checks)) return null
  return { fields, era, precision, approximate, t }
}

/** The child of the `parent` unit `fields` name when it is its only child. */
function onlyChild(
  calendar: CompiledCalendar,
  fields: Record<string, string>,
  parent: string,
  era: string | null,
): string | null {
  const t = fromFields(calendar, fields, parent, { era, overflow: 'reject' })
  const level = calendar.levelIndex(parent)
  const template = descend(calendar, activeRegime(calendar, t), t, level).template
  if (template.totalCount !== 1n) return null
  const segment = defined(template.segments[0])
  return segment.slotId ?? defined(calendar.numberingStarts[level - 1]).toString()
}

/** Every value matched for a level names the date's unit (its number or its slot id). */
function consistent(
  calendar: CompiledCalendar,
  t: bigint,
  levels: ReadonlyMap<string, readonly string[]>,
): boolean {
  const found = toFields(calendar, t).levels
  for (const [level, matched] of levels) {
    const unit = defined(found.get(level))
    for (const value of matched) {
      const same = isNumber(value)
        ? unit.n !== null && BigInt(value) === unit.n
        : unit.slotId === value
      if (!same) return false
    }
  }
  return true
}

/** The matched values of cycles at or above the precision `level` are the date's (finer cycles
 * and overlays change within the unit: they only have to match). */
function agrees(
  calendar: CompiledCalendar,
  t: bigint,
  level: number,
  checks: readonly Capture[],
): boolean {
  const found = toFields(calendar, t)
  const regime = activeRegime(calendar, t)
  for (const [kind, id, value] of checks) {
    const cycle = regime.cycles.find((c) => c.id === id)
    if (kind !== 'cycle' || cycle === undefined || cycle.level < level) continue
    const current = found.cycles.get(id ?? '')
    if (current == null || String(current.index) !== value) return false
  }
  return true
}

/** §10.1 `parse`: the date `text` writes in this calendar's formats; `invalid_date` when none
 * matches. */
export function parseDate(calendar: CompiledCalendar, text: string): ParsedDate {
  let normalized = text.replace(SPACES, ' ').trim()
  let approximate = false
  const circa = layoutOf(calendar).display.circa.replace(SPACES, ' ').trim().toLowerCase()
  if (circa !== '' && normalized.toLowerCase().startsWith(circa)) {
    approximate = true
    normalized = normalized.slice(circa.length).trim()
  }
  const matcher = new Matcher(calendar, normalized)
  for (const [precision, pieces] of patterns(calendar)) {
    let count = 0
    for (const captures of matcher.matches(elements(pieces))) {
      if (count++ >= MATCH_LIMIT) break
      const date = dateOf(calendar, precision, captures, approximate)
      if (date !== null) return date
    }
  }
  throw new DateError('invalid_date', `no date of this calendar reads ${JSON.stringify(text)}`)
}
