import type {
  Cycle,
  DefinitionTimePoint,
  Era,
  Overlay,
  Phase,
  Rational,
  Regime,
  TimePoint,
} from '@lore/chronology'
import { formatMoment } from '@lore/chronology'
import { ArrowDownIcon, ArrowUpIcon, PlusIcon, Trash2Icon } from 'lucide-react'
import { useId, useState } from 'react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

import { BigNumberInput } from '../big-number-input'
import type { DimensionTime, Lens } from '../calendars'
import { SELECT_CLASS } from '../select'
import { TimePointPicker } from '../time-point-picker'
import { edit, freshId, levelsOf, omit, part, regimeOf, regimePath, type Definition } from './model'
import { FieldErrors, IconButton, PathInput, type StructureProps } from './structure'

/** What the time point editors need to pick moments of the dimension (other calendars, events). */
export interface TimeScope {
  vault: string
  dimension: DimensionTime
  /** The dimension's display calendars, without the one being edited. */
  lenses: readonly Lens[]
}

const SMALL_SELECT = cn(SELECT_CLASS, 'h-8')

/** Splits "a, b, c" (empty: none). */
function list(text: string): string[] | null {
  const items = text
    .split(',')
    .map((item) => item.trim())
    .filter((item) => item !== '')
  return items.length === 0 ? null : items
}

function int(text: string, fallback: number): number {
  const value = Number.parseInt(text, 10)
  return Number.isNaN(value) ? fallback : value
}

/** Moves an item of `items` by `by` places. */
function moved<T>(items: readonly T[], index: number, by: number): T[] {
  const next = [...items]
  const [item] = next.splice(index, 1)
  if (item !== undefined) next.splice(index + by, 0, item)
  return next
}

// --- time points of the definition -------------------------------------------------------------

/** A date of this calendar (from the year down; the finest given level is the precision). */
function LocalFields({
  definition,
  path,
  label,
  fields,
  onChange,
}: {
  definition: Definition
  path: string
  label: string
  fields: Readonly<Record<string, string | undefined>>
  onChange: (fields: Record<string, string>) => void
}) {
  const levels = [...levelsOf(definition)].reverse()
  return (
    <div className="flex flex-wrap gap-2">
      {levels.map((level) => (
        <div key={level.id} className="flex flex-col gap-1 text-xs">
          <span>{level.label}</span>
          <PathInput
            path={`${path}/${part(level.id)}`}
            aria-label={`${label} ${level.label}`}
            className="w-24"
            value={fields[level.id] ?? ''}
            onChange={(event) => {
              const next = Object.fromEntries(
                Object.entries(fields).filter(
                  (entry): entry is [string, string] =>
                    entry[0] !== level.id && entry[1] !== undefined,
                ),
              )
              if (event.target.value !== '') next[level.id] = event.target.value
              // Keep the order from the top level down.
              onChange(
                Object.fromEntries(
                  levels.flatMap((each) => {
                    const value = next[each.id]
                    return value === undefined ? [] : [[each.id, value]]
                  }),
                ),
              )
            }}
          />
        </div>
      ))}
    </div>
  )
}

/** The finest level among `fields` (the precision of a local anchor). */
function finest(definition: Definition, fields: Readonly<Record<string, string | undefined>>) {
  return levelsOf(definition).find((level) => fields[level.id] !== undefined)?.id ?? 'base'
}

type PointKind = 'local' | 'absolute' | 'other'

/**
 * A time point inside the definition (a regime start, an era start, an overlay epoch): a date of
 * this calendar (`local`, read in a regime), a moment, or another time point of the dimension
 * (another calendar's date, relative to an event, …).
 */
export function DefinitionPointField({
  definition,
  scope,
  path,
  label,
  value,
  onChange,
  regimeChoice,
  local = true,
}: {
  definition: Definition
  scope: TimeScope
  path: string
  label: string
  value: DefinitionTimePoint
  onChange: (value: DefinitionTimePoint) => void
  /** Offer the regime a local date is read in. */
  regimeChoice?: boolean
  /** Offer dates of this calendar (not for the alignment, which defines them). */
  local?: boolean
}) {
  const id = useId()
  const anchor = value.anchor
  // "Another time point" starts as the moment it was: the picker then edits it.
  const [other, setOther] = useState(false)
  const kind: PointKind =
    anchor.kind === 'local' ? 'local' : anchor.kind === 'absolute' && !other ? 'absolute' : 'other'
  const switchTo = (next: PointKind) => {
    setOther(next === 'other')
    if (next === 'local') {
      onChange({
        anchor: { kind: 'local', fields: { [finest(definition, {})]: '1' } },
        precision: 'base',
      })
    } else if (next === 'absolute' && anchor.kind !== 'absolute') {
      onChange({ anchor: { kind: 'absolute', t: '0' }, precision: 'base' })
    } else if (next === 'other' && anchor.kind === 'local') {
      onChange({ anchor: { kind: 'absolute', t: '0' }, precision: 'base' })
    }
  }
  return (
    <div className="flex flex-col gap-2 rounded-md border p-2">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <label htmlFor={id}>{label}</label>
        <select
          id={id}
          data-path={`${path}/anchor`}
          className={SMALL_SELECT}
          value={kind}
          onChange={(event) => {
            switchTo(event.target.value as PointKind)
          }}
        >
          {local && <option value="local">A date of this calendar</option>}
          <option value="absolute">A moment</option>
          <option value="other">Another time point</option>
        </select>
      </div>
      {anchor.kind === 'local' && (
        <>
          <LocalFields
            definition={definition}
            path={`${path}/anchor/fields`}
            label={label}
            fields={anchor.fields}
            onChange={(fields) => {
              onChange({
                ...value,
                anchor: { ...anchor, fields },
                precision: finest(definition, fields),
              })
            }}
          />
          {regimeChoice && (
            <label className="flex items-center gap-2 text-xs">
              Read with the rules
              <select
                className={SMALL_SELECT}
                value={anchor.regime ?? ''}
                onChange={(event) => {
                  const rest = omit(anchor, 'regime')
                  onChange({
                    ...value,
                    anchor:
                      event.target.value === '' ? rest : { ...rest, regime: event.target.value },
                  })
                }}
              >
                <option value="">Automatic</option>
                {definition.regimes.map((regime) => (
                  <option key={regime.id} value={regime.id}>
                    {regime.name}
                  </option>
                ))}
              </select>
            </label>
          )}
        </>
      )}
      {anchor.kind === 'absolute' && kind === 'absolute' && (
        <BigNumberInput
          aria-label={`${label} moment`}
          value={BigInt(anchor.t)}
          min={0n}
          max={scope.dimension.duration}
          onChange={(t) => {
            if (t !== null) onChange({ ...value, anchor: { kind: 'absolute', t: formatMoment(t) } })
          }}
        />
      )}
      {kind === 'other' && (
        <TimePointPicker
          vault={scope.vault}
          dimension={scope.dimension}
          lenses={scope.lenses}
          value={value as TimePoint}
          label={label}
          onChange={(point) => {
            if (point !== null) onChange(point)
          }}
        />
      )}
    </div>
  )
}

// --- regimes -------------------------------------------------------------------------------------

/**
 * The calendar's regimes (chronology-engine.md §3.3): reforms, each a full set of rules from its
 * start on. Picking one shows its templates, years, alignment and cycles below; later ones start
 * at a date (strictly after the previous one).
 */
export function RegimesEditor({
  definition,
  errors,
  onChange,
  regimeIndex = 0,
  onSelect,
  scope,
}: StructureProps & { onSelect: (index: number) => void; scope: TimeScope }) {
  const regimes = definition.regimes
  const regime = regimeOf(definition, regimeIndex)
  const path = regimePath(regimeIndex)
  return (
    <section aria-label="Reforms" className="flex flex-col gap-2">
      <h3 className="text-sm font-semibold">Rules and reforms</h3>
      <div className="flex flex-wrap items-center gap-1" role="tablist" aria-label="Rules">
        {regimes.map((each, index) => (
          <Button
            key={index}
            type="button"
            role="tab"
            aria-selected={index === regimeIndex}
            variant={index === regimeIndex ? 'default' : 'outline'}
            size="sm"
            onClick={() => {
              onSelect(index)
            }}
          >
            {each.name || each.id}
          </Button>
        ))}
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => {
            const next = edit(definition, (draft) => {
              const source = structuredClone(regimeOf(draft, regimeIndex))
              const id = freshId(
                draft.regimes.map((each) => each.id),
                'reform',
              )
              const reform: Regime = {
                ...source,
                id,
                name: 'Reform',
                starts_at: {
                  anchor: { kind: 'local', fields: { ...source.alignment.fields } },
                  precision: finest(draft, source.alignment.fields),
                },
              }
              draft.regimes.push(reform)
            })
            onChange(next)
            onSelect(next.regimes.length - 1)
          }}
        >
          <PlusIcon aria-hidden /> Reform
        </Button>
        {regimeIndex > 0 && (
          <IconButton
            label={`Remove the rules ${regime.name}`}
            onClick={() => {
              onChange(
                edit(definition, (draft) => {
                  draft.regimes.splice(regimeIndex, 1)
                }),
              )
              onSelect(regimeIndex - 1)
            }}
          >
            <Trash2Icon />
          </IconButton>
        )}
      </div>
      {regimeIndex > 0 && regime.starts_at && (
        <DefinitionPointField
          definition={definition}
          scope={scope}
          path={`${path}/starts_at`}
          label="Takes effect at"
          value={regime.starts_at}
          regimeChoice
          onChange={(starts_at) => {
            onChange(
              edit(definition, (draft) => {
                regimeOf(draft, regimeIndex).starts_at = starts_at
              }),
            )
          }}
        />
      )}
      <FieldErrors errors={errors} path={`${path}/starts_at`} />
    </section>
  )
}

// --- cycles --------------------------------------------------------------------------------------

/** The named units of `regime` that skip `cycle` (`cycle_excluded` in templates). */
function skippedBy(regime: Regime, cycle: string): string[] {
  return Object.values(regime.templates).flatMap((template) =>
    template !== undefined && 'sequence' in template
      ? template.sequence.flatMap((child) =>
          'id' in child && (child.cycle_excluded ?? []).includes(cycle) ? [child.name] : [],
        )
      : [],
  )
}

/**
 * Parallel cycles of a regime (§3.7): weekdays and the like, counted along a level either
 * continuously (from an anchor unit) or restarting in every unit of a coarser level. Units can
 * skip a cycle (set on the unit in its template).
 */
export function CyclesEditor({ definition, errors, onChange, regimeIndex = 0 }: StructureProps) {
  const regime = regimeOf(definition, regimeIndex)
  const cycles = regime.cycles ?? []
  const levels = [...levelsOf(definition)].reverse()
  const path = `${regimePath(regimeIndex)}/cycles`
  const set = (index: number, cycle: Cycle) => {
    onChange(
      edit(definition, (draft) => {
        const target = regimeOf(draft, regimeIndex)
        target.cycles = (target.cycles ?? []).map((old, at) => (at === index ? cycle : old))
      }),
    )
  }
  return (
    <section aria-label="Cycles" className="flex flex-col gap-2">
      <h3 className="text-sm font-semibold">Cycles</h3>
      <ul className="flex flex-col gap-2">
        {cycles.map((cycle, index) => {
          const at = `${path}/${index}`
          const reset = typeof cycle.mode === 'object' ? cycle.mode.reset : null
          const skipped = skippedBy(regime, cycle.id)
          return (
            <li
              key={index}
              aria-label={`Cycle ${cycle.id}`}
              className="flex flex-col gap-2 rounded-md border p-2 text-sm"
            >
              <div className="flex flex-wrap items-center gap-2">
                <PathInput
                  path={`${at}/id`}
                  aria-label="Cycle id"
                  className="w-28"
                  value={cycle.id}
                  onChange={(event) => {
                    set(index, { ...cycle, id: event.target.value })
                  }}
                />
                <span>every</span>
                <select
                  aria-label="Cycle level"
                  className={SMALL_SELECT}
                  value={cycle.level}
                  onChange={(event) => {
                    set(index, { ...cycle, level: event.target.value })
                  }}
                >
                  {levels.map((level) => (
                    <option key={level.id} value={level.id}>
                      {level.label}
                    </option>
                  ))}
                </select>
                <span>of</span>
                <PathInput
                  path={`${at}/length`}
                  aria-label="Cycle length"
                  inputMode="numeric"
                  className="w-20"
                  value={String(cycle.length)}
                  onChange={(event) => {
                    set(index, { ...cycle, length: int(event.target.value, 0) })
                  }}
                />
                <span>values, numbered from</span>
                <PathInput
                  path={`${at}/number_start`}
                  aria-label="Cycle first number"
                  inputMode="numeric"
                  className="w-16"
                  value={String(cycle.number_start ?? 1)}
                  onChange={(event) => {
                    set(index, { ...cycle, number_start: int(event.target.value, 1) })
                  }}
                />
                <div className="flex-1" />
                <IconButton
                  label={`Remove cycle ${cycle.id}`}
                  onClick={() => {
                    onChange(
                      edit(definition, (draft) => {
                        const target = regimeOf(draft, regimeIndex)
                        target.cycles = (target.cycles ?? []).filter((_, other) => other !== index)
                      }),
                    )
                  }}
                >
                  <Trash2Icon />
                </IconButton>
              </div>
              {(['names', 'abbrs', 'ids'] as const).map((key) => (
                <label key={key} className="flex items-center gap-2">
                  <span className="w-24 text-muted-foreground">
                    {key === 'names' ? 'Names' : key === 'abbrs' ? 'Abbreviations' : 'Ids'}
                  </span>
                  <PathInput
                    path={`${at}/${key}`}
                    aria-label={`Cycle ${key}`}
                    placeholder="Comma-separated, one per value"
                    value={(cycle[key] ?? []).join(', ')}
                    onChange={(event) => {
                      const items = list(event.target.value)
                      const rest = omit(cycle, key)
                      set(index, items === null ? rest : { ...rest, [key]: items })
                    }}
                  />
                </label>
              ))}
              <div className="flex flex-wrap items-center gap-2">
                <select
                  aria-label="Cycle counting"
                  className={SMALL_SELECT}
                  value={reset === null ? 'continuous' : 'reset'}
                  onChange={(event) => {
                    const coarser = levels[0]?.id ?? cycle.level
                    set(index, {
                      ...cycle,
                      mode: event.target.value === 'reset' ? { reset: coarser } : 'continuous',
                    })
                  }}
                >
                  <option value="continuous">Counts on forever</option>
                  <option value="reset">Restarts every…</option>
                </select>
                {reset !== null && (
                  <select
                    aria-label="Cycle restarts every"
                    className={SMALL_SELECT}
                    value={reset}
                    onChange={(event) => {
                      set(index, { ...cycle, mode: { reset: event.target.value } })
                    }}
                  >
                    {levels.map((level) => (
                      <option key={level.id} value={level.id}>
                        {level.label}
                      </option>
                    ))}
                  </select>
                )}
                {regimeIndex > 0 && reset === null && (
                  <label className="flex items-center gap-1 text-xs">
                    <input
                      type="checkbox"
                      checked={cycle.continue_from_previous_regime === true}
                      onChange={(event) => {
                        const rest = omit(omit(cycle, 'continue_from_previous_regime'), 'anchor')
                        set(
                          index,
                          event.target.checked
                            ? { ...rest, continue_from_previous_regime: true }
                            : { ...rest, anchor: { fields: {}, index: 0 } },
                        )
                      }}
                    />
                    Continues from the previous rules
                  </label>
                )}
              </div>
              {cycle.continue_from_previous_regime !== true && (
                <div className="flex flex-col gap-1">
                  <span className="text-xs text-muted-foreground">
                    {reset === null
                      ? 'Value of a given unit (its date, and its value index from 0):'
                      : 'Value of the first unit in each restart (index from 0):'}
                  </span>
                  {reset === null && (
                    <LocalFields
                      definition={definition}
                      path={`${at}/anchor/fields`}
                      label="Cycle anchor"
                      fields={cycle.anchor?.fields ?? {}}
                      onChange={(fields) => {
                        set(index, { ...cycle, anchor: { ...cycle.anchor, fields } })
                      }}
                    />
                  )}
                  <PathInput
                    path={`${at}/anchor/index`}
                    aria-label="Cycle anchor index"
                    inputMode="numeric"
                    className="w-20"
                    value={String(cycle.anchor?.index ?? 0)}
                    onChange={(event) => {
                      set(index, {
                        ...cycle,
                        anchor: { ...cycle.anchor, index: int(event.target.value, 0) },
                      })
                    }}
                  />
                </div>
              )}
              {skipped.length > 0 && (
                <p className="text-xs text-muted-foreground">Skipped by: {skipped.join(', ')}</p>
              )}
              <FieldErrors errors={errors} path={at} />
            </li>
          )
        })}
      </ul>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="self-start"
        onClick={() => {
          onChange(
            edit(definition, (draft) => {
              const target = regimeOf(draft, regimeIndex)
              const finestLevel = levelsOf(draft)[0]?.id ?? ''
              const day = levelsOf(draft).find((level) => level.id === 'day')?.id ?? finestLevel
              target.cycles = [
                ...(target.cycles ?? []),
                {
                  id: freshId(
                    (target.cycles ?? []).map((cycle) => cycle.id),
                    'week',
                  ),
                  level: day,
                  length: 7,
                  anchor: { fields: { ...target.alignment.fields }, index: 0 },
                },
              ]
            }),
          )
        }}
      >
        <PlusIcon aria-hidden /> Cycle
      </Button>
    </section>
  )
}

// --- eras ----------------------------------------------------------------------------------------

/**
 * Eras (§3.8), in order: names, abbreviation before or after the year, where each starts (the
 * first one has always been), and how its years count (forward from a first year, or backward
 * towards the next era).
 */
export function ErasEditor({
  definition,
  errors,
  onChange,
  scope,
}: StructureProps & { scope: TimeScope }) {
  const eras = definition.eras ?? []
  const set = (next: Era[]) => {
    onChange(
      edit(definition, (draft) => {
        if (next.length === 0) delete draft.eras
        else draft.eras = next
      }),
    )
  }
  const update = (index: number, era: Era) => {
    set(eras.map((old, at) => (at === index ? era : old)))
  }
  return (
    <section aria-label="Eras" className="flex flex-col gap-2">
      <h3 className="text-sm font-semibold">Eras</h3>
      <ol className="flex flex-col gap-2">
        {eras.map((era, index) => {
          const at = `/eras/${index}`
          return (
            <li
              key={index}
              aria-label={`Era ${era.id}`}
              className="flex flex-col gap-2 rounded-md border p-2 text-sm"
            >
              <div className="flex flex-wrap items-center gap-2">
                <PathInput
                  path={`${at}/id`}
                  aria-label="Era id"
                  className="w-24"
                  value={era.id}
                  onChange={(event) => {
                    update(index, { ...era, id: event.target.value })
                  }}
                />
                <PathInput
                  path={`${at}/name`}
                  aria-label="Era name"
                  className="w-48"
                  value={era.name}
                  onChange={(event) => {
                    update(index, { ...era, name: event.target.value })
                  }}
                />
                <PathInput
                  path={`${at}/abbr`}
                  aria-label="Era abbreviation"
                  className="w-20"
                  value={era.abbr}
                  onChange={(event) => {
                    update(index, { ...era, abbr: event.target.value })
                  }}
                />
                <select
                  aria-label="Era abbreviation position"
                  className={SMALL_SELECT}
                  value={era.abbr_position ?? 'suffix'}
                  onChange={(event) => {
                    const rest = omit(era, 'abbr_position')
                    update(
                      index,
                      event.target.value === 'prefix' ? { ...rest, abbr_position: 'prefix' } : rest,
                    )
                  }}
                >
                  <option value="suffix">After the year</option>
                  <option value="prefix">Before the year</option>
                </select>
                <div className="flex-1" />
                <IconButton
                  label={`Move era ${era.id} up`}
                  disabled={index === 0}
                  onClick={() => {
                    set(moved(eras, index, -1))
                  }}
                >
                  <ArrowUpIcon />
                </IconButton>
                <IconButton
                  label={`Move era ${era.id} down`}
                  disabled={index === eras.length - 1}
                  onClick={() => {
                    set(moved(eras, index, 1))
                  }}
                >
                  <ArrowDownIcon />
                </IconButton>
                <IconButton
                  label={`Remove era ${era.id}`}
                  onClick={() => {
                    set(eras.filter((_, other) => other !== index))
                  }}
                >
                  <Trash2Icon />
                </IconButton>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <select
                  aria-label="Era counting"
                  className={SMALL_SELECT}
                  value={era.numbering.direction}
                  onChange={(event) => {
                    update(index, {
                      ...era,
                      numbering: {
                        ...era.numbering,
                        direction: event.target.value === 'backward' ? 'backward' : 'forward',
                      },
                    })
                  }}
                >
                  <option value="forward">Years count up from</option>
                  <option value="backward">Years count down to</option>
                </select>
                <PathInput
                  path={`${at}/numbering/first`}
                  aria-label="Era first year"
                  inputMode="numeric"
                  className="w-20"
                  value={era.numbering.first}
                  onChange={(event) => {
                    update(index, {
                      ...era,
                      numbering: { ...era.numbering, first: event.target.value },
                    })
                  }}
                />
              </div>
              {index === 0 ? (
                <p className="text-xs text-muted-foreground">The first era has always been.</p>
              ) : (
                <DefinitionPointField
                  definition={definition}
                  scope={scope}
                  path={`${at}/start`}
                  label="Begins at"
                  value={
                    era.start ?? {
                      anchor: {
                        kind: 'local',
                        fields: { ...regimeOf(definition).alignment.fields },
                      },
                      precision: finest(definition, regimeOf(definition).alignment.fields),
                    }
                  }
                  regimeChoice={definition.regimes.length > 1}
                  onChange={(start) => {
                    update(index, { ...era, start })
                  }}
                />
              )}
              <FieldErrors errors={errors} path={at} />
            </li>
          )
        })}
      </ol>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="self-start"
        onClick={() => {
          const id = freshId(
            eras.map((era) => era.id),
            'era',
          )
          const first = eras.length === 0
          const fields = regimeOf(definition).alignment.fields
          set([
            ...eras,
            {
              id,
              name: 'Era',
              abbr: 'E',
              numbering: { direction: first ? 'backward' : 'forward', first: '1' },
              ...(first
                ? {}
                : {
                    start: {
                      anchor: { kind: 'local', fields: { ...fields } },
                      precision: finest(definition, fields),
                    },
                  }),
            },
          ])
        }}
      >
        <PlusIcon aria-hidden /> Era
      </Button>
      <FieldErrors errors={errors} path="/eras" />
    </section>
  )
}

// --- overlays ------------------------------------------------------------------------------------

function RationalInput({
  path,
  label,
  value,
  onChange,
}: {
  path: string
  label: string
  value: Rational
  onChange: (value: Rational) => void
}) {
  return (
    <span className="flex items-center gap-1">
      <PathInput
        path={`${path}/num`}
        aria-label={`${label} numerator`}
        inputMode="numeric"
        className="w-32"
        value={value.num}
        onChange={(event) => {
          onChange({ ...value, num: event.target.value })
        }}
      />
      <span>/</span>
      <PathInput
        path={`${path}/den`}
        aria-label={`${label} denominator`}
        inputMode="numeric"
        className="w-24"
        value={value.den}
        onChange={(event) => {
          onChange({ ...value, den: event.target.value })
        }}
      />
    </span>
  )
}

/** "29.530588" days of `unit` base units each, as an exact fraction of base units. */
export function daysToPeriod(days: string, unit: bigint): Rational | null {
  const match = /^(\d+)(?:\.(\d+))?$/.exec(days.trim())
  if (match === null || unit <= 0n) return null
  const fraction = match[2] ?? ''
  const num = BigInt((match[1] ?? '0') + fraction) * unit
  const den = 10n ** BigInt(fraction.length)
  if (num === 0n) return null
  let [a, b] = [num, den]
  while (b !== 0n) [a, b] = [b, a % b]
  return { num: (num / a).toString(), den: (den / a).toString() }
}

/**
 * Overlays (§3.9): cycles that don't divide the calendar's units (moon phases, seasons): a period
 * in base units (exact fraction, with a days helper), an epoch where phase 0 begins, and named
 * phases from fractions of the period.
 */
export function OverlaysEditor({
  definition,
  errors,
  onChange,
  scope,
  dayLength,
}: StructureProps & {
  scope: TimeScope
  /** Base units in one day of the calendar (for the days helper), when it has uniform days. */
  dayLength: bigint | null
}) {
  const overlays = definition.overlays ?? []
  const set = (next: Overlay[]) => {
    onChange(
      edit(definition, (draft) => {
        if (next.length === 0) delete draft.overlays
        else draft.overlays = next
      }),
    )
  }
  const update = (index: number, overlay: Overlay) => {
    set(overlays.map((old, at) => (at === index ? overlay : old)))
  }
  return (
    <section aria-label="Overlays" className="flex flex-col gap-2">
      <h3 className="text-sm font-semibold">Overlays</h3>
      <ul className="flex flex-col gap-2">
        {overlays.map((overlay, index) => {
          const at = `/overlays/${index}`
          const setPhases = (phases: Phase[]) => {
            if (phases.length > 0)
              update(index, { ...overlay, phases: phases as [Phase, ...Phase[]] })
          }
          return (
            <li
              key={index}
              aria-label={`Overlay ${overlay.id}`}
              className="flex flex-col gap-2 rounded-md border p-2 text-sm"
            >
              <div className="flex flex-wrap items-center gap-2">
                <PathInput
                  path={`${at}/id`}
                  aria-label="Overlay id"
                  className="w-24"
                  value={overlay.id}
                  onChange={(event) => {
                    update(index, { ...overlay, id: event.target.value })
                  }}
                />
                <PathInput
                  path={`${at}/name`}
                  aria-label="Overlay name"
                  className="w-40"
                  value={overlay.name}
                  onChange={(event) => {
                    update(index, { ...overlay, name: event.target.value })
                  }}
                />
                <div className="flex-1" />
                <IconButton
                  label={`Remove overlay ${overlay.id}`}
                  onClick={() => {
                    set(overlays.filter((_, other) => other !== index))
                  }}
                >
                  <Trash2Icon />
                </IconButton>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-muted-foreground">Period (base units)</span>
                <RationalInput
                  path={`${at}/period`}
                  label="Overlay period"
                  value={overlay.period}
                  onChange={(period) => {
                    update(index, { ...overlay, period })
                  }}
                />
                {dayLength !== null && (
                  <label className="flex items-center gap-1 text-xs">
                    or in days
                    <input
                      aria-label="Overlay period in days"
                      className="h-8 w-28 rounded-md border bg-transparent px-2"
                      placeholder="29.530588"
                      onChange={(event) => {
                        const period = daysToPeriod(event.target.value, dayLength)
                        if (period !== null) update(index, { ...overlay, period })
                      }}
                    />
                  </label>
                )}
              </div>
              <DefinitionPointField
                definition={definition}
                scope={scope}
                path={`${at}/epoch`}
                label="Phase 0 begins at"
                value={overlay.epoch}
                onChange={(epoch) => {
                  update(index, { ...overlay, epoch })
                }}
              />
              <ol className="flex flex-col gap-1">
                {overlay.phases.map((phase, phaseIndex) => (
                  <li key={phaseIndex} className="flex flex-wrap items-center gap-2">
                    <PathInput
                      path={`${at}/phases/${phaseIndex}/name`}
                      aria-label={`Phase ${phaseIndex + 1} name`}
                      className="w-40"
                      value={phase.name}
                      onChange={(event) => {
                        setPhases(
                          overlay.phases.map((old, other) =>
                            other === phaseIndex ? { ...old, name: event.target.value } : old,
                          ),
                        )
                      }}
                    />
                    <span className="text-xs text-muted-foreground">from</span>
                    <RationalInput
                      path={`${at}/phases/${phaseIndex}/from`}
                      label={`Phase ${phaseIndex + 1} from`}
                      value={phase.from}
                      onChange={(from) => {
                        setPhases(
                          overlay.phases.map((old, other) =>
                            other === phaseIndex ? { ...old, from } : old,
                          ),
                        )
                      }}
                    />
                    <span className="text-xs text-muted-foreground">of the period</span>
                    <IconButton
                      label={`Remove phase ${phaseIndex + 1}`}
                      disabled={overlay.phases.length === 1}
                      onClick={() => {
                        setPhases(overlay.phases.filter((_, other) => other !== phaseIndex))
                      }}
                    >
                      <Trash2Icon />
                    </IconButton>
                  </li>
                ))}
              </ol>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="self-start"
                onClick={() => {
                  setPhases([...overlay.phases, { name: 'Phase', from: { num: '1', den: '2' } }])
                }}
              >
                <PlusIcon aria-hidden /> Phase
              </Button>
              <FieldErrors errors={errors} path={at} />
            </li>
          )
        })}
      </ul>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="self-start"
        onClick={() => {
          set([
            ...overlays,
            {
              id: freshId(
                overlays.map((overlay) => overlay.id),
                'moon',
              ),
              name: 'Moon',
              period: { num: '1', den: '1' },
              epoch: { anchor: { kind: 'absolute', t: '0' }, precision: 'base' },
              phases: [{ name: 'New', from: { num: '0', den: '1' } }],
            },
          ])
        }}
      >
        <PlusIcon aria-hidden /> Overlay
      </Button>
    </section>
  )
}
