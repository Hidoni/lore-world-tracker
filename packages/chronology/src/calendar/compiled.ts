/**
 * Compiled calendars: immutable, precomputed structures (chronology-engine.md §4–§5). Built by
 * `compileCalendar`. Lookups are logarithmic (binary searches over prefix sums), never loops over
 * years or units. The Python twin is backend/src/lore/chronology/calendar/compiled.py.
 */
import { floorDiv, floorMod } from '../numbers'
import type { CalendarDefinition, CompileContext } from '../schema.gen'

const NUMBER = /^-?[0-9]+$/

/** A field value is a regular number (else it is a slot id). */
export function isNumber(value: string): boolean {
  return NUMBER.test(value)
}

/** `value`, which an engine invariant guarantees is present (a lookup that cannot miss). */
export function defined<T>(value: T | null | undefined): T {
  if (value == null) throw new Error('chronology engine invariant violated: missing value')
  return value
}

/** Number of elements of the sorted `values[0..hi)` that are `≤ value` (Python `bisect_right`). */
export function bisectRight(values: readonly bigint[], value: bigint, hi = values.length): number {
  let lo = 0
  while (lo < hi) {
    const mid = (lo + hi) >>> 1
    if (value < defined(values[mid])) hi = mid
    else lo = mid + 1
  }
  return lo
}

/** Number of elements of the sorted `values` that are `< value` (Python `bisect_left`). */
export function bisectLeft(values: readonly bigint[], value: bigint): number {
  let lo = 0
  let hi = values.length
  while (lo < hi) {
    const mid = (lo + hi) >>> 1
    if (defined(values[mid]) < value) lo = mid + 1
    else hi = mid
  }
  return lo
}

/** A run of identical children inside a template (a named slot is a segment of count 1). */
export interface Segment {
  readonly count: bigint
  /** Child template id; `null` for level-0 templates (children are base units). */
  readonly child: string | null
  readonly childLength: bigint
  /** Base-unit offset of the segment's first child within the template. */
  readonly start: bigint
  /** Number of regular (non-intercalary) children before the segment. */
  readonly regularStart: bigint
  readonly slotId: string | null
  readonly name: string | null
  readonly abbr: string | null
  readonly intercalary: boolean
  readonly cycleExcluded: readonly string[]
}

export function segmentRegularCount(segment: Segment): bigint {
  return segment.intercalary ? 0n : segment.count
}

/** One child unit located inside a template. */
export interface Child {
  readonly segment: Segment
  /** Index of the segment within the template. */
  readonly position: number
  /** Index of the child within its segment. */
  readonly index: bigint
  /** Base-unit offset of the child within the parent template. */
  readonly offset: bigint
}

/** 0-based ordinal among regular siblings; `null` for an intercalary child. */
export function childRegularIndex(child: Child): bigint | null {
  return child.segment.intercalary ? null : child.segment.regularStart + child.index
}

/** The layout of one unit at one level, with prefix sums (chronology-engine §3.4, §5.5). */
export class CompiledTemplate {
  /** `L(T)` in base units. */
  readonly length: bigint
  /** Slot id → segment index. */
  readonly slots: ReadonlyMap<string, number>
  /** Number of children. */
  readonly totalCount: bigint
  /** Number of regular (non-intercalary) children. */
  readonly regularCount: bigint
  readonly #starts: readonly bigint[]
  readonly #regularSegments: readonly number[]
  readonly #regularStarts: readonly bigint[]

  /** `segments` have their `start`/`regularStart` set; `units` maps a level index to the
   * (total, regular) number of descendant units at that level. */
  constructor(
    readonly id: string,
    /** Index of the template's level in the calendar's levels (0 = finest). */
    readonly level: number,
    readonly segments: readonly Segment[],
    readonly units: ReadonlyMap<number, readonly [bigint, bigint]>,
  ) {
    const last = defined(segments[segments.length - 1])
    this.length = last.start + last.count * last.childLength
    this.slots = new Map(
      segments.flatMap((segment, i) => (segment.slotId === null ? [] : [[segment.slotId, i]])),
    )
    this.totalCount = segments.reduce((sum, segment) => sum + segment.count, 0n)
    this.regularCount = last.regularStart + segmentRegularCount(last)
    this.#starts = segments.map((segment) => segment.start)
    this.#regularSegments = segments.flatMap((segment, i) => (segment.intercalary ? [] : [i]))
    this.#regularStarts = this.#regularSegments.map((i) => defined(segments[i]).regularStart)
  }

  #child(position: number, index: bigint): Child {
    const segment = defined(this.segments[position])
    return { segment, position, index, offset: segment.start + index * segment.childLength }
  }

  /** The child containing `0 ≤ offset < length` (binary search over the prefix sums). */
  childAt(offset: bigint): Child {
    const position = bisectRight(this.#starts, offset) - 1
    const segment = defined(this.segments[position])
    return this.#child(position, (offset - segment.start) / segment.childLength)
  }

  /** The regular child with this 0-based ordinal, if it exists. */
  childByRegularIndex(regularIndex: bigint): Child | null {
    if (regularIndex < 0n || regularIndex >= this.regularCount) return null
    const position = defined(
      this.#regularSegments[bisectRight(this.#regularStarts, regularIndex) - 1],
    )
    const segment = defined(this.segments[position])
    return this.#child(position, regularIndex - segment.regularStart)
  }

  childBySlot(slotId: string): Child | null {
    const position = this.slots.get(slotId)
    return position === undefined ? null : this.#child(position, 0n)
  }
}

export interface RegimeStructure {
  readonly id: string
  readonly index: number
  readonly templates: ReadonlyMap<string, CompiledTemplate>
  /** `P`: the top pattern repeats every `P` years. */
  readonly period: bigint
  /** Distinct template ids used by the pattern; `topSequence` indexes into it. */
  readonly topTemplates: readonly string[]
  /** Template (index into `topTemplates`) of years `0 … P-1` of a period. */
  readonly topSequence: ArrayLike<number>
  /** `S[0..P]`: prefix sums of year lengths over one period. */
  readonly yearStarts: readonly bigint[]
  /** `C = S[P]`. */
  readonly cycleLength: bigint
  readonly exceptionYears: readonly bigint[]
  readonly exceptionTemplates: readonly string[]
  /** Prefix sums of `Δ_e` over the sorted exceptions (length n + 1). */
  readonly exceptionDeltas: readonly bigint[]
  /** `A_e = rel_start(Y_e)` for each exception. */
  readonly exceptionStarts: readonly bigint[]
}

/** A parallel cycle (chronology-engine §3.7), evaluated by the `cycles` module. */
export interface CompiledCycle {
  readonly id: string
  /** Index of the cycle's level. */
  readonly level: number
  readonly length: number
  readonly names: readonly string[] | null
  readonly abbrs: readonly string[] | null
  /** Stable value ids (recurrence rules match them, or the number `index + numberStart`). */
  readonly ids: readonly string[] | null
  readonly numberStart: number
  /** Index of the reset level; `null` for a continuous cycle. */
  readonly reset: number | null
  readonly anchorIndex: number
  /** Continuous cycles: counted ordinal of the unit with `anchorIndex`; `null` for reset cycles. */
  readonly anchorOrdinal: bigint | null
}

/** One regime: templates, the top-level period and exceptions, and the epoch (§5.1–§5.4). */
export class CompiledRegime implements RegimeStructure {
  readonly id: string
  readonly index: number
  readonly templates: ReadonlyMap<string, CompiledTemplate>
  readonly period: bigint
  readonly topTemplates: readonly string[]
  readonly topSequence: ArrayLike<number>
  readonly yearStarts: readonly bigint[]
  readonly cycleLength: bigint
  readonly exceptionYears: readonly bigint[]
  readonly exceptionTemplates: readonly string[]
  readonly exceptionDeltas: readonly bigint[]
  readonly exceptionStarts: readonly bigint[]
  /** Derived structures computed on first use (unit counts per level and filter, `units`). */
  readonly cache = new Map<string, unknown>()

  constructor(
    structure: RegimeStructure,
    /** `E`: the moment year 0 starts. */
    readonly epoch: bigint,
    /** Resolved start moment (`null` for regime 0, and before `local` starts are resolved). */
    readonly startsAt: bigint | null,
    readonly cycles: readonly CompiledCycle[] = [],
  ) {
    this.id = structure.id
    this.index = structure.index
    this.templates = structure.templates
    this.period = structure.period
    this.topTemplates = structure.topTemplates
    this.topSequence = structure.topSequence
    this.yearStarts = structure.yearStarts
    this.cycleLength = structure.cycleLength
    this.exceptionYears = structure.exceptionYears
    this.exceptionTemplates = structure.exceptionTemplates
    this.exceptionDeltas = structure.exceptionDeltas
    this.exceptionStarts = structure.exceptionStarts
  }

  /** A copy with another start or other cycles (compilation resolves them in later steps). */
  with(changes: {
    readonly startsAt?: bigint | null
    readonly cycles?: readonly CompiledCycle[]
  }): CompiledRegime {
    return new CompiledRegime(
      this,
      this.epoch,
      changes.startsAt === undefined ? this.startsAt : changes.startsAt,
      changes.cycles ?? this.cycles,
    )
  }

  template(id: string): CompiledTemplate {
    const template = this.templates.get(id)
    if (template === undefined) throw new Error(`unknown template ${id}`)
    return template
  }

  /** `cum(Y) = Σ_{Y_e < Y} Δ_e − Σ_{Y_e < 0} Δ_e`. */
  #cumulative(year: bigint): bigint {
    const before = defined(this.exceptionDeltas[bisectLeft(this.exceptionYears, year)])
    return before - defined(this.exceptionDeltas[bisectLeft(this.exceptionYears, 0n)])
  }

  /** `tmpl(Y)` from the pattern alone (ignoring exceptions). */
  regularTemplate(year: bigint): string {
    const index = defined(this.topSequence[Number(floorMod(year, this.period))])
    return defined(this.topTemplates[index])
  }

  /** `tmpl*(Y)`: the template year `Y` uses, honoring exceptions. */
  yearTemplate(year: bigint): CompiledTemplate {
    const position = bisectLeft(this.exceptionYears, year)
    if (this.exceptionYears[position] === year) {
      return this.template(defined(this.exceptionTemplates[position]))
    }
    return this.template(this.regularTemplate(year))
  }

  /** Start of year `Y` relative to the epoch (§5.1–§5.2). */
  relStart(year: bigint): bigint {
    const k = floorDiv(year, this.period)
    const i = Number(year - k * this.period)
    return k * this.cycleLength + defined(this.yearStarts[i]) + this.#cumulative(year)
  }

  /** The year containing the epoch-relative moment `rel` (§5.3). */
  yearOfRel(rel: bigint): bigint {
    const position = bisectRight(this.exceptionStarts, rel) - 1
    let offset: bigint
    if (position >= 0) {
      const exceptionYear = defined(this.exceptionYears[position])
      const length = this.template(defined(this.exceptionTemplates[position])).length
      if (rel < defined(this.exceptionStarts[position]) + length) return exceptionYear
      offset = this.#cumulative(exceptionYear + 1n)
    } else {
      offset = this.#cumulative(this.exceptionYears[0] ?? 0n)
    }
    const regular = rel - offset
    const k = floorDiv(regular, this.cycleLength)
    const s = regular - k * this.cycleLength
    const i = bisectRight(this.yearStarts, s, Number(this.period)) - 1
    return k * this.period + BigInt(i)
  }

  /** Absolute start moment of year `Y` (`E + rel_start(Y)`). */
  yearStart(year: bigint): bigint {
    return this.epoch + this.relStart(year)
  }

  /** The year containing moment `t` in this regime's structure. */
  yearOf(t: bigint): bigint {
    return this.yearOfRel(t - this.epoch)
  }
}

/** An era with its resolved bounds (chronology-engine §3.8). */
export class CompiledEra {
  constructor(
    readonly id: string,
    readonly name: string,
    readonly abbr: string,
    readonly abbrPosition: 'prefix' | 'suffix',
    readonly backward: boolean,
    readonly first: bigint,
    /** Start moment (`null` for era 0: since −∞). */
    readonly start: bigint | null,
    /** The next era's start (`null` for the last era). */
    readonly end: bigint | null,
    /** `Y(start)`: the year containing the start (forward eras). */
    readonly startYear: bigint | null,
    /** `Y_end`: the first year starting at or after `end` (backward eras). */
    readonly endYear: bigint | null,
  ) {}

  /** The era-relative number of astronomical year `year`. */
  eraYear(year: bigint): bigint {
    if (this.backward) return defined(this.endYear) - year + this.first - 1n
    return year - defined(this.startYear) + this.first
  }

  /** The astronomical year of era year `eraYear` (the inverse of `eraYear`). */
  year(eraYear: bigint): bigint {
    if (this.backward) return defined(this.endYear) - eraYear + this.first - 1n
    return eraYear - this.first + defined(this.startYear)
  }
}

/** An immutable compiled calendar. Callers cache it (e.g. by calendar id and version). */
export class CompiledCalendar {
  readonly #levelIndex: ReadonlyMap<string, number>

  constructor(
    readonly definition: CalendarDefinition,
    readonly context: CompileContext,
    /** Level ids, fine → coarse (index 0 is made of base units; the last is the top level). */
    readonly levels: readonly string[],
    readonly numberingStarts: readonly bigint[],
    readonly regimes: readonly CompiledRegime[],
    readonly eras: readonly CompiledEra[] = [],
    /** Resolved epoch of each overlay, in definition order (`overlays` module). */
    readonly overlayEpochs: readonly bigint[] = [],
  ) {
    this.#levelIndex = new Map(levels.map((level, i) => [level, i]))
  }

  /** Index of a level id (0 = finest), or -1 if the calendar has no such level. */
  levelIndex(levelId: string): number {
    return this.#levelIndex.get(levelId) ?? -1
  }
}

export type DateErrorCode =
  'invalid_date' | 'reform_gap' | 'reform_ambiguous' | 'unknown_cycle' | 'unknown_overlay'

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

/** The last regime whose start is `≤ t` (regime 0 before every other). */
export function activeRegime(calendar: CompiledCalendar, t: bigint): CompiledRegime {
  const regime = calendar.regimes.findLast(
    (r) => r.index === 0 || (r.startsAt !== null && r.startsAt <= t),
  )
  return defined(regime)
}
