/**
 * Preset calendars: instantiation for a dimension (chronology-engine.md §13). The Python twin is
 * backend/src/lore/chronology/presets.py. The presets themselves are bundled by the separate entry
 * point `@lore/chronology/presets` (`preset-library.ts`), so the engine doesn't carry them.
 *
 * Presets are written in seconds (level 0 is `second` with `uniform.count = 1`) and their absolute
 * time points are seconds after the origin. Instantiating one for a base unit of `p/q` seconds
 * keeps the first level whose templates all last a whole number of base units, turns it into
 * level 0 and drops the finer levels; absolute moments become `origin + floor(seconds·q/p)` and
 * overlay periods are scaled exactly.
 */
import { defined } from './calendar/compiled'
import { parsePattern } from './calendar/formats'
import { type BigRational, floorDiv, rational, rationalMul } from './numbers'
import type {
  CalendarDefinition,
  DefinitionTimePoint,
  Level,
  Preset,
  Regime,
  Template,
  TimePoint,
} from './schema.gen'

export type PresetErrorCode = 'preset.incompatible_base_unit'

/** A preset that can't be instantiated as asked. */
export class PresetError extends Error {
  constructor(
    readonly code: PresetErrorCode,
    message: string,
  ) {
    super(message)
    this.name = 'PresetError'
  }
}

type Fields = Record<string, string | undefined>

/**
 * The preset's definition for a dimension whose base unit lasts `secondsPerBaseUnit` seconds.
 * `origin` is the moment (in base units) at which the preset's alignment unit starts, e.g. the
 * start of 1 January AD 1 for the Gregorian preset. Throws `preset.incompatible_base_unit` when no
 * level lasts a whole number of base units in every template, or when the levels to drop are
 * needed (a cycle on them, or a date that isn't at the start of such a unit).
 */
export function instantiatePreset(
  preset: Preset,
  secondsPerBaseUnit: BigRational,
  options: { readonly origin?: bigint } = {},
): CalendarDefinition {
  const origin = options.origin ?? 0n
  const { num: p, den: q } = secondsPerBaseUnit
  if (p <= 0n) {
    throw new PresetError('preset.incompatible_base_unit', 'a base unit must be longer than 0')
  }
  const definition = structuredClone(preset.definition)
  const levels = definition.levels.map((level) => level.id)
  const lengths = definition.regimes.map((regime) => templateLengths(definition, regime))
  const keep = levels.findIndex((level) =>
    definition.regimes.every((regime, r) =>
      Object.entries(regime.templates).every(
        ([id, template]) =>
          template?.level !== level || (defined(lengths[r]?.get(id)) * q) % p === 0n,
      ),
    ),
  )
  if (keep < 0) {
    throw new PresetError(
      'preset.incompatible_base_unit',
      `no level of ${preset.id} lasts a whole number of ${p}/${q} s units`,
    )
  }
  const level0 = defined(levels[keep])
  const dropped = new Map<string, Level>(
    definition.levels.slice(0, keep).map((level) => [level.id, level]),
  )
  definition.levels = definition.levels.slice(keep) as CalendarDefinition['levels']
  definition.regimes.forEach((regime, r) => {
    scaleRegime(regime, defined(lengths[r]), level0, dropped, secondsPerBaseUnit)
  })
  for (const fields of structuralFields(definition)) dropFields(fields, dropped)
  for (const [, point] of pointedTimePoints(definition)) {
    const anchor = point.anchor
    if (anchor.kind === 'local') dropFields(anchor.fields, dropped)
    else if (anchor.kind === 'absolute') {
      anchor.t = (origin + floorDiv(BigInt(anchor.t) * q, p)).toString()
    }
    if (dropped.has(point.precision)) point.precision = level0
  }
  for (const overlay of definition.overlays ?? []) {
    const period = rational(BigInt(overlay.period.num), BigInt(overlay.period.den))
    const scaled = rationalMul(period, rational(q, p))
    overlay.period = { num: scaled.num.toString(), den: scaled.den.toString() }
  }
  dropFormats(definition, dropped)
  return definition
}

/** `CompileContext.resolved` for a definition whose non-local anchors are all absolute. */
export function absoluteMoments(definition: CalendarDefinition): Record<string, string> {
  const moments: Record<string, string> = {}
  for (const [pointer, point] of pointedTimePoints(definition)) {
    if (point.anchor.kind === 'absolute') moments[pointer] = point.anchor.t
  }
  return moments
}

// --- helpers -------------------------------------------------------------------------------------

/** Length in seconds (level-0 children are one second each) of every template. */
function templateLengths(definition: CalendarDefinition, regime: Regime): Map<string, bigint> {
  const levels = definition.levels.map((level) => level.id)
  const defaults = new Map(definition.levels.map((level) => [level.id, level.default_template]))
  const memo = new Map<string, bigint>()
  const length = (id: string): bigint => {
    const cached = memo.get(id)
    if (cached !== undefined) return cached
    const template = defined(regime.templates[id])
    const index = levels.indexOf(template.level)
    const child = (explicit: string | null | undefined): bigint =>
      index === 0 ? 1n : length(defined(explicit ?? defaults.get(defined(levels[index - 1]))))
    let total = 0n
    if ('uniform' in template) {
      total = BigInt(template.uniform.count) * child(template.uniform.template)
    } else {
      for (const item of template.sequence) {
        total +=
          'run' in item ? BigInt(item.run.count) * child(item.run.template) : child(item.template)
      }
    }
    memo.set(id, total)
    return total
  }
  return new Map(Object.keys(regime.templates).map((id) => [id, length(id)]))
}

function scaleRegime(
  regime: Regime,
  lengths: ReadonlyMap<string, bigint>,
  level0: string,
  dropped: ReadonlyMap<string, Level>,
  unit: BigRational,
): void {
  for (const cycle of regime.cycles ?? []) {
    if (dropped.has(cycle.level)) {
      throw new PresetError(
        'preset.incompatible_base_unit',
        `cycle ${cycle.id} needs ${cycle.level}`,
      )
    }
  }
  const templates: Record<string, Template> = {}
  for (const [id, template] of Object.entries(regime.templates)) {
    if (template === undefined || dropped.has(template.level)) continue
    if (template.level === level0) {
      // the level was chosen so that the count is whole
      const count = (defined(lengths.get(id)) * unit.den) / unit.num
      templates[id] = { level: level0, uniform: { count: count.toString() } }
    } else {
      templates[id] = template
    }
  }
  regime.templates = templates
}

/** Remove the dropped levels from date fields; they must name the first unit. */
function dropFields(fields: Fields, dropped: ReadonlyMap<string, Level>): void {
  for (const [level, value] of Object.entries(fields)) {
    const definition = dropped.get(level)
    if (definition === undefined) continue
    if (value !== String(definition.numbering_start ?? 1)) {
      throw new PresetError(
        'preset.incompatible_base_unit',
        `a date needs ${level} ${String(value)}, finer than a unit`,
      )
    }
    // eslint-disable-next-line @typescript-eslint/no-dynamic-delete -- date fields are a record
    delete fields[level]
  }
}

/** The date fields of alignments and cycle anchors (time points come separately). */
function* structuralFields(definition: CalendarDefinition): Generator<Fields> {
  for (const regime of definition.regimes) {
    yield regime.alignment.fields
    for (const cycle of regime.cycles ?? []) {
      if (cycle.anchor?.fields != null) yield cycle.anchor.fields
    }
  }
}

/** (JSON pointer, time point) for every time point of a definition (§3.10). */
function* pointedTimePoints(
  definition: CalendarDefinition,
): Generator<readonly [string, TimePoint | DefinitionTimePoint]> {
  for (const [r, regime] of definition.regimes.entries()) {
    yield [`/regimes/${r}/alignment/at`, regime.alignment.at]
    if (regime.starts_at != null) yield [`/regimes/${r}/starts_at`, regime.starts_at]
  }
  for (const [e, era] of (definition.eras ?? []).entries()) {
    if (era.start != null) yield [`/eras/${e}/start`, era.start]
  }
  for (const [o, overlay] of (definition.overlays ?? []).entries()) {
    yield [`/overlays/${o}/epoch`, overlay.epoch]
  }
}

/** Remove the formats of dropped precisions and the patterns using dropped levels. */
function dropFormats(definition: CalendarDefinition, dropped: ReadonlyMap<string, Level>): void {
  const custom = definition.formats
  if (custom == null) return
  const keep = (key: string, pattern: string): boolean =>
    !dropped.has(key) &&
    !parsePattern(pattern).some(
      (piece) => typeof piece !== 'string' && piece.kind === 'level' && dropped.has(piece.id ?? ''),
    )
  const kept: NonNullable<CalendarDefinition['formats']> = {}
  for (const [key, value] of Object.entries(custom)) {
    if (key !== 'intercalary' && typeof value === 'string' && keep(key, value)) kept[key] = value
  }
  if (custom.intercalary !== undefined) {
    const intercalary: Record<string, string> = {}
    for (const [key, value] of Object.entries(custom.intercalary)) {
      if (value !== undefined && keep(key, value)) intercalary[key] = value
    }
    kept.intercalary = intercalary
  }
  definition.formats = kept
}
