/**
 * Calendar compilation: semantic validation and precomputation (chronology-engine.md §4). The
 * Python twin is backend/src/lore/chronology/calendar/compile.py.
 *
 * `compileCalendar` takes schema-valid documents and returns a `CompiledCalendar` or **all**
 * semantic errors (§11), each with a stable code and a JSON-pointer path. It reports root causes
 * only: checks that depend on an invalid part are skipped. `validateCalendar` takes raw JSON
 * documents and also reports structural (schema) errors first.
 *
 * Not yet compiled (later issues): `local` anchors, cycle values, eras and overlays (#24). They
 * are validated here as far as possible without resolving local anchors.
 */
import { floorDiv, floorMod, gcd } from '../numbers'
import type {
  CalendarDefinition,
  CompileContext,
  DefinitionTimePoint,
  NamedChild,
  Predicate,
  Regime,
  Template,
  TimePoint,
  YearPattern,
} from '../schema.gen'
import {
  type Child,
  CompiledCalendar,
  CompiledRegime,
  CompiledTemplate,
  type RegimeStructure,
  type Segment,
  bisectLeft,
  defined,
  isNumber,
  segmentRegularCount,
} from './compiled'
import { unknownTokens } from './formats'
import { type PathPart, type SchemaIssue, checkDocument } from './schema-check'

const RESERVED_LEVEL_IDS = new Set(['base', 'intercalary'])
const MAX_PERIOD = 1_000_000n

/** One definition error: a stable `code` (§11) and a JSON pointer `path`. */
export interface ValidationError {
  readonly code: string
  readonly path: string
  readonly message: string
}

/** A JSON pointer (RFC 6901) from path parts. */
export function pointer(...parts: readonly PathPart[]): string {
  return parts.map((part) => '/' + String(part).replace(/~/g, '~0').replace(/\//g, '~1')).join('')
}

/** Errors without duplicate (path, code) pairs, sorted by path, then code. */
function sortedErrors(errors: readonly ValidationError[]): ValidationError[] {
  const unique = new Map<string, ValidationError>()
  for (const error of errors) unique.set(`${error.path}\u0000${error.code}`, error)
  return [...unique.entries()].sort(([a], [b]) => (a < b ? -1 : 1)).map(([, error]) => error)
}

// --- compilation ---------------------------------------------------------------------------------

/** Compile a schema-valid definition, or return every semantic error (sorted by path). */
export function compileCalendar(
  definition: CalendarDefinition,
  context: CompileContext,
): CompiledCalendar | ValidationError[] {
  return new Compiler(definition, context).run()
}

type Path = readonly PathPart[]

class Compiler {
  readonly errors: ValidationError[] = []
  readonly levels: readonly string[]
  readonly levelIndex: ReadonlyMap<string, number>
  readonly numbering: readonly bigint[]
  readonly resolvedMoments: Readonly<Record<string, string | undefined>>

  constructor(
    readonly definition: CalendarDefinition,
    readonly context: CompileContext,
  ) {
    this.levels = definition.levels.map((level) => level.id)
    this.levelIndex = new Map(this.levels.map((id, i) => [id, i]))
    this.numbering = definition.levels.map((level) => BigInt(level.numbering_start ?? 1))
    this.resolvedMoments = context.resolved ?? {}
  }

  error(code: string, path: string, message: string): void {
    this.errors.push({ code, path, message })
  }

  resolved(path: string): bigint | null {
    const value = Object.hasOwn(this.resolvedMoments, path) ? this.resolvedMoments[path] : undefined
    return value === undefined ? null : BigInt(value)
  }

  run(): CompiledCalendar | ValidationError[] {
    this.checkLevels()
    if (this.errors.length > 0) return sortedErrors(this.errors) // everything else uses levels
    this.checkRegimes()
    this.checkTimePoints()
    this.checkEras()
    this.checkOverlays()
    const regimes = this.definition.regimes.map((regime, r) => this.compileRegime(r, regime))
    this.checkFormats()
    if (this.errors.length > 0) return sortedErrors(this.errors)
    return new CompiledCalendar(
      this.definition,
      this.context,
      this.levels,
      this.numbering,
      regimes.filter((regime) => regime !== null),
    )
  }

  // --- levels, regimes, eras, overlays, time points ---------------------------------------

  checkLevels(): void {
    const seen = new Set<string>()
    this.definition.levels.forEach((level, i) => {
      const path = pointer('levels', i, 'id')
      if (RESERVED_LEVEL_IDS.has(level.id)) {
        this.error('level.invalid_id', path, `level id ${level.id} is reserved`)
      }
      if (seen.has(level.id)) this.error('level.duplicate_id', path, `duplicate level ${level.id}`)
      seen.add(level.id)
    })
  }

  /** Unique ids; item 0 starts at −∞ (`null`), later ones at strictly increasing moments. */
  orderedStarts(
    kind: 'regime' | 'era',
    items: readonly (readonly [string, DefinitionTimePoint | null | undefined])[],
    member: string,
  ): void {
    const seen = new Set<string>()
    let last: bigint | null = null
    const plural = `${kind}s`
    items.forEach(([id, start], i) => {
      if (seen.has(id)) this.error(`${kind}.duplicate_id`, pointer(plural, i, 'id'), 'duplicate id')
      seen.add(id)
      const path = pointer(plural, i, member)
      if (i === 0) {
        if (start != null)
          this.error(`${kind}.first_has_start`, path, `the first ${kind} has no start`)
        return
      }
      if (start == null) {
        this.error(`${kind}.missing_start`, path, `every ${kind} after the first needs a start`)
        return
      }
      if (start.anchor.kind === 'local') return // resolved with the compiled structure (#24)
      const value = this.resolved(path)
      if (value === null) return // anchor.unresolved
      if (last !== null && value <= last) {
        this.error(`${kind}.start_not_increasing`, path, `${kind} starts must increase`)
      }
      last = value
    })
  }

  checkRegimes(): void {
    this.orderedStarts(
      'regime',
      this.definition.regimes.map((regime) => [regime.id, regime.starts_at] as const),
      'starts_at',
    )
  }

  checkEras(): void {
    this.orderedStarts(
      'era',
      (this.definition.eras ?? []).map((era) => [era.id, era.start] as const),
      'start',
    )
  }

  checkOverlays(): void {
    const seen = new Set<string>()
    ;(this.definition.overlays ?? []).forEach((overlay, i) => {
      if (seen.has(overlay.id)) {
        this.error('overlay.duplicate_id', pointer('overlays', i, 'id'), 'duplicate id')
      }
      seen.add(overlay.id)
      if (BigInt(overlay.period.num) <= 0n) {
        this.error('overlay.bad_period', pointer('overlays', i, 'period'), 'period must be > 0')
      }
      let previous: readonly [bigint, bigint] | null = null
      overlay.phases.forEach((phase, k) => {
        const a = BigInt(phase.from.num)
        const b = BigInt(phase.from.den)
        const inRange = a >= 0n && a < b && (k > 0 || a === 0n)
        const increasing = previous === null || a * previous[1] > previous[0] * b
        if (!(inRange && increasing)) {
          const path = pointer('overlays', i, 'phases', k, 'from')
          this.error('overlay.phases_unsorted', path, 'phases start at 0, increase, stay < 1')
        }
        previous = [a, b]
      })
    })
  }

  *timePoints(): Generator<readonly [Path, TimePoint | DefinitionTimePoint]> {
    for (const [r, regime] of this.definition.regimes.entries()) {
      yield [['regimes', r, 'alignment', 'at'], regime.alignment.at]
      if (regime.starts_at != null) yield [['regimes', r, 'starts_at'], regime.starts_at]
    }
    for (const [e, era] of (this.definition.eras ?? []).entries()) {
      if (era.start != null) yield [['eras', e, 'start'], era.start]
    }
    for (const [o, overlay] of (this.definition.overlays ?? []).entries()) {
      yield [['overlays', o, 'epoch'], overlay.epoch]
    }
  }

  checkTimePoints(): void {
    for (const [parts, point] of this.timePoints()) {
      const anchor = point.anchor
      if (anchor.kind === 'local') continue
      const path = pointer(...parts)
      if (
        parts.at(-1) === 'at' &&
        anchor.kind === 'calendar' &&
        anchor.calendar_id === this.context.calendar_id
      ) {
        this.error(
          'alignment.self_reference',
          pointer(...parts, 'anchor', 'calendar_id'),
          'the alignment cannot be a date of this calendar',
        )
      }
      if (!Object.hasOwn(this.resolvedMoments, path)) {
        this.error('anchor.unresolved', path, 'no resolved moment in the context')
      }
    }
  }

  checkFormats(): void {
    const formats = this.definition.formats
    if (formats == null) return
    const scope = {
      levels: new Set(this.levels),
      cycles: new Set(this.definition.regimes.flatMap((r) => (r.cycles ?? []).map((c) => c.id))),
      overlays: new Set((this.definition.overlays ?? []).map((overlay) => overlay.id)),
    }
    const patterns: [string, string, string][] = []
    for (const [key, value] of Object.entries(formats)) {
      if (key !== 'intercalary' && typeof value === 'string') {
        patterns.push([pointer('formats', key), key, value])
      }
    }
    for (const [key, value] of Object.entries(formats.intercalary ?? {})) {
      if (value !== undefined) patterns.push([pointer('formats', 'intercalary', key), key, value])
    }
    for (const [path, key, pattern] of patterns) {
      if (!this.levelIndex.has(key)) {
        this.error('format.unknown_level', path, `${key} is not a level of this calendar`)
      }
      const unknown = unknownTokens(pattern, scope)
      if (unknown.length > 0) {
        this.error('format.unknown_token', path, `unknown tokens: ${unknown.join(', ')}`)
      }
    }
  }

  // --- regimes ----------------------------------------------------------------------------

  compileRegime(r: number, regime: Regime): CompiledRegime | null {
    const before = this.errors.length
    const base: Path = ['regimes', r]
    const cycleIds = this.checkCycles(r, regime)
    const templates = this.compileTemplates(base, regime, cycleIds)
    this.checkTop(base, regime)
    if (this.errors.length > before || templates === null) return null
    const structure = this.buildRegime(r, regime, templates)
    const located = new CompiledRegime(structure, 0n, null)
    const offset = this.locate(
      located,
      regime.alignment.fields,
      [...base, 'alignment', 'fields'],
      'alignment.invalid_fields',
    )
    this.checkCycleAnchors(r, regime, located)
    const at = this.resolved(pointer(...base, 'alignment', 'at'))
    if (offset === null || at === null || this.errors.length > before) return null
    const [year, within] = offset
    let startsAt: bigint | null = null
    if (regime.starts_at != null && regime.starts_at.anchor.kind !== 'local') {
      startsAt = this.resolved(pointer(...base, 'starts_at'))
    }
    return new CompiledRegime(structure, at - located.relStart(year) - within, startsAt)
  }

  // --- templates --------------------------------------------------------------------------

  /** Validate every template; build them all if the regime's templates are valid. */
  compileTemplates(
    base: Path,
    regime: Regime,
    cycleIds: ReadonlySet<string>,
  ): Map<string, CompiledTemplate> | null {
    const definitions = new Map<string, Template>()
    for (const [id, template] of Object.entries(regime.templates)) {
      if (template !== undefined) definitions.set(id, template)
    }
    let ok = true
    const children = new Map<string, string[]>()
    for (const [id, template] of definitions) {
      const refs = this.checkTemplate([...base, 'templates', id], template, definitions, cycleIds)
      if (refs === null) ok = false
      else children.set(id, refs)
    }
    if (!ok) return null
    const compiled = new Map<string, CompiledTemplate>()
    const build = (id: string): void => {
      if (compiled.has(id)) return
      for (const child of children.get(id) ?? []) build(child)
      compiled.set(id, this.buildTemplate(id, defined(definitions.get(id)), compiled))
    }
    for (const id of definitions.keys()) build(id)
    return compiled
  }

  childTemplate(level: number, explicit: string | null | undefined): string | null {
    return explicit ?? this.definition.levels[level - 1]?.default_template ?? null
  }

  /** Local checks of one template; returns the child template ids, or null if invalid. */
  checkTemplate(
    path: Path,
    template: Template,
    definitions: ReadonlyMap<string, Template>,
    cycleIds: ReadonlySet<string>,
  ): string[] | null {
    const before = this.errors.length
    const level = this.levelIndex.get(template.level)
    if (level === undefined) {
      this.error('template.unknown_level', pointer(...path, 'level'), 'unknown level')
      return null
    }
    const refs: string[] = []
    const reference = (explicit: string | null | undefined, refPath: Path, implicit: Path) => {
      const child = this.childTemplate(level, explicit)
      const where = pointer(...(explicit != null ? refPath : implicit))
      const childDefinition = child === null ? undefined : definitions.get(child)
      if (child === null || childDefinition === undefined) {
        this.error('template.unknown_template', where, `unknown child template ${String(child)}`)
        return
      }
      const childLevel = this.levelIndex.get(childDefinition.level)
      if (childLevel !== undefined && childLevel !== level - 1) {
        this.error('template.child_level_mismatch', where, `${child} is at the wrong level`)
        return
      }
      refs.push(child)
    }

    if ('uniform' in template && level === 0) {
      if (template.uniform.template != null) {
        this.error(
          'template.level0_not_uniform',
          pointer(...path, 'uniform', 'template'),
          'level-0 units are made of base units',
        )
      }
    } else if ('uniform' in template) {
      reference(template.uniform.template, [...path, 'uniform', 'template'], [...path, 'uniform'])
    } else if (level === 0) {
      this.error(
        'template.level0_not_uniform',
        pointer(...path, 'sequence'),
        'level-0 templates are uniform',
      )
    } else {
      const slots = new Set<string>()
      template.sequence.forEach((child, k) => {
        const childPath: Path = [...path, 'sequence', k]
        if ('run' in child) {
          reference(child.run.template, [...childPath, 'run', 'template'], [...childPath, 'run'])
        } else {
          this.checkNamedChild(child, childPath, slots, cycleIds)
          reference(child.template, [...childPath, 'template'], [...childPath, 'template'])
        }
      })
    }
    return this.errors.length === before ? refs : null
  }

  checkNamedChild(
    child: NamedChild,
    path: Path,
    slots: Set<string>,
    cycleIds: ReadonlySet<string>,
  ): void {
    if (slots.has(child.id)) {
      this.error('template.duplicate_slot_id', pointer(...path, 'id'), `duplicate slot ${child.id}`)
    }
    slots.add(child.id)
    ;(child.cycle_excluded ?? []).forEach((cycleId, j) => {
      if (!cycleIds.has(cycleId)) {
        this.error(
          'template.unknown_cycle',
          pointer(...path, 'cycle_excluded', j),
          `unknown cycle ${cycleId}`,
        )
      }
    })
  }

  buildTemplate(
    id: string,
    template: Template,
    compiled: ReadonlyMap<string, CompiledTemplate>,
  ): CompiledTemplate {
    const level = defined(this.levelIndex.get(template.level))
    const lengthOf = (child: string): bigint => defined(compiled.get(child)).length
    const segments: Segment[] = []
    const plain = { slotId: null, name: null, abbr: null, intercalary: false, cycleExcluded: [] }
    if ('uniform' in template) {
      const child = level === 0 ? null : this.childTemplate(level, template.uniform.template)
      segments.push({
        ...plain,
        count: BigInt(template.uniform.count),
        child,
        childLength: child === null ? 1n : lengthOf(child),
        start: 0n,
        regularStart: 0n,
      })
    } else {
      let start = 0n
      let regular = 0n
      for (const child of template.sequence) {
        let segment: Segment
        if ('run' in child) {
          const childId = defined(this.childTemplate(level, child.run.template))
          segment = {
            ...plain,
            count: BigInt(child.run.count),
            child: childId,
            childLength: lengthOf(childId),
            start,
            regularStart: regular,
          }
        } else {
          segment = {
            count: 1n,
            child: child.template,
            childLength: lengthOf(child.template),
            start,
            regularStart: regular,
            slotId: child.id,
            name: child.name,
            abbr: child.abbr ?? null,
            intercalary: child.intercalary ?? false,
            cycleExcluded: child.cycle_excluded ?? [],
          }
        }
        segments.push(segment)
        start += segment.count * segment.childLength
        regular += segmentRegularCount(segment)
      }
    }
    return new CompiledTemplate(id, level, segments, units(level, segments, compiled))
  }

  // --- top pattern ------------------------------------------------------------------------

  checkTop(base: Path, regime: Regime): void {
    const top = regime.top
    const path: Path = [...base, 'top']
    const topLevel = defined(this.levels.at(-1))
    const reference = (templateId: string, refPath: Path): void => {
      const template = Object.hasOwn(regime.templates, templateId)
        ? regime.templates[templateId]
        : undefined
      if (template === undefined) {
        this.error('top.unknown_template', pointer(...refPath), `unknown template ${templateId}`)
      } else if (template.level !== topLevel && this.levelIndex.has(template.level)) {
        this.error('top.template_wrong_level', pointer(...refPath), `${templateId} is no year`)
      }
    }
    const pattern = top.pattern
    const patternPath: Path = [...path, 'pattern']
    if (pattern.kind === 'fixed') {
      reference(pattern.template, [...patternPath, 'template'])
    } else if (pattern.kind === 'rules') {
      reference(pattern.default, [...patternPath, 'default'])
      const moduli: bigint[] = []
      pattern.rules.forEach((rule, k) => {
        reference(rule.template, [...patternPath, 'rules', k, 'template'])
        this.checkPredicate(rule.when, [...patternPath, 'rules', k, 'when'], moduli)
      })
      if (lcmExceeds(moduli, MAX_PERIOD)) {
        this.error('top.period_too_large', pointer(...patternPath), 'the period exceeds 1000000')
      }
    } else {
      pattern.templates.forEach((id, k) => {
        reference(id, [...patternPath, 'templates', k])
      })
    }
    const years = new Set<bigint>()
    ;(top.exceptions ?? []).forEach((exception, k) => {
      const year = BigInt(exception.year)
      if (years.has(year)) {
        this.error(
          'top.duplicate_exception',
          pointer(...path, 'exceptions', k, 'year'),
          `duplicate exception year ${exception.year}`,
        )
      }
      years.add(year)
      reference(exception.template, [...path, 'exceptions', k, 'template'])
    })
  }

  checkPredicate(predicate: Predicate, path: Path, moduli: bigint[]): void {
    if ('mod' in predicate) {
      const mod = BigInt(predicate.mod)
      if (BigInt(predicate.eq) >= mod) {
        this.error('top.bad_predicate', pointer(...path), 'eq must lie in [0, mod)')
      }
      moduli.push(mod)
    } else if ('not' in predicate) {
      this.checkPredicate(predicate.not, [...path, 'not'], moduli)
    } else {
      const [key, inner] = 'all' in predicate ? ['all', predicate.all] : ['any', predicate.any]
      inner.forEach((part, j) => {
        this.checkPredicate(part, [...path, key, j], moduli)
      })
    }
  }

  /** Period, per-period template sequence, prefix sums and exceptions (§4 step 3, §5.2). */
  buildRegime(
    r: number,
    regime: Regime,
    templates: ReadonlyMap<string, CompiledTemplate>,
  ): RegimeStructure {
    const lengthOf = (id: string): bigint => defined(templates.get(id)).length
    const [topTemplates, sequence] = topSequence(regime.top.pattern)
    const period = sequence.length
    const lengths = topTemplates.map(lengthOf)
    const yearStarts = new Array<bigint>(period + 1)
    yearStarts[0] = 0n
    for (let i = 0; i < period; i++) {
      yearStarts[i + 1] = defined(yearStarts[i]) + defined(lengths[defined(sequence[i])])
    }
    const cycleLength = defined(yearStarts[period])
    const bigPeriod = BigInt(period)
    const exceptions = (regime.top.exceptions ?? [])
      .map((exception) => [BigInt(exception.year), exception.template] as const)
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    const years = exceptions.map(([year]) => year)
    const regularIndex = (year: bigint): number => Number(floorMod(year, bigPeriod))
    const prefix = [0n]
    for (const [year, id] of exceptions) {
      const delta = lengthOf(id) - defined(lengths[defined(sequence[regularIndex(year)])])
      prefix.push(defined(prefix.at(-1)) + delta)
    }
    const negative = defined(prefix[bisectLeft(years, 0n)])
    const starts = years.map((year, e) => {
      const i = regularIndex(year)
      const k = floorDiv(year, bigPeriod)
      return k * cycleLength + defined(yearStarts[i]) + defined(prefix[e]) - negative
    })
    return {
      id: regime.id,
      index: r,
      templates,
      period: bigPeriod,
      topTemplates,
      topSequence: sequence,
      yearStarts,
      cycleLength,
      exceptionYears: years,
      exceptionTemplates: exceptions.map(([, id]) => id),
      exceptionDeltas: prefix,
      exceptionStarts: starts,
    }
  }

  // --- fields, cycles ---------------------------------------------------------------------

  /**
   * (year, offset within the year) of the unit `fields` denote, or null (error added). Fields go
   * from the top level down without gaps; values are regular numbers or slot ids. With `finest`,
   * the fields must stop exactly at that level.
   */
  locate(
    regime: CompiledRegime,
    fields: Readonly<Record<string, string | undefined>>,
    path: Path,
    code: string,
    finest?: string,
  ): readonly [bigint, bigint, readonly Segment[]] | null {
    const keys = Object.keys(fields)
    const unknown = keys.filter((key) => !this.levelIndex.has(key))
    for (const key of unknown) this.error(code, pointer(...path, key), `${key} is not a level`)
    const present = keys.flatMap((key) => this.levelIndex.get(key) ?? []).sort((a, b) => b - a)
    const top = this.levels.length - 1
    const lowest = present.at(-1) ?? top
    if (unknown.length > 0) return null
    const gapless = present.length === top - lowest + 1 && present.every((l, i) => l === top - i)
    if (!gapless || (finest !== undefined && lowest !== this.levelIndex.get(finest))) {
      this.error(code, pointer(...path), 'fields must go from the top level down without gaps')
      return null
    }
    const topId = defined(this.levels[top])
    const yearValue = defined(fields[topId])
    if (!isNumber(yearValue)) {
      this.error(code, pointer(...path, topId), 'the year must be a number')
      return null
    }
    const year = BigInt(yearValue)
    let template = regime.yearTemplate(year)
    let offset = 0n
    const segments: Segment[] = []
    for (let level = top - 1; level >= lowest; level--) {
      const levelId = defined(this.levels[level])
      const value = defined(fields[levelId])
      const child: Child | null = isNumber(value)
        ? template.childByRegularIndex(BigInt(value) - defined(this.numbering[level]))
        : template.childBySlot(value)
      if (child === null) {
        this.error(code, pointer(...path, levelId), `no ${levelId} ${value} here`)
        return null
      }
      offset += child.offset
      segments.push(child.segment)
      template = regime.template(defined(child.segment.child))
    }
    return [year, offset, segments]
  }

  checkCycles(r: number, regime: Regime): Set<string> {
    const seen = new Set<string>()
    ;(regime.cycles ?? []).forEach((cycle, c) => {
      const path: Path = ['regimes', r, 'cycles', c]
      if (seen.has(cycle.id)) {
        this.error('cycle.duplicate_id', pointer(...path, 'id'), `duplicate cycle ${cycle.id}`)
      }
      seen.add(cycle.id)
      const level = this.levelIndex.get(cycle.level)
      if (level === undefined) {
        this.error('cycle.unknown_level', pointer(...path, 'level'), 'unknown level')
      }
      for (const member of ['names', 'abbrs'] as const) {
        const values = cycle[member]
        if (values != null && values.length !== cycle.length) {
          this.error(
            'cycle.names_length_mismatch',
            pointer(...path, member),
            `${member} must have ${cycle.length} entries`,
          )
        }
      }
      const mode = cycle.mode ?? 'continuous'
      if (mode !== 'continuous') {
        const reset = this.levelIndex.get(mode.reset)
        if (reset === undefined || level === undefined || reset <= level) {
          this.error(
            'cycle.bad_reset_level',
            pointer(...path, 'mode', 'reset'),
            'the reset level must be coarser',
          )
        }
      }
      const continued = cycle.continue_from_previous_regime ?? false
      if (continued && mode !== 'continuous') {
        this.error(
          'cycle.anchor_invalid',
          pointer(...path, 'continue_from_previous_regime'),
          'only continuous cycles continue across regimes',
        )
      } else if (continued && r === 0) {
        this.error(
          'cycle.anchor_invalid',
          pointer(...path, 'continue_from_previous_regime'),
          'regime 0 has no previous regime',
        )
      } else if (continued) {
        this.checkContinuedCycle(
          path,
          cycle.id,
          cycle.length,
          defined(this.definition.regimes[r - 1]),
        )
      } else if (mode === 'continuous' && cycle.anchor?.fields == null) {
        const missing = cycle.anchor == null ? ['anchor'] : ['anchor', 'fields']
        this.error(
          'cycle.anchor_invalid',
          pointer(...path, ...missing),
          'a continuous cycle needs an anchor date',
        )
      }
      if (cycle.anchor != null && (cycle.anchor.index ?? 0) >= cycle.length) {
        this.error(
          'cycle.anchor_invalid',
          pointer(...path, 'anchor', 'index'),
          'index must be < length',
        )
      }
    })
    return seen
  }

  /** A continued cycle needs a continuous cycle of the same id and length before it. */
  checkContinuedCycle(path: Path, cycleId: string, length: number, previous: Regime): void {
    const where = pointer(...path, 'continue_from_previous_regime')
    const before = (previous.cycles ?? []).find((cycle) => cycle.id === cycleId)
    if (before === undefined || (before.mode ?? 'continuous') !== 'continuous') {
      this.error(
        'cycle.anchor_invalid',
        where,
        `the previous regime has no continuous cycle ${cycleId}`,
      )
    } else if (before.length !== length) {
      this.error('cycle.anchor_invalid', where, "the previous regime's cycle has another length")
    }
  }

  checkCycleAnchors(r: number, regime: Regime, compiled: CompiledRegime): void {
    ;(regime.cycles ?? []).forEach((cycle, c) => {
      const anchored =
        (cycle.mode ?? 'continuous') === 'continuous' &&
        !(cycle.continue_from_previous_regime ?? false)
      const fields = cycle.anchor?.fields
      if (anchored && fields != null && this.levelIndex.has(cycle.level)) {
        const path: Path = ['regimes', r, 'cycles', c, 'anchor', 'fields']
        const found = this.locate(compiled, fields, path, 'cycle.anchor_invalid', cycle.level)
        // The anchor unit must count: neither it nor an ancestor is excluded from the cycle.
        if (found?.[2].some((segment) => segment.cycleExcluded.includes(cycle.id)) === true) {
          this.error(
            'cycle.anchor_invalid',
            pointer(...path),
            'the anchor unit is excluded from the cycle',
          )
        }
      }
    })
  }
}

/** Level → (total, regular) descendant units; a unit is regular unless it is intercalary. */
function units(
  level: number,
  segments: readonly Segment[],
  compiled: ReadonlyMap<string, CompiledTemplate>,
): Map<number, readonly [bigint, bigint]> {
  const result = new Map<number, readonly [bigint, bigint]>()
  if (level === 0) return result
  let total = 0n
  let regular = 0n
  for (const segment of segments) {
    total += segment.count
    regular += segmentRegularCount(segment)
  }
  result.set(level - 1, [total, regular])
  for (let below = 0; below < level - 1; below++) {
    let belowTotal = 0n
    let belowRegular = 0n
    for (const segment of segments) {
      if (segment.child === null) continue
      const [childTotal, childRegular] = defined(
        defined(compiled.get(segment.child)).units.get(below),
      )
      belowTotal += segment.count * childTotal
      belowRegular += segment.count * childRegular
    }
    result.set(below, [belowTotal, belowRegular])
  }
  return result
}

function lcm(a: bigint, b: bigint): bigint {
  return (a / gcd(a, b)) * b
}

function lcmExceeds(moduli: readonly bigint[], limit: bigint): boolean {
  let period = 1n
  for (const mod of moduli) {
    period = lcm(period, mod)
    if (period > limit) return true
  }
  return false
}

type SequenceArray = Uint8Array | Uint16Array

function sequenceArray(length: number, templates: number): SequenceArray {
  // A regime has at most 500 templates (schema).
  return templates <= 0x100 ? new Uint8Array(length) : new Uint16Array(length)
}

/** Distinct top templates and the template index of each year in one period. */
function topSequence(pattern: YearPattern): readonly [string[], SequenceArray] {
  if (pattern.kind === 'fixed') return [[pattern.template], new Uint8Array(1)]
  if (pattern.kind === 'rules') {
    const ids = [...new Set([pattern.default, ...pattern.rules.map((rule) => rule.template)])]
    const index = new Map(ids.map((id, i) => [id, i]))
    const moduli: bigint[] = []
    for (const rule of pattern.rules) collectModuli(rule.when, moduli)
    const period = Number(moduli.reduce(lcm, 1n))
    const sequence = sequenceArray(period, ids.length)
    sequence.fill(defined(index.get(pattern.default)))
    // The first matching rule wins: apply the rules last to first, one predicate mask each.
    for (const rule of [...pattern.rules].reverse()) {
      const selected = mask(rule.when, period)
      const value = defined(index.get(rule.template))
      for (let year = 0; year < period; year++) if (selected[year] === 1) sequence[year] = value
    }
    return [ids, sequence]
  }
  const ids = [...new Set(pattern.templates)]
  const index = new Map(ids.map((id, i) => [id, i]))
  const count = BigInt(pattern.templates.length)
  const start = BigInt(pattern.start)
  const sequence = sequenceArray(pattern.templates.length, ids.length)
  for (let i = 0; i < pattern.templates.length; i++) {
    const position = Number(floorMod(BigInt(i) - start, count))
    sequence[i] = defined(index.get(defined(pattern.templates[position])))
  }
  return [ids, sequence]
}

function collectModuli(predicate: Predicate, moduli: bigint[]): void {
  if ('mod' in predicate) moduli.push(BigInt(predicate.mod))
  else if ('not' in predicate) collectModuli(predicate.not, moduli)
  else
    for (const inner of 'all' in predicate ? predicate.all : predicate.any)
      collectModuli(inner, moduli)
}

/** `1` for the years `0 … period-1` that satisfy the predicate (moduli divide the period). */
function mask(predicate: Predicate, period: number): Uint8Array {
  if ('mod' in predicate) {
    const result = new Uint8Array(period)
    const mod = Number(predicate.mod)
    for (let year = Number(predicate.eq); year < period; year += mod) result[year] = 1
    return result
  }
  if ('not' in predicate) return mask(predicate.not, period).map((bit) => bit ^ 1)
  const all = 'all' in predicate
  const parts = (all ? predicate.all : predicate.any).map((part) => mask(part, period))
  const result = defined(parts[0])
  for (const part of parts.slice(1)) {
    for (let year = 0; year < period; year++) {
      result[year] = all
        ? defined(result[year]) & defined(part[year])
        : defined(result[year]) | defined(part[year])
    }
  }
  return result
}

// --- raw documents (schema + semantics) ----------------------------------------------------------

/**
 * Validate raw JSON documents: structural (schema) errors first, then `compileCalendar`.
 *
 * Some schema violations have specific codes (§11): too many levels, a bad level id, a zero or
 * oversized count, too many templates or children, an intercalary child without id, an era on a
 * local anchor. Every other violation is `schema.invalid`. Context errors are reported under
 * `/$context`.
 */
export function validateCalendar(
  definition: unknown,
  context: unknown,
): CompiledCalendar | ValidationError[] {
  const errors = prescan(definition)
  const skipped = errors.map((error) => error.path)
  const definitionIssues = checkDocument('CalendarDefinition', definition)
  for (const issue of definitionIssues) {
    const path = pointer(...issue.path)
    if (!skipped.some((skip) => path === skip || path.startsWith(skip + '/'))) {
      errors.push({ code: schemaCode(issue), path, message: 'schema violation' })
    }
  }
  const contextIssues = checkDocument('CompileContext', context)
  for (const issue of contextIssues) {
    errors.push({
      code: 'schema.invalid',
      path: pointer('$context', ...issue.path),
      message: 'schema violation',
    })
  }
  if (errors.length > 0 || definitionIssues.length > 0 || contextIssues.length > 0) {
    return sortedErrors(errors)
  }
  return compileCalendar(definition as CalendarDefinition, context as CompileContext)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function asList(value: unknown): readonly unknown[] {
  return Array.isArray(value) ? value : []
}

/** Violations with dedicated codes that the schema would only report as unknown members. */
function prescan(definition: unknown): ValidationError[] {
  const errors: ValidationError[] = []
  if (!isRecord(definition)) return errors
  asList(definition.regimes).forEach((regime, r) => {
    if (!isRecord(regime)) return
    const templates = isRecord(regime.templates) ? regime.templates : {}
    for (const [id, template] of Object.entries(templates)) {
      asList(isRecord(template) ? template.sequence : undefined).forEach((child, k) => {
        if (isRecord(child) && child.intercalary === true && !Object.hasOwn(child, 'id')) {
          errors.push({
            code: 'template.intercalary_without_id',
            path: pointer('regimes', r, 'templates', id, 'sequence', k),
            message: 'an intercalary child needs an id',
          })
        }
      })
    }
    errors.push(...localEra(regime.starts_at, ['regimes', r, 'starts_at']))
  })
  for (const [kind, member] of [
    ['eras', 'start'],
    ['overlays', 'epoch'],
  ] as const) {
    asList(definition[kind]).forEach((item, i) => {
      if (isRecord(item)) errors.push(...localEra(item[member], [kind, i, member]))
    })
  }
  return errors
}

function localEra(point: unknown, path: Path): ValidationError[] {
  const anchor = isRecord(point) ? point.anchor : undefined
  if (isRecord(anchor) && anchor.kind === 'local' && Object.hasOwn(anchor, 'era')) {
    return [
      {
        code: 'era.local_anchor_uses_era',
        path: pointer(...path, 'anchor', 'era'),
        message: 'local anchors use astronomical years',
      },
    ]
  }
  return []
}

function schemaCode(issue: SchemaIssue): string {
  const path = issue.path
  const [first, , third] = path
  const last = path.at(-1)
  if (first === 'levels') {
    if (path.length === 1 && issue.kind === 'too_long') return 'level.too_many'
    if (path.length === 3 && third === 'id') return 'level.invalid_id'
  }
  if (first === 'regimes' && third === 'templates') {
    const tooMany = path.length === 3 || (path.length >= 4 && last === 'sequence')
    if (tooMany && issue.kind === 'too_long') return 'template.too_large'
    if (path.length >= 4 && last === 'count') {
      if (issue.kind === 'string_too_long') return 'template.too_large'
      if (issue.value === '0') return 'template.zero_length'
    }
  }
  return 'schema.invalid'
}
