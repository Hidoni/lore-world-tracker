import {
  type CalendarDefinition,
  type CalendarRule,
  type CompiledCalendar,
  type Cycle,
  type LevelSelector,
  type Limit,
  type PeriodFilter,
  type RecurrenceRule,
  type TimePoint,
  formatInteger,
  toFields,
} from '@lore/chronology'

/** The presets of the recurrence editor (recurrence.md §10); `custom` is the advanced mode. */
export type PresetId = 'yearly' | 'monthly' | 'nth_weekday' | 'weekly' | 'interval' | 'custom'

/** What presets and summaries read: the rule's calendar and the series start. */
export interface RuleScope {
  calendarId: string | null
  calendar: CompiledCalendar | null
  /** The resolved series start (`null`: not set yet). */
  start: bigint | null
  /** The dimension's base unit, for interval rules. */
  baseUnit: { singular: string; plural: string }
}

const NEVER: Limit = { kind: 'never' }

/** Levels coarse to fine (the top first). */
function levelsDown(calendar: CompiledCalendar): string[] {
  return [...calendar.levels].reverse()
}

function levelDef(definition: CalendarDefinition, id: string) {
  return definition.levels.find((level) => level.id === id)
}

/** The continuous cycles of the calendar (only those can be a period, §2.1), by level. */
export function continuousCycles(calendar: CompiledCalendar): Cycle[] {
  const seen = new Set<string>()
  return calendar.definition.regimes.flatMap((regime) =>
    (regime.cycles ?? []).filter((cycle) => {
      if (seen.has(cycle.id)) return false
      seen.add(cycle.id)
      return cycle.mode === undefined || cycle.mode === 'continuous'
    }),
  )
}

/** Every cycle of the calendar (filters and selectors may use reset cycles too). */
export function allCycles(calendar: CompiledCalendar): Cycle[] {
  const seen = new Map<string, Cycle>()
  for (const regime of calendar.definition.regimes) {
    for (const cycle of regime.cycles ?? []) if (!seen.has(cycle.id)) seen.set(cycle.id, cycle)
  }
  return [...seen.values()]
}

/** A cycle position's value id (`ids`), else its number (`index + number_start`). */
export function cycleValueId(cycle: Cycle, index: number): string {
  return cycle.ids?.[index] ?? String(index + (cycle.number_start ?? 1))
}

/** The display name of a cycle value id or number. */
export function cycleValueName(cycle: Cycle, value: string): string {
  const byId = cycle.ids?.indexOf(value) ?? -1
  const index = byId >= 0 ? byId : Number(value) - (cycle.number_start ?? 1)
  return cycle.names?.[index] ?? value
}

/** The name of a slot id at a level (any template of any regime), else the id. */
export function slotName(definition: CalendarDefinition, level: string, id: string): string {
  for (const regime of definition.regimes) {
    for (const template of Object.values(regime.templates)) {
      if (template === undefined || !('sequence' in template)) continue
      for (const child of template.sequence) {
        if ('id' in child && child.id === id) {
          const childLevel = regime.templates[child.template]?.level
          if (childLevel === undefined || childLevel === level) return child.name
        }
      }
    }
  }
  return id
}

interface StartParts {
  /** Per level: the regular number (as a string) or `null` for an intercalary unit. */
  numbers: Map<string, string | null>
  slots: Map<string, string | null>
  /** Per cycle id: its index at the start (`null`: excluded). */
  cycles: Map<string, number | null>
}

function startParts(calendar: CompiledCalendar, start: bigint): StartParts | null {
  try {
    const fields = toFields(calendar, start)
    const numbers = new Map<string, string | null>()
    const slots = new Map<string, string | null>()
    for (const [level, value] of fields.levels) {
      numbers.set(level, value.n === null ? null : value.n.toString())
      slots.set(level, value.slotId)
    }
    const cycles = new Map<string, number | null>()
    for (const [id, value] of fields.cycles) cycles.set(id, value?.index ?? null)
    return { numbers, slots, cycles }
  } catch {
    return null
  }
}

/** The weekday-like cycle of the level just below the second-highest one (days of months). */
function dayCycle(calendar: CompiledCalendar): Cycle | null {
  const levels = levelsDown(calendar)
  const day = levels[2]
  return continuousCycles(calendar).find((cycle) => cycle.level === day) ?? null
}

/** Which presets this calendar supports (`interval` and `custom` always). */
export function availablePresets(scope: RuleScope): PresetId[] {
  const calendar = scope.calendar
  if (calendar === null) return ['interval', 'custom']
  const levels = calendar.levels.length
  const found: PresetId[] = ['yearly']
  if (levels >= 3) found.push('monthly')
  if (levels >= 3 && dayCycle(calendar) !== null) found.push('nth_weekday')
  if (continuousCycles(calendar).length > 0) found.push('weekly')
  found.push('interval', 'custom')
  return found
}

export interface PresetOptions {
  /** Weekly: the cycle values (default: the start's). */
  weekdays?: readonly string[]
  /** Every N periods (yearly, monthly, weekly) or base units (interval). */
  every?: string
  limit?: Limit
}

/**
 * A preset's rule for the series start (recurrence.md §10): "yearly on this date" (the top level,
 * `select: null`), "monthly on day N", "the nth <weekday> of the month", "weekly on these days" (a
 * continuous cycle's rounds), "every N base units". `null` when the calendar or start can't
 * support it.
 */
export function presetRule(
  preset: PresetId,
  scope: RuleScope,
  options: PresetOptions = {},
): RecurrenceRule | null {
  const limit = options.limit ?? NEVER
  const every = options.every ?? '1'
  if (preset === 'interval') {
    return { kind: 'interval', every: options.every ?? '86400', limit }
  }
  const { calendar, calendarId, start } = scope
  if (calendar === null || calendarId === null || start === null) return null
  const levels = levelsDown(calendar)
  const parts = startParts(calendar, start)
  const base = (freq: CalendarRule['freq']): CalendarRule => ({
    kind: 'calendar',
    calendar_id: calendarId,
    freq,
    ...(every === '1' ? {} : { interval: every }),
    limit,
  })
  const [top, second, third] = levels
  switch (preset) {
    case 'yearly':
      return top === undefined ? null : base({ level: top })
    case 'monthly': {
      if (second === undefined || third === undefined || parts === null) return null
      const day = parts.numbers.get(third) ?? null
      if (day === null) return null
      return { ...base({ level: second }), select: { path: [{ level: third, values: [day] }] } }
    }
    case 'nth_weekday': {
      const cycle = dayCycle(calendar)
      if (second === undefined || third === undefined || cycle === null || parts === null) {
        return null
      }
      const index = parts.cycles.get(cycle.id) ?? null
      const day = parts.numbers.get(third) ?? null
      if (index === null || day === null) return null
      const first = levelDef(calendar.definition, third)?.numbering_start ?? 1
      const nth = Math.floor((Number(day) - first) / cycle.length) + 1
      return {
        ...base({ level: second }),
        select: {
          path: [
            {
              level: third,
              cycle: { id: cycle.id, values: [cycleValueId(cycle, index)], nth: [String(nth)] },
            },
          ],
        },
      }
    }
    case 'weekly': {
      const cycle = continuousCycles(calendar)[0]
      if (cycle === undefined) return null
      const index = parts?.cycles.get(cycle.id) ?? null
      const values =
        options.weekdays !== undefined && options.weekdays.length > 0
          ? [...options.weekdays]
          : index === null
            ? [cycleValueId(cycle, 0)]
            : [cycleValueId(cycle, index)]
      return {
        ...base({ cycle: cycle.id }),
        select: {
          path: [
            {
              level: cycle.level,
              cycle: { id: cycle.id, values: values as [string, ...string[]] },
            },
          ],
        },
      }
    }
    default:
      return null
  }
}

/** The preset a rule is (the editor opens on it), else `custom`. */
export function detectPreset(rule: RecurrenceRule, scope: RuleScope): PresetId {
  if (rule.kind === 'interval') {
    return (rule.exclusions ?? []).length === 0 ? 'interval' : 'custom'
  }
  const plain =
    (rule.filters ?? []).length === 0 &&
    (rule.exclusions ?? []).length === 0 &&
    rule.time == null &&
    (rule.missing ?? 'skip') === 'skip'
  if (!plain) return 'custom'
  const options = {
    limit: rule.limit,
    ...(rule.interval === undefined ? {} : { every: rule.interval }),
  }
  for (const preset of ['yearly', 'monthly', 'nth_weekday'] as const) {
    const candidate = presetRule(preset, scope, options)
    if (candidate !== null && sameRule(candidate, rule)) return preset
  }
  if ('cycle' in rule.freq) {
    const selector = rule.select?.path[0]
    if (
      rule.select?.path.length === 1 &&
      selector !== undefined &&
      'cycle' in selector &&
      selector.cycle.id === rule.freq.cycle &&
      (selector.cycle.nth ?? null) === null
    ) {
      return 'weekly'
    }
  }
  return 'custom'
}

/** Members at their default value (recurrence.md §2), which stored rules spell out. */
const DEFAULTS: Record<string, unknown> = {
  schema_version: 1,
  interval: '1',
  missing: 'skip',
  of: 'number',
}

function sameRule(a: RecurrenceRule, b: RecurrenceRule): boolean {
  const normal = (rule: RecurrenceRule) =>
    JSON.stringify(rule, (key, value: unknown) =>
      value === null ||
      (Array.isArray(value) && value.length === 0) ||
      (key in DEFAULTS && DEFAULTS[key] === value)
        ? undefined
        : value,
    )
  return normal(a) === normal(b)
}

// --- summaries -----------------------------------------------------------------------------------

const ORDINALS = ['first', 'second', 'third', 'fourth', 'fifth']

/** `1` → first, `-1` → last, `-2` → second to last, `7` → 7th. */
function nthWord(value: string): string {
  const n = Number(value)
  if (n < 0) return n === -1 ? 'last' : `${nthWord(String(-n))} to last`
  return ORDINALS[n - 1] ?? `${value}th`
}

function list(items: readonly string[], joiner = 'and'): string {
  if (items.length <= 1) return items.join('')
  return `${items.slice(0, -1).join(', ')} ${joiner} ${items.at(-1) ?? ''}`
}

function plural(
  definition: CalendarDefinition,
  level: string,
  count: bigint | string | number,
): string {
  const def = levelDef(definition, level)
  const one = String(count) === '1'
  return ((one ? def?.label : def?.plural) ?? level).toLowerCase()
}

function valueText(definition: CalendarDefinition, level: string, value: string): string {
  if (/^-?\d+$/.test(value)) {
    return Number(value) < 0 ? `the ${nthWord(value)} ${plural(definition, level, 1)}` : value
  }
  return slotName(definition, level, value)
}

function selectorText(calendar: CompiledCalendar, selector: LevelSelector): string {
  const definition = calendar.definition
  const label = plural(definition, selector.level, 1)
  if ('all' in selector) return `every ${label}`
  if ('cycle' in selector) {
    const cycle = allCycles(calendar).find((each) => each.id === selector.cycle.id)
    const names = selector.cycle.values.map((value) =>
      cycle === undefined ? value : cycleValueName(cycle, value),
    )
    const nth = selector.cycle.nth
    if (nth == null || nth.length === 0) return list(names)
    return `the ${list(nth.map(nthWord))} ${list(names, 'and')}`
  }
  const numbered = selector.values.every((value) => /^\d+$/.test(value))
  const values = selector.values.map((value) => valueText(definition, selector.level, value))
  return numbered ? `${label} ${list(values)}` : list(values)
}

function filterText(calendar: CompiledCalendar, filter: PeriodFilter, unit: string): string {
  if ('mod' in filter) {
    if (filter.mod === '2' && (filter.of ?? 'number') === 'number') {
      return filter.eq === '1' ? `odd ${unit}s only` : `even ${unit}s only`
    }
    const what = filter.of === 'ordinal' ? 'ordinal' : 'number'
    return `${unit}s whose ${what} is ${filter.eq} modulo ${filter.mod}`
  }
  if ('cycle' in filter) {
    const cycle = allCycles(calendar).find((each) => each.id === filter.cycle)
    return `only on ${list(
      filter.in.map((value) => (cycle === undefined ? value : cycleValueName(cycle, value))),
      'or',
    )}`
  }
  if ('in' in filter) return `only ${unit}s ${list(filter.in, 'or')}`
  if ('all' in filter)
    return filter.all.map((inner) => filterText(calendar, inner, unit)).join(', ')
  if ('any' in filter) {
    return `either ${list(
      filter.any.map((inner) => filterText(calendar, inner, unit)),
      'or',
    )}`
  }
  return `not ${filterText(calendar, filter.not, unit)}`
}

/** The start's own position below `level` ("on 10 March"), coarse levels last. */
function startPosition(calendar: CompiledCalendar, start: bigint, level: string): string | null {
  const parts = startParts(calendar, start)
  if (parts === null) return null
  const levels = levelsDown(calendar)
  const below = levels.slice(levels.indexOf(level) + 1, levels.indexOf(level) + 3)
  const words = below
    .map((id) => {
      const slot = parts.slots.get(id) ?? null
      if (slot !== null) return slotName(calendar.definition, id, slot)
      const n = parts.numbers.get(id) ?? null
      return n === null ? null : `${plural(calendar.definition, id, 1)} ${n}`
    })
    .filter((word): word is string => word !== null)
  return words.length === 0 ? null : words.reverse().join(' of ')
}

export interface SummaryOptions {
  /** How to name the `until` time point ("the Fall of the Empire", a date). */
  until?: string | null
}

/**
 * The rule in words (recurrence.md §10): "Every year on day 10 of March, odd years only, until 5
 * May 1200". Calendar names and slot names come from the calendar.
 */
export function summarize(
  rule: RecurrenceRule,
  scope: RuleScope,
  options: SummaryOptions = {},
): string {
  const parts: string[] = []
  if (rule.kind === 'interval') {
    const n = BigInt(rule.every)
    const unit = n === 1n ? scope.baseUnit.singular : scope.baseUnit.plural
    parts.push(`Every ${formatInteger(n)} ${unit.toLowerCase()}`)
  } else {
    const calendar = scope.calendar
    if (calendar === null) return 'A rule in a calendar this page can’t read.'
    const definition = calendar.definition
    const interval = rule.interval ?? '1'
    const unit =
      'level' in rule.freq ? plural(definition, rule.freq.level, 1) : rule.freq.cycle.toLowerCase()
    const units =
      'level' in rule.freq
        ? plural(definition, rule.freq.level, interval)
        : `${rule.freq.cycle.toLowerCase()}s`
    let head = interval === '1' ? `Every ${unit}` : `Every ${interval} ${units}`
    if (rule.select != null) {
      const path = [...rule.select.path]
        .reverse()
        .map((selector) => selectorText(calendar, selector))
      head += ` on ${path.join(' of ')}`
    } else if ('level' in rule.freq && scope.start !== null) {
      const position = startPosition(calendar, scope.start, rule.freq.level)
      if (position !== null) head += ` on ${position}`
    }
    if (rule.time != null) {
      const fields = levelsDown(calendar)
        .filter((level) => rule.time?.fields[level] !== undefined)
        .map((level) => `${plural(definition, level, 1)} ${rule.time?.fields[level] ?? ''}`)
      if (fields.length > 0) head += ` at ${fields.join(', ')}`
    }
    parts.push(head)
    for (const filter of rule.filters ?? []) parts.push(filterText(calendar, filter, unit))
    if (rule.missing === 'constrain') parts.push('on the nearest date when the day doesn’t exist')
  }
  const limit = rule.limit
  if (limit.kind === 'count') {
    parts.push(limit.count === '1' ? 'once' : `${formatInteger(BigInt(limit.count))} times`)
  } else if (limit.kind === 'until') {
    parts.push(`until ${options.until ?? 'a set time'}`)
  }
  const exclusions = rule.exclusions?.length ?? 0
  if (exclusions > 0) {
    parts.push(
      `except ${exclusions === 1 ? 'one excluded range' : `${exclusions} excluded ranges`}`,
    )
  }
  return `${parts.join(', ')}.`
}

// --- time points of a rule -------------------------------------------------------------------------

/** The rule's time points by JSON pointer (`/limit/until`, `/exclusions/0/from` …). */
export function ruleTimePoints(rule: RecurrenceRule): [string, TimePoint][] {
  const found: [string, TimePoint][] = []
  if (rule.limit.kind === 'until') found.push(['/limit/until', rule.limit.until])
  for (const [index, exclusion] of (rule.exclusions ?? []).entries()) {
    found.push([`/exclusions/${index}/from`, exclusion.from])
    found.push([`/exclusions/${index}/to`, exclusion.to])
  }
  return found
}
