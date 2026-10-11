import type {
  CalendarDefinition,
  Level,
  Predicate,
  Regime,
  SequenceChild,
  Template,
  TimePoint,
  ValidationError,
  YearPattern,
} from '@lore/chronology'

/**
 * The calendar editor's model: the definition document itself (chronology-engine.md §3), edited
 * through small immutable updates. The structure editors work on the first regime; further
 * regimes, cycles, eras, overlays and formats are kept as they are (their editors arrive with
 * #77, the JSON tab edits everything).
 */
export type Definition = CalendarDefinition

/** Ids of levels, templates, eras and cycles; slot and regime ids also allow `-`. */
export const ID_PATTERN = /^[a-z][a-z0-9_]*$/
export const SLOT_PATTERN = /^[a-z][a-z0-9_-]*$/

/** A copy of `definition` changed by `recipe` (which mutates the copy). */
export function edit(definition: Definition, recipe: (draft: Definition) => void): Definition {
  const draft = structuredClone(definition)
  recipe(draft)
  return draft
}

export function levelsOf(definition: Definition): Level[] {
  return definition.levels
}

/** `value` without `key`. */
export function omit<T extends object, K extends keyof T>(value: T, key: K): Omit<T, K> {
  return Object.fromEntries(Object.entries(value).filter(([name]) => name !== key)) as Omit<T, K>
}

/** A record without `key` (for computed keys). */
export function omitKey<V>(record: Record<string, V>, key: string): Record<string, V> {
  return Object.fromEntries(Object.entries(record).filter(([name]) => name !== key))
}

/** A regime by index (the first by default). */
export function regimeOf(definition: Definition, index = 0): Regime {
  const regime = definition.regimes[index] ?? definition.regimes[0]
  return regime
}

/** The JSON pointer of a regime. */
export function regimePath(index: number): string {
  return `/regimes/${index}`
}

/** The ids of the templates of `regime` at `level`, in the document's order. */
export function templatesAt(regime: Regime, level: string): string[] {
  return Object.entries(regime.templates)
    .filter((entry): entry is [string, Template] => entry[1]?.level === level)
    .map(([id]) => id)
}

/** The level one finer than `level` (`null` for level 0). */
export function childLevel(definition: Definition, level: string): string | null {
  const levels = levelsOf(definition)
  const index = levels.findIndex((candidate) => candidate.id === level)
  return index > 0 ? (levels[index - 1]?.id ?? null) : null
}

/** A calendar to start from: a year of 360 days, the year 1 beginning at the inception. */
export function blankDefinition(): Definition {
  const at: TimePoint = { anchor: { kind: 'absolute', t: '0' }, precision: 'base' }
  return {
    schema_version: 1,
    levels: [
      {
        id: 'day',
        label: 'day',
        plural: 'days',
        abbr: 'd',
        numbering_start: 1,
        default_template: 'day',
      },
      { id: 'year', label: 'year', plural: 'years', abbr: 'y' },
    ],
    regimes: [
      {
        id: 'main',
        name: 'Main',
        templates: {
          day: { level: 'day', uniform: { count: '1' } },
          year: { level: 'year', uniform: { count: '360', template: 'day' } },
        },
        top: { pattern: { kind: 'fixed', template: 'year' } },
        alignment: { fields: { year: '1' }, at },
      },
    ],
  }
}

/** A new level id not used yet (`level`, `level_2`, …). */
export function freshId(taken: Iterable<string>, base: string): string {
  const used = new Set(taken)
  if (!used.has(base)) return base
  for (let n = 2; ; n++) if (!used.has(`${base}_${n}`)) return `${base}_${n}`
}

/** A new uniform template at `level` (its child template defaults to the child level's). */
export function newTemplate(level: string): Template {
  return { level, uniform: { count: '1' } }
}

export function newChild(kind: 'slot' | 'run', template: string): SequenceChild {
  return kind === 'slot'
    ? { id: 'slot', template, name: 'Slot' }
    : { run: { count: '1', ...(template === '' ? {} : { template }) } }
}

export function newPattern(kind: YearPattern['kind'], template: string): YearPattern {
  switch (kind) {
    case 'fixed':
      return { kind, template }
    case 'cycle':
      return { kind, templates: [template], start: '1' }
    case 'rules':
      return { kind, default: template, rules: [] }
  }
}

export const NEW_PREDICATE: Predicate = { mod: '4', eq: '0' }

/** The slot ids that appear in more than one template (they keep typed dates across templates). */
export function sharedSlotIds(regime: Regime): Set<string> {
  const seen = new Map<string, number>()
  for (const template of Object.values(regime.templates)) {
    if (template === undefined || !('sequence' in template)) continue
    const ids = new Set(template.sequence.flatMap((child) => ('id' in child ? [child.id] : [])))
    for (const id of ids) seen.set(id, (seen.get(id) ?? 0) + 1)
  }
  return new Set([...seen].filter(([, count]) => count > 1).map(([id]) => id))
}

/** The errors at `path` or inside it. */
export function errorsAt(errors: readonly ValidationError[], path: string): ValidationError[] {
  return errors.filter((error) => error.path === path || error.path.startsWith(`${path}/`))
}

/** JSON pointer escaping of one part (`~` and `/`). */
export function part(text: string): string {
  return text.replaceAll('~', '~0').replaceAll('/', '~1')
}

/** Plain words for the engine's error codes (chronology-engine.md §11). */
const MESSAGES: Record<string, string> = {
  'level.duplicate_id': 'Another level has this id.',
  'level.invalid_id': 'Use lowercase letters, digits and _ (starting with a letter).',
  'level.too_many': 'At most 20 levels.',
  'template.unknown_level': 'Unknown level.',
  'template.child_level_mismatch': 'The child template belongs to another level.',
  'template.unknown_template': 'Unknown template.',
  'template.zero_length': 'Units must last at least one base unit.',
  'template.level0_not_uniform': 'The finest level must be uniform base units.',
  'template.duplicate_slot_id': 'Another unit of this template has this id.',
  'template.intercalary_without_id': 'Intercalary units need an id.',
  'template.too_large': 'Too many units.',
  'top.template_wrong_level': 'Years must use templates of the top level.',
  'top.unknown_template': 'Unknown template.',
  'top.period_too_large': 'The rules repeat too rarely (at most every 1,000,000 years).',
  'top.duplicate_exception': 'This year already has an exception.',
  'top.bad_predicate': 'The remainder must be smaller than the divisor.',
  'alignment.invalid_fields': 'Not a date of this calendar.',
  'alignment.self_reference': 'The alignment can’t use this calendar.',
  'regime.duplicate_id': 'Another set of rules has this id.',
  'regime.first_has_start': 'The first rules apply from the beginning: they have no start.',
  'regime.missing_start': 'A reform needs the date it starts.',
  'regime.start_not_increasing': 'A reform must start after the previous one.',
  'cycle.duplicate_id': 'Another cycle has this id.',
  'cycle.unknown_level': 'Unknown level.',
  'cycle.bad_reset_level': 'The cycle can only restart at a coarser level.',
  'cycle.duplicate_value_id': 'Two values of the cycle have the same id.',
  'cycle.names_length_mismatch': 'Give a name for each value of the cycle (as many as its length).',
  'cycle.anchor_invalid': 'Not a valid anchor for this cycle.',
  'era.duplicate_id': 'Another era has this id.',
  'era.first_has_start': 'The first era has no start: it covers everything before the second.',
  'era.missing_start': 'Every era after the first needs a start.',
  'era.start_not_increasing': 'An era must start after the previous one.',
  'era.forward_without_start': 'The first era can’t count forward: it has no start to count from.',
  'era.backward_without_end': 'The last era can’t count backward: it has no end to count to.',
  'era.local_anchor_uses_era': 'A date in the definition can’t use an era.',
  'overlay.duplicate_id': 'Another overlay has this id.',
  'overlay.bad_period': 'The period must be positive.',
  'overlay.phases_unsorted': 'List the phases in order of their start.',
  'format.unknown_level': 'Unknown level.',
  'format.unknown_token': 'Unknown token: type { to see the tokens.',
  'anchor.invalid_local': 'Not a date of this calendar.',
  'anchor.unresolved': 'Resolved when saved.',
  'anchor.out_of_bounds': 'Outside the dimension.',
}

export function errorMessage(error: ValidationError): string {
  if (error.code.startsWith('schema.')) return 'Missing or invalid value.'
  return MESSAGES[error.code] ?? error.message
}

/** Errors that block saving (an anchor the server resolves on save doesn't). */
export function blocking(errors: readonly ValidationError[]): ValidationError[] {
  return errors.filter((error) => error.code !== 'anchor.unresolved')
}
