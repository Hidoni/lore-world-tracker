/**
 * Moment ⇄ fields conversions (chronology-engine.md §5.3, §5.5–§5.7, §6). The Python twin is
 * backend/src/lore/chronology/calendar/convert.py.
 *
 * Every step jumps with prefix sums and binary searches: the cost depends on the number of levels
 * and the logarithm of template widths, never on the year number (years may have 1000 digits).
 * Cycles, eras and overlays come from their modules (`cycles`, `eras`, `overlays`).
 */
import {
  type Child,
  type CompiledCalendar,
  type CompiledRegime,
  type CompiledTemplate,
  DateError,
  activeRegime,
  childRegularIndex,
  defined,
  isNumber,
} from './compiled'
import { type CycleValue, cycleValues } from './cycles'
import { type EraValue, eraOf, eraValueToJson, findEra } from './eras'
import { type OverlayValue, overlayValueToJson, overlayValues } from './overlays'

export type Overflow = 'reject' | 'constrain'

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
  /** Every cycle of the regime: its value, or `null` where the unit is excluded. */
  readonly cycles: ReadonlyMap<string, CycleValue | null>
  /** The era and era-relative year (`null` for a calendar without eras). */
  readonly era: EraValue | null
  /** Every overlay's phase and phase name. */
  readonly overlays: ReadonlyMap<string, OverlayValue>
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
    era: date.era === null ? null : eraValueToJson(date.era),
    cycles: Object.fromEntries(
      [...date.cycles].map(([id, value]) => [id, value === null ? null : { ...value }]),
    ),
    overlays: Object.fromEntries(
      [...date.overlays].map(([id, value]) => [id, overlayValueToJson(value)]),
    ),
  }
}

// --- regimes -------------------------------------------------------------------------------------

function regimeById(calendar: CompiledCalendar, regime: string): CompiledRegime {
  const found = calendar.regimes.find((r) => r.id === regime)
  if (found === undefined) throw new DateError('invalid_date', `unknown regime ${regime}`)
  return found
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
  return {
    regime: regime.id,
    levels: values,
    base: offset,
    cycles: cycleValues(levels.length - 1, regime, t),
    era: eraOf(calendar, t),
    overlays: overlayValues(calendar, t),
  }
}

function unitValue(child: Child, numberingStart: bigint): UnitValue {
  const regular = childRegularIndex(child)
  const { slotId, name, intercalary } = child.segment
  return { n: regular === null ? null : regular + numberingStart, slotId, name, intercalary }
}

// --- fromFields ----------------------------------------------------------------------------------

export interface FromFieldsOptions {
  /** The year is relative to this era (§3.8); else it is astronomical. */
  readonly era?: string | null
  /** Interpret the fields in this regime (proleptically); else pick the regime in force. */
  readonly regime?: string | null
  /** `reject` (default): out-of-range values are `invalid_date`; `constrain`: they are clamped. */
  readonly overflow?: Overflow
}

/** Calendar fields by level id: regular numbers or slot ids (decimal strings). */
export type FieldsInput = Readonly<Record<string, string | undefined>>

/**
 * The start moment of the unit at `precision` that `fields` denote (§5.7). `fields` hold every
 * level from the top down to `precision` and none below. With `era`, the year is era-relative,
 * the unit must overlap the era, and a unit that starts before the era resolves to the era's
 * start. Throws `DateError`.
 */
export function fromFields(
  calendar: CompiledCalendar,
  fields: FieldsInput,
  precision: string,
  options: FromFieldsOptions = {},
): bigint {
  const overflow = options.overflow ?? 'reject'
  checkShape(calendar, fields, precision)
  if (options.era != null) return fromEraFields(calendar, fields, precision, options.era, options)
  if (options.regime != null) {
    return resolve(calendar, regimeById(calendar, options.regime), fields, precision, overflow)
  }
  const results: bigint[] = []
  const errors: DateError[] = []
  for (const candidate of [...calendar.regimes].reverse()) {
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

/** §5.7 step 1: an era year becomes `Y`; the resulting unit must overlap the era. */
function fromEraFields(
  calendar: CompiledCalendar,
  fields: FieldsInput,
  precision: string,
  eraId: string,
  options: FromFieldsOptions,
): bigint {
  const top = defined(calendar.levels.at(-1))
  const era = findEra(calendar, eraId)
  const yearValue = defined(fields[top])
  if (!isNumber(yearValue)) throw new DateError('invalid_date', 'the year must be a number', top)
  const astronomical = { ...fields, [top]: era.year(BigInt(yearValue)).toString() }
  const regime = options.regime ?? null
  const start = fromFields(calendar, astronomical, precision, { ...options, era: null })
  const chosen = regime === null ? activeRegime(calendar, start) : regimeById(calendar, regime)
  const end = start + unitLength(calendar, chosen, astronomical, precision)
  if ((era.start !== null && end <= era.start) || (era.end !== null && start >= era.end)) {
    throw new DateError('invalid_date', `the date is not in the era ${eraId}`, top)
  }
  // A unit that straddles the era's start resolves to the era's start ("Reiwa 1" → 1 May 2019).
  return era.start !== null && era.start > start ? era.start : start
}

function unitLength(
  calendar: CompiledCalendar,
  regime: CompiledRegime,
  fields: FieldsInput,
  precision: string,
): bigint {
  const levels = calendar.levels
  let template = regime.yearTemplate(BigInt(defined(fields[defined(levels.at(-1))])))
  for (let level = levels.length - 2; level >= calendar.levelIndex(precision); level--) {
    const value = defined(fields[defined(levels[level])])
    const child = resolveChild(calendar, regime, template, level, value, 'constrain')
    template = regime.template(defined(child.segment.child))
  }
  return template.length
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
    const child = resolveChild(calendar, regime, template, level, value, overflow)
    t += child.offset
    template = regime.template(defined(child.segment.child))
  }
  return t
}

/**
 * The child of `template` (a `level + 1` unit) addressed by `value`: a regular number or a slot
 * id, constrained per §5.7 step 4 when `overflow` allows. Throws `invalid_date`.
 */
export function resolveChild(
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
  const chosen = regime === null ? activeRegime(calendar, t) : regimeById(calendar, regime)
  const top = defined(levels.at(-1))
  const year = BigInt(defined(fields[top]))
  let template = chosen.yearTemplate(year)
  const normalized: Record<string, string> = { [top]: year.toString() }
  for (let level = levels.length - 2; level >= calendar.levelIndex(precision); level--) {
    const id = defined(levels[level])
    const child = resolveChild(calendar, chosen, template, level, defined(fields[id]), 'reject')
    // Named units by slot id (intercalary ones have no number); unnamed ones are never intercalary.
    normalized[id] =
      child.segment.slotId ??
      (defined(childRegularIndex(child)) + defined(calendar.numberingStarts[level])).toString()
    template = chosen.template(defined(child.segment.child))
  }
  return normalized
}

// --- picker options (§6) -------------------------------------------------------------------------

/** A named child: by slot id, with its regular number (`null` if intercalary). */
export interface SlotOption {
  readonly kind: 'slot'
  readonly slotId: string
  readonly n: bigint | null
  readonly name: string | null
  readonly intercalary: boolean
}

/** Unnamed children numbered `first … last` (`null` bounds: any year). */
export interface RangeOption {
  readonly kind: 'range'
  readonly first: bigint | null
  readonly last: bigint | null
}

export type Option = SlotOption | RangeOption

/**
 * The valid children at `level` given the parents `fields` (top level down to the level just
 * above), in template order: named slots one by one, unnamed runs as ranges.
 */
export function options(
  calendar: CompiledCalendar,
  fields: FieldsInput,
  level: string,
  { regime = null }: { readonly regime?: string | null } = {},
): Option[] {
  const index = calendar.levelIndex(level)
  if (index < 0) throw new DateError('invalid_date', `unknown level ${level}`, level)
  const top = calendar.levels.length - 1
  if (index === top) {
    if (Object.keys(fields).length > 0) {
      throw new DateError('invalid_date', 'the top level has no parents', level)
    }
    return [{ kind: 'range', first: null, last: null }]
  }
  const parent = defined(calendar.levels[index + 1])
  const start = fromFields(calendar, fields, parent, { regime })
  const chosen = regime === null ? activeRegime(calendar, start) : regimeById(calendar, regime)
  const template = templateAt(calendar, chosen, start, index + 1)
  const numbering = defined(calendar.numberingStarts[index])
  return template.segments.map((segment): Option => {
    if (segment.slotId !== null) {
      const n = segment.intercalary ? null : segment.regularStart + numbering
      const { slotId, name, intercalary } = segment
      return { kind: 'slot', slotId, n, name, intercalary }
    }
    const first = segment.regularStart + numbering
    return { kind: 'range', first, last: first + segment.count - 1n }
  })
}

/** The template of the `level` unit starting at `t`. */
function templateAt(
  calendar: CompiledCalendar,
  regime: CompiledRegime,
  t: bigint,
  level: number,
): CompiledTemplate {
  const rel = t - regime.epoch
  const year = regime.yearOfRel(rel)
  let template = regime.yearTemplate(year)
  let offset = rel - regime.relStart(year)
  for (let parent = calendar.levels.length - 1; parent > level; parent--) {
    const child = template.childAt(offset)
    offset -= child.offset
    template = regime.template(defined(child.segment.child))
  }
  return template
}

/** The conformance-vector form of `options` (README `options`). */
export function optionsToJson(found: readonly Option[]): Record<string, unknown>[] {
  const text = (value: bigint | null) => (value === null ? null : value.toString())
  return found.map((option) =>
    option.kind === 'slot'
      ? {
          kind: 'slot',
          value: option.slotId,
          n: text(option.n),
          name: option.name,
          intercalary: option.intercalary,
        }
      : { kind: 'range', first: text(option.first), last: text(option.last) },
  )
}
