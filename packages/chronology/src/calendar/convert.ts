/**
 * Moment ⇄ fields conversions (chronology-engine.md §5.3, §5.5–§5.7, §6). The Python twin is
 * backend/src/lore/chronology/calendar/convert.py.
 *
 * Every step jumps with prefix sums and binary searches: the cost depends on the number of levels
 * and the logarithm of template widths, never on the year number (years may have 1000 digits).
 * Cycles, eras and overlays arrive with #24; their members of the §5.6 output are `null`/`{}`.
 */
import {
  type Child,
  type CompiledCalendar,
  type CompiledRegime,
  type CompiledTemplate,
  childRegularIndex,
  defined,
  isNumber,
} from './compiled'

export type Overflow = 'reject' | 'constrain'
export type DateErrorCode = 'invalid_date' | 'reform_gap' | 'reform_ambiguous'

/** A date the calendar can't resolve. `level` names the offending level, if any. */
export class DateError extends Error {
  constructor(
    readonly code: DateErrorCode,
    message: string,
    readonly level: string | null = null,
  ) {
    super(message)
    this.name = 'DateError'
  }
}

/** One level of a date: its regular number and, for a named slot, the slot's identity. */
export interface UnitValue {
  /** Regular number; `null` for an intercalary unit. */
  readonly n: bigint | null
  readonly slotId: string | null
  readonly name: string | null
  readonly intercalary: boolean
}

/** The result of `toFields` (chronology-engine §5.6). */
export interface DateFields {
  readonly regime: string
  /** Every level, top level first. */
  readonly levels: ReadonlyMap<string, UnitValue>
  /** Base-unit remainder inside the level-0 unit. */
  readonly base: bigint
}

/** The §5.6 JSON shape of a date (as in the conformance vectors). */
export function dateFieldsToJson(date: DateFields): Record<string, unknown> {
  const levels: Record<string, unknown> = {}
  for (const [level, value] of date.levels) {
    const n = value.n === null ? null : value.n.toString()
    levels[level] =
      value.slotId === null
        ? { n }
        : { n, id: value.slotId, name: value.name, intercalary: value.intercalary }
  }
  return {
    regime: date.regime,
    levels,
    base: date.base.toString(),
    era: null,
    cycles: {},
    overlays: {},
  }
}

// --- regimes -------------------------------------------------------------------------------------

/**
 * The last regime whose start is `≤ t` (regime 0 before every other). Regimes whose start is a
 * `local` anchor are resolved by #24; until then they never activate.
 */
export function activeRegime(calendar: CompiledCalendar, t: bigint): CompiledRegime {
  const regime = calendar.regimes.findLast(
    (r) => r.index === 0 || (r.startsAt !== null && r.startsAt <= t),
  )
  return defined(regime)
}

function regimeEnd(calendar: CompiledCalendar, regime: CompiledRegime): bigint | null {
  let end: bigint | null = null
  for (const later of calendar.regimes.slice(regime.index + 1)) {
    if (later.startsAt !== null && (end === null || later.startsAt < end)) end = later.startsAt
  }
  return end
}

// --- toFields ------------------------------------------------------------------------------------

/** The date of moment `t`: every level from the top down, plus the base remainder. */
export function toFields(calendar: CompiledCalendar, t: bigint): DateFields {
  const regime = activeRegime(calendar, t)
  const rel = t - regime.epoch
  const year = regime.yearOfRel(rel)
  let offset = rel - regime.relStart(year)
  let template = regime.yearTemplate(year)
  const levels = calendar.levels
  const values = new Map<string, UnitValue>([
    [defined(levels.at(-1)), { n: year, slotId: null, name: null, intercalary: false }],
  ])
  for (let level = levels.length - 2; level >= 0; level--) {
    const child = template.childAt(offset)
    offset -= child.offset
    values.set(defined(levels[level]), unitValue(child, defined(calendar.numberingStarts[level])))
    template = regime.template(defined(child.segment.child)) // children of level ≥ 1 templates
  }
  return { regime: regime.id, levels: values, base: offset }
}

function unitValue(child: Child, numberingStart: bigint): UnitValue {
  const regular = childRegularIndex(child)
  const { slotId, name, intercalary } = child.segment
  return { n: regular === null ? null : regular + numberingStart, slotId, name, intercalary }
}

// --- fromFields ----------------------------------------------------------------------------------

export interface FromFieldsOptions {
  /** Interpret the fields in this regime (proleptically); else pick the regime in force. */
  readonly regime?: string | null
  /** `reject` (default): out-of-range values are `invalid_date`; `constrain`: they are clamped. */
  readonly overflow?: Overflow
}

/** Calendar fields by level id: regular numbers or slot ids (decimal strings). */
export type FieldsInput = Readonly<Record<string, string | undefined>>

/**
 * The start moment of the unit at `precision` that `fields` denote (§5.7). `fields` hold every
 * level from the top down to `precision` and none below. Throws `DateError`.
 */
export function fromFields(
  calendar: CompiledCalendar,
  fields: FieldsInput,
  precision: string,
  options: FromFieldsOptions = {},
): bigint {
  const overflow = options.overflow ?? 'reject'
  checkShape(calendar, fields, precision)
  if (options.regime != null) {
    const chosen = calendar.regimes.find((r) => r.id === options.regime)
    if (chosen === undefined)
      throw new DateError('invalid_date', `unknown regime ${options.regime}`)
    return resolve(calendar, chosen, fields, precision, overflow)
  }
  const results: bigint[] = []
  const errors: DateError[] = []
  for (const candidate of [...calendar.regimes].reverse()) {
    if (candidate.index > 0 && candidate.startsAt === null) continue // a local start (#24)
    let t: bigint
    try {
      t = resolve(calendar, candidate, fields, precision, overflow)
    } catch (error) {
      if (!(error instanceof DateError)) throw error
      errors.push(error)
      continue
    }
    const end = regimeEnd(calendar, candidate)
    const afterStart = candidate.startsAt === null || candidate.startsAt <= t
    if (afterStart && (end === null || t < end)) results.push(t)
  }
  if (results.length > 1) {
    throw new DateError('reform_ambiguous', 'the date exists in several regimes: pass regime')
  }
  if (results.length === 1) return defined(results[0])
  // Invalid in every regime: report regime 0's error.
  const last = errors.at(-1)
  if (last !== undefined && errors.length === calendar.regimes.length) throw last
  throw new DateError('reform_gap', 'no regime has this date at a moment it is in force')
}

function checkShape(calendar: CompiledCalendar, fields: FieldsInput, precision: string): void {
  const levels = calendar.levels
  const lowest = calendar.levelIndex(precision)
  if (lowest < 0) throw new DateError('invalid_date', `unknown precision ${precision}`, precision)
  for (const key of Object.keys(fields)) {
    if (calendar.levelIndex(key) < 0)
      throw new DateError('invalid_date', `${key} is not a level`, key)
  }
  for (let level = levels.length - 1; level >= 0; level--) {
    const id = defined(levels[level])
    const present = Object.hasOwn(fields, id)
    if (level >= lowest && !present) throw new DateError('invalid_date', `${id} is missing`, id)
    if (level < lowest && present) {
      throw new DateError('invalid_date', `${id} is below the precision`, id)
    }
  }
}

function resolve(
  calendar: CompiledCalendar,
  regime: CompiledRegime,
  fields: FieldsInput,
  precision: string,
  overflow: Overflow,
): bigint {
  const levels = calendar.levels
  const top = defined(levels.at(-1))
  const yearValue = defined(fields[top])
  if (!isNumber(yearValue)) throw new DateError('invalid_date', 'the year must be a number', top)
  const year = BigInt(yearValue)
  let t = regime.yearStart(year)
  let template = regime.yearTemplate(year)
  for (let level = levels.length - 2; level >= calendar.levelIndex(precision); level--) {
    const value = defined(fields[defined(levels[level])])
    const child = locateChild(calendar, regime, template, level, value, overflow)
    t += child.offset
    template = regime.template(defined(child.segment.child))
  }
  return t
}

function locateChild(
  calendar: CompiledCalendar,
  regime: CompiledRegime,
  template: CompiledTemplate,
  level: number,
  value: string,
  overflow: Overflow,
): Child {
  const levelId = defined(calendar.levels[level])
  const numbering = defined(calendar.numberingStarts[level])
  let child: Child | null
  if (isNumber(value)) {
    const index = BigInt(value) - numbering
    child = template.childByRegularIndex(index)
    if (child === null && overflow === 'constrain' && template.regularCount > 0n) {
      const last = template.regularCount - 1n
      child = template.childByRegularIndex(index < 0n ? 0n : index > last ? last : index)
    }
  } else {
    child = template.childBySlot(value)
    if (child === null && overflow === 'constrain') {
      child = fallback(calendar, regime, template, level, value)
    }
  }
  if (child === null) throw new DateError('invalid_date', `no ${levelId} ${value} here`, levelId)
  return child
}

/** Constrain an unknown slot id: its regular number in the parent level's default template. */
function fallback(
  calendar: CompiledCalendar,
  regime: CompiledRegime,
  template: CompiledTemplate,
  level: number,
  slotId: string,
): Child | null {
  const defaultId = calendar.definition.levels[level + 1]?.default_template
  const defaultTemplate = defaultId == null ? undefined : regime.templates.get(defaultId)
  const found = defaultTemplate?.childBySlot(slotId) ?? null
  const regular = found === null ? null : childRegularIndex(found)
  if (regular === null || template.regularCount === 0n) return null
  const last = template.regularCount - 1n
  return template.childByRegularIndex(regular < last ? regular : last)
}

// --- normalization -------------------------------------------------------------------------------

/**
 * Store-ready fields: named units by slot id, unnamed units by canonical number (§6). The fields
 * must form a valid date (`reject` semantics) down to their finest level.
 */
export function normalizeFields(
  calendar: CompiledCalendar,
  fields: FieldsInput,
  options: { readonly regime?: string | null } = {},
): Record<string, string> {
  const levels = calendar.levels
  const precision = levels.find((level) => Object.hasOwn(fields, level)) ?? defined(levels.at(-1))
  const regime = options.regime ?? null
  const t = fromFields(calendar, fields, precision, { regime }) // validates; picks the regime
  const chosen =
    regime === null
      ? activeRegime(calendar, t)
      : defined(calendar.regimes.find((r) => r.id === regime))
  const top = defined(levels.at(-1))
  const year = BigInt(defined(fields[top]))
  let template = chosen.yearTemplate(year)
  const normalized: Record<string, string> = { [top]: year.toString() }
  for (let level = levels.length - 2; level >= calendar.levelIndex(precision); level--) {
    const id = defined(levels[level])
    const child = locateChild(calendar, chosen, template, level, defined(fields[id]), 'reject')
    // Named units by slot id (intercalary ones have no number); unnamed ones are never intercalary.
    normalized[id] =
      child.segment.slotId ??
      (defined(childRegularIndex(child)) + defined(calendar.numberingStarts[level])).toString()
    template = chosen.template(defined(child.segment.child))
  }
  return normalized
}
