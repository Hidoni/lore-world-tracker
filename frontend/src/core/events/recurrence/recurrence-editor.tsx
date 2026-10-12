import {
  type CalendarRule,
  type Cycle,
  type EndSpec,
  type Exclusion,
  type LevelSelector,
  type Limit,
  type PeriodFilter,
  type RecurrenceRule,
  type RuleValidationError,
  type TimePoint,
  nextOccurrences,
  RecurrenceError,
  validateRule,
} from '@lore/chronology'
import { PlusIcon, Trash2Icon } from 'lucide-react'
import { useEffect, useId, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import {
  BigNumberInput,
  formatIn,
  TimePointPicker,
  type DimensionTime,
  type Lens,
} from '@/core/time'
import { useTimeResolution } from '@/data'
import { cn } from '@/lib/utils'

import {
  allCycles,
  availablePresets,
  continuousCycles,
  cycleValueId,
  detectPreset,
  presetRule,
  ruleTimePoints,
  summarize,
  type PresetId,
  type PresetOptions,
  type RuleScope,
} from './rule-model'

const SELECT =
  'h-8 rounded-md border border-input bg-transparent px-2 text-sm shadow-xs focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none'

const PRESET_LABELS: Record<PresetId, string> = {
  yearly: 'Every year on this date',
  monthly: 'Every month on this day',
  nth_weekday: 'Every month on this weekday (e.g. the second Tuesday)',
  weekly: 'Every week on these days',
  interval: 'Every N base units',
  custom: 'Advanced',
}

/** Plain words for the rule problems people meet most (recurrence.md §9). */
const MESSAGES: Record<string, string> = {
  'rule.series_start_not_occurrence':
    'The series start doesn’t match the rule: the first occurrence comes later.',
  'rule.series_end_not_duration':
    'A recurring event lasts a duration, an instant, or an unknown time (not an end date).',
  'rule.until_before_start': 'The series ends before it starts.',
  'rule.bad_interval': 'The interval must be at least 1.',
  'rule.bad_filter': 'A filter doesn’t fit this period.',
  'rule.bad_selector_level': 'Each position must be at a finer level than the one before.',
  'rule.unknown_slot': 'A value names nothing in this calendar.',
  'rule.bad_nth': '“0th” isn’t a position: count from 1, or from −1 for the last.',
  'rule.bad_time_fields': 'The time fields must be consecutive levels below the period.',
  'rule.cycle_not_continuous': 'Only cycles that never restart can be a period.',
  'rule.bad_exclusion': 'An excluded range ends before it starts.',
  'anchor.unresolved': 'A time point of the rule has no moment yet.',
}

function problemText(error: RuleValidationError): string {
  return MESSAGES[error.code] ?? error.message
}

/** "a, b, c" → ["a", "b", "c"] (`null` when empty). */
function splitList(text: string): [string, ...string[]] | null {
  const items = text
    .split(',')
    .map((item) => item.trim())
    .filter((item) => item !== '')
  return items.length === 0 ? null : (items as [string, ...string[]])
}

const ABSOLUTE_ZERO: TimePoint = { anchor: { kind: 'absolute', t: '0' }, precision: 'base' }

// --- limit ---------------------------------------------------------------------------------------

function LimitEditor({
  vault,
  dimension,
  lenses,
  value,
  onChange,
}: {
  vault: string
  dimension: DimensionTime
  lenses: readonly Lens[]
  value: Limit
  onChange: (limit: Limit) => void
}) {
  const id = useId()
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <label htmlFor={id}>Ends</label>
        <select
          id={id}
          className={SELECT}
          value={value.kind}
          onChange={(event) => {
            const kind = event.target.value
            onChange(
              kind === 'count'
                ? { kind: 'count', count: '10' }
                : kind === 'until'
                  ? { kind: 'until', until: ABSOLUTE_ZERO }
                  : { kind: 'never' },
            )
          }}
        >
          <option value="never">Never</option>
          <option value="count">After a number of occurrences</option>
          <option value="until">At a time point (inclusive)</option>
        </select>
        {value.kind === 'count' && (
          <BigNumberInput
            aria-label="Occurrences"
            className="w-32"
            value={BigInt(value.count)}
            min={1n}
            onChange={(count) => {
              if (count !== null) onChange({ kind: 'count', count: count.toString() })
            }}
          />
        )}
      </div>
      {value.kind === 'until' && (
        <TimePointPicker
          vault={vault}
          dimension={dimension}
          lenses={lenses}
          value={value.until}
          label="Until"
          onChange={(until) => {
            if (until !== null) onChange({ kind: 'until', until })
          }}
        />
      )}
    </div>
  )
}

// --- advanced ------------------------------------------------------------------------------------

function FiltersEditor({
  calendar,
  filters,
  onChange,
}: {
  calendar: RuleScope['calendar']
  filters: readonly PeriodFilter[]
  onChange: (filters: PeriodFilter[]) => void
}) {
  const cycles = calendar === null ? [] : allCycles(calendar)
  const firstCycle = cycles[0]
  const set = (index: number, filter: PeriodFilter | null) => {
    const next = filters.flatMap((old, at) =>
      at === index ? (filter === null ? [] : [filter]) : [old],
    )
    onChange(next)
  }
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="text-sm font-medium">Only periods that…</legend>
      {filters.length === 0 && <p className="text-xs text-muted-foreground">Every period.</p>}
      <ul className="flex flex-col gap-1">
        {filters.map((filter, index) => {
          const negate = 'not' in filter
          const inner = 'not' in filter ? filter.not : filter
          const wrap = (made: PeriodFilter, not = negate): PeriodFilter =>
            not ? { not: made } : made
          let row
          if ('mod' in inner) {
            row = (
              <>
                <span>have a</span>
                <select
                  aria-label={`Filter ${index + 1} counts`}
                  className={SELECT}
                  value={inner.of ?? 'number'}
                  onChange={(event) => {
                    set(index, wrap({ ...inner, of: event.target.value as 'number' | 'ordinal' }))
                  }}
                >
                  <option value="number">number (astronomical for years)</option>
                  <option value="ordinal">global ordinal</option>
                </select>
                <span>of</span>
                <Input
                  aria-label={`Filter ${index + 1} remainder`}
                  className="h-8 w-16"
                  value={inner.eq}
                  onChange={(event) => {
                    set(index, wrap({ ...inner, eq: event.target.value.trim() }))
                  }}
                />
                <span>modulo</span>
                <Input
                  aria-label={`Filter ${index + 1} modulus`}
                  className="h-8 w-16"
                  value={inner.mod}
                  onChange={(event) => {
                    set(index, wrap({ ...inner, mod: event.target.value.trim() }))
                  }}
                />
              </>
            )
          } else if ('cycle' in inner) {
            row = (
              <>
                <span>fall on</span>
                <select
                  aria-label={`Filter ${index + 1} cycle`}
                  className={SELECT}
                  value={inner.cycle}
                  onChange={(event) => {
                    set(index, wrap({ ...inner, cycle: event.target.value }))
                  }}
                >
                  {cycles.map((cycle) => (
                    <option key={cycle.id} value={cycle.id}>
                      {cycle.id}
                    </option>
                  ))}
                </select>
                <Input
                  aria-label={`Filter ${index + 1} values`}
                  placeholder="Values, comma-separated"
                  className="h-8 w-56"
                  defaultValue={inner.in.join(', ')}
                  onBlur={(event) => {
                    const values = splitList(event.target.value)
                    if (values !== null) set(index, wrap({ ...inner, in: values }))
                  }}
                />
              </>
            )
          } else if ('in' in inner) {
            row = (
              <>
                <span>are number or slot</span>
                <Input
                  aria-label={`Filter ${index + 1} values`}
                  placeholder="Numbers or slot ids, comma-separated"
                  className="h-8 w-56"
                  defaultValue={inner.in.join(', ')}
                  onBlur={(event) => {
                    const values = splitList(event.target.value)
                    if (values !== null) set(index, wrap({ in: values }))
                  }}
                />
              </>
            )
          } else {
            row = <code className="text-xs">{JSON.stringify(inner)} (edit in the JSON below)</code>
          }
          return (
            <li key={index} className="flex flex-wrap items-center gap-2 text-sm">
              <label className="flex items-center gap-1">
                <input
                  type="checkbox"
                  checked={negate}
                  onChange={(event) => {
                    set(index, wrap(inner, event.target.checked))
                  }}
                />
                not
              </label>
              {row}
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-7"
                aria-label={`Remove filter ${index + 1}`}
                onClick={() => {
                  set(index, null)
                }}
              >
                <Trash2Icon aria-hidden />
              </Button>
            </li>
          )
        })}
      </ul>
      <div className="flex flex-wrap gap-1">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => {
            onChange([...filters, { mod: '2', eq: '1', of: 'number' }])
          }}
        >
          <PlusIcon aria-hidden /> Every Nth
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => {
            onChange([...filters, { in: ['1'] }])
          }}
        >
          <PlusIcon aria-hidden /> By number or slot
        </Button>
        {firstCycle !== undefined && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => {
              onChange([...filters, { cycle: firstCycle.id, in: [cycleValueId(firstCycle, 0)] }])
            }}
          >
            <PlusIcon aria-hidden /> By cycle value
          </Button>
        )}
      </div>
    </fieldset>
  )
}

function SelectorRow({
  index,
  calendar,
  selector,
  onChange,
  onRemove,
}: {
  index: number
  calendar: NonNullable<RuleScope['calendar']>
  selector: LevelSelector
  onChange: (selector: LevelSelector) => void
  onRemove: () => void
}) {
  const levels = [...calendar.levels].reverse()
  const cycles = allCycles(calendar).filter((cycle) => cycle.level === selector.level)
  const type = 'all' in selector ? 'all' : 'cycle' in selector ? 'cycle' : 'values'
  const label = `Position ${index + 1}`
  return (
    <li className="flex flex-wrap items-center gap-2 text-sm">
      <select
        aria-label={`${label} level`}
        className={SELECT}
        value={selector.level}
        onChange={(event) => {
          onChange({ ...selector, level: event.target.value })
        }}
      >
        {levels.map((level) => (
          <option key={level} value={level}>
            {calendar.definition.levels.find((each) => each.id === level)?.label ?? level}
          </option>
        ))}
      </select>
      <select
        aria-label={`${label} kind`}
        className={SELECT}
        value={type}
        onChange={(event) => {
          const next = event.target.value
          const cycle = allCycles(calendar).find((each) => each.level === selector.level)
          onChange(
            next === 'all'
              ? { level: selector.level, all: true }
              : next === 'cycle' && cycle !== undefined
                ? {
                    level: selector.level,
                    cycle: { id: cycle.id, values: [cycleValueId(cycle, 0)] },
                  }
                : { level: selector.level, values: ['1'] },
          )
        }}
      >
        <option value="values">numbers or slots</option>
        {cycles.length > 0 && <option value="cycle">cycle values</option>}
        <option value="all">every one</option>
      </select>
      {'values' in selector && (
        <Input
          aria-label={`${label} values`}
          placeholder="1, 15, -1 (last), or slot ids"
          className="h-8 w-56"
          defaultValue={selector.values.join(', ')}
          onBlur={(event) => {
            const values = splitList(event.target.value)
            if (values !== null) onChange({ level: selector.level, values })
          }}
        />
      )}
      {'cycle' in selector && (
        <>
          <Input
            aria-label={`${label} cycle values`}
            placeholder="Values, comma-separated"
            className="h-8 w-48"
            defaultValue={selector.cycle.values.join(', ')}
            onBlur={(event) => {
              const values = splitList(event.target.value)
              if (values !== null) onChange({ ...selector, cycle: { ...selector.cycle, values } })
            }}
          />
          <Input
            aria-label={`${label} nth`}
            placeholder="nth: 1, -1 (optional)"
            className="h-8 w-36"
            defaultValue={(selector.cycle.nth ?? []).join(', ')}
            onBlur={(event) => {
              onChange({
                ...selector,
                cycle: { ...selector.cycle, nth: splitList(event.target.value) },
              })
            }}
          />
        </>
      )}
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="size-7"
        aria-label={`Remove position ${index + 1}`}
        onClick={onRemove}
      >
        <Trash2Icon aria-hidden />
      </Button>
    </li>
  )
}

function ExclusionsEditor({
  vault,
  dimension,
  lenses,
  value,
  onChange,
}: {
  vault: string
  dimension: DimensionTime
  lenses: readonly Lens[]
  value: readonly Exclusion[]
  onChange: (exclusions: Exclusion[]) => void
}) {
  const set = (index: number, exclusion: Exclusion | null) => {
    onChange(
      value.flatMap((old, at) => (at === index ? (exclusion === null ? [] : [exclusion]) : [old])),
    )
  }
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="text-sm font-medium">Skip occurrences starting in…</legend>
      {value.map((exclusion, index) => (
        <div key={index} className="flex flex-col gap-2 rounded-md border p-2">
          <div className="grid gap-2 md:grid-cols-2">
            <TimePointPicker
              vault={vault}
              dimension={dimension}
              lenses={lenses}
              value={exclusion.from}
              label={`Excluded from (${index + 1})`}
              onChange={(from) => {
                if (from !== null) set(index, { ...exclusion, from })
              }}
            />
            <TimePointPicker
              vault={vault}
              dimension={dimension}
              lenses={lenses}
              value={exclusion.to}
              label={`Excluded until (${index + 1})`}
              onChange={(to) => {
                if (to !== null) set(index, { ...exclusion, to })
              }}
            />
          </div>
          <div className="flex items-center gap-2">
            <Input
              aria-label={`Exclusion ${index + 1} note`}
              placeholder="Why (optional)"
              className="h-8"
              value={exclusion.note ?? ''}
              onChange={(event) => {
                set(index, { ...exclusion, note: event.target.value || null })
              }}
            />
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                set(index, null)
              }}
            >
              Remove
            </Button>
          </div>
        </div>
      ))}
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="self-start"
        onClick={() => {
          onChange([...value, { from: ABSOLUTE_ZERO, to: ABSOLUTE_ZERO }])
        }}
      >
        <PlusIcon aria-hidden /> Excluded range
      </Button>
    </fieldset>
  )
}

/** Advanced mode (recurrence.md §2): every part of a calendar or interval rule, plus JSON. */
function AdvancedEditor({
  vault,
  dimension,
  lenses,
  scope,
  rule,
  onChange,
}: {
  vault: string
  dimension: DimensionTime
  lenses: readonly Lens[]
  scope: RuleScope
  rule: RecurrenceRule
  onChange: (rule: RecurrenceRule) => void
}) {
  const [json, setJson] = useState<string | null>(null)
  const [jsonError, setJsonError] = useState<string | null>(null)
  const calendar = scope.calendar
  const exclusions = (
    <ExclusionsEditor
      vault={vault}
      dimension={dimension}
      lenses={lenses}
      value={rule.exclusions ?? []}
      onChange={(next) => {
        onChange({ ...rule, exclusions: next })
      }}
    />
  )
  const jsonEditor = (
    <details
      className="text-sm"
      onToggle={(event) => {
        if (event.currentTarget.open) setJson(JSON.stringify(rule, null, 2))
      }}
    >
      <summary className="cursor-pointer text-muted-foreground">Rule JSON</summary>
      <Textarea
        aria-label="Rule JSON"
        spellCheck={false}
        className="mt-1 min-h-48 font-mono text-xs"
        value={json ?? ''}
        onChange={(event) => {
          setJson(event.target.value)
          try {
            onChange(JSON.parse(event.target.value) as RecurrenceRule)
            setJsonError(null)
          } catch (error) {
            setJsonError(error instanceof Error ? error.message : 'Not JSON.')
          }
        }}
      />
      {jsonError !== null && <p className="text-destructive">Not valid JSON: {jsonError}</p>}
    </details>
  )
  if (rule.kind === 'interval' || calendar === null) {
    return (
      <div className="flex flex-col gap-3">
        {rule.kind === 'interval' && (
          <div className="flex items-center gap-2 text-sm">
            Every
            <BigNumberInput
              aria-label="Every (base units)"
              className="w-48"
              value={BigInt(rule.every)}
              min={1n}
              onChange={(every) => {
                if (every !== null) onChange({ ...rule, every: every.toString() })
              }}
            />
            {dimension.baseUnit.plural}
          </div>
        )}
        {exclusions}
        {jsonEditor}
      </div>
    )
  }
  const calendarRule: CalendarRule = rule
  const levels = [...calendar.levels].reverse()
  const freqValue =
    'level' in calendarRule.freq
      ? `level:${calendarRule.freq.level}`
      : `cycle:${calendarRule.freq.cycle}`
  const freqLevel =
    'level' in calendarRule.freq
      ? calendarRule.freq.level
      : (continuousCycles(calendar).find(
          (cycle) => 'cycle' in calendarRule.freq && cycle.id === calendarRule.freq.cycle,
        )?.level ?? null)
  const below = freqLevel === null ? [] : levels.slice(levels.indexOf(freqLevel) + 1)
  const path = calendarRule.select?.path ?? []
  const setPath = (next: LevelSelector[]) => {
    onChange({
      ...calendarRule,
      select: next.length === 0 ? null : { path: next as [LevelSelector, ...LevelSelector[]] },
    } as CalendarRule)
  }
  const time = calendarRule.time?.fields ?? {}
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        Every
        <Input
          aria-label="Interval"
          className="h-8 w-16"
          value={calendarRule.interval ?? '1'}
          onChange={(event) => {
            const interval = event.target.value.trim()
            onChange({ ...calendarRule, interval: interval === '' ? '1' : interval })
          }}
        />
        <select
          aria-label="Period"
          className={SELECT}
          value={freqValue}
          onChange={(event) => {
            const [kind, id] = event.target.value.split(':') as [string, string]
            onChange({
              ...calendarRule,
              freq: kind === 'level' ? { level: id } : { cycle: id },
              select: null,
            })
          }}
        >
          {levels.map((level) => (
            <option key={level} value={`level:${level}`}>
              {calendar.definition.levels.find((each) => each.id === level)?.label ?? level}
            </option>
          ))}
          {continuousCycles(calendar).map((cycle) => (
            <option key={cycle.id} value={`cycle:${cycle.id}`}>
              {cycle.id} (cycle)
            </option>
          ))}
        </select>
      </div>
      <FiltersEditor
        calendar={calendar}
        filters={calendarRule.filters ?? []}
        onChange={(filters) => {
          onChange({ ...calendarRule, filters })
        }}
      />
      <fieldset className="flex flex-col gap-2">
        <legend className="text-sm font-medium">At these positions in each period</legend>
        {path.length === 0 ? (
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            The series start’s own position.
            <label className="flex items-center gap-1 text-foreground">
              When it doesn’t exist:
              <select
                aria-label="When the position doesn't exist"
                className={SELECT}
                value={calendarRule.missing ?? 'skip'}
                onChange={(event) => {
                  onChange({
                    ...calendarRule,
                    missing: event.target.value as 'skip' | 'constrain',
                  })
                }}
              >
                <option value="skip">skip that period</option>
                <option value="constrain">use the nearest valid date</option>
              </select>
            </label>
          </div>
        ) : (
          <ul className="flex flex-col gap-1">
            {path.map((selector, index) => (
              <SelectorRow
                key={index}
                index={index}
                calendar={calendar}
                selector={selector}
                onChange={(next) => {
                  setPath(path.map((old, at) => (at === index ? next : old)))
                }}
                onRemove={() => {
                  setPath(path.filter((_old, at) => at !== index))
                }}
              />
            ))}
          </ul>
        )}
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="self-start"
          disabled={below.length === 0}
          onClick={() => {
            const last = path.at(-1)?.level ?? freqLevel
            const next = levels[levels.indexOf(last ?? '') + 1] ?? below[0]
            if (next !== undefined) setPath([...path, { level: next, values: ['1'] }])
          }}
        >
          <PlusIcon aria-hidden /> Position
        </Button>
      </fieldset>
      <fieldset className="flex flex-col gap-1 text-sm">
        <legend className="font-medium">Time of day (empty: the series start’s)</legend>
        <div className="flex flex-wrap gap-2">
          {below.map((level) => (
            <label key={level} className="flex items-center gap-1">
              {calendar.definition.levels.find((each) => each.id === level)?.label ?? level}
              <Input
                aria-label={`Time ${level}`}
                className="h-8 w-16"
                value={time[level] ?? ''}
                onChange={(event) => {
                  const value = event.target.value.trim()
                  const fields = Object.fromEntries(
                    Object.entries({ ...time, [level]: value }).filter(
                      (entry): entry is [string, string] =>
                        entry[1] !== undefined && entry[1] !== '',
                    ),
                  )
                  onChange({
                    ...calendarRule,
                    time: Object.keys(fields).length === 0 ? null : { fields },
                  })
                }}
              />
            </label>
          ))}
        </div>
      </fieldset>
      {exclusions}
      {jsonEditor}
    </div>
  )
}

// --- the editor ----------------------------------------------------------------------------------

function WeekdayPicker({
  cycle,
  value,
  onChange,
}: {
  cycle: Cycle
  value: readonly string[]
  onChange: (values: string[]) => void
}) {
  return (
    <fieldset className="flex flex-wrap items-center gap-2 text-sm">
      <legend className="sr-only">Days</legend>
      {Array.from({ length: cycle.length }, (_unused, index) => {
        const id = cycleValueId(cycle, index)
        const name = cycle.names?.[index] ?? id
        return (
          <label key={id} className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={value.includes(id)}
              onChange={(event) => {
                onChange(
                  event.target.checked ? [...value, id] : value.filter((each) => each !== id),
                )
              }}
            />
            {name}
          </label>
        )
      })}
    </fieldset>
  )
}

function presetOptionsOf(rule: RecurrenceRule | null): PresetOptions {
  if (rule === null) return {}
  if (rule.kind === 'interval') return { every: rule.every }
  const selector = rule.select?.path[0]
  return {
    ...(rule.interval === undefined ? {} : { every: rule.interval }),
    ...(selector !== undefined && 'cycle' in selector ? { weekdays: selector.cycle.values } : {}),
  }
}

/**
 * The recurrence editor (frontend.md §8, recurrence.md §10): presets built from the series start
 * (yearly on this date, monthly on this day, the nth weekday of the month, weekly on these days,
 * every N base units) or an advanced mode exposing every part of the rule; when it ends (never,
 * after N occurrences, until a time point); a summary in words; the next 10 occurrences and the
 * rule's problems from the TS engine (`nextOccurrences`, `validateRule`). Time points of the rule
 * (the series start, `until`, exclusions) are resolved by the server.
 */
export function RecurrenceEditor({
  vault,
  dimension,
  lenses,
  start,
  end,
  value,
  onChange,
}: {
  vault: string
  dimension: DimensionTime
  lenses: readonly Lens[]
  /** The series start (the rule is built around it). */
  start: TimePoint | null
  /** The series' end spec: the occurrence duration. */
  end: EndSpec | null
  value: RecurrenceRule | null
  onChange: (rule: RecurrenceRule | null) => void
}) {
  const id = useId()
  const calendars = lenses.filter((lens) => lens.calendar !== null)
  const [calendarId, setCalendarId] = useState<string | null>(
    value?.kind === 'calendar'
      ? value.calendar_id
      : (calendars.find((lens) => lens.id === dimension.defaultCalendarId)?.id ??
          calendars[0]?.id ??
          null),
  )
  const lens = calendars.find((candidate) => candidate.id === calendarId) ?? null
  const points = value === null ? [] : ruleTimePoints(value)
  const resolution = useTimeResolution(
    vault,
    start === null
      ? null
      : {
          dimension_id: dimension.id,
          items: [start, ...points.map(([, point]) => point)].map((point) => ({
            time_point: point as never,
          })),
        },
  )
  const items = resolution.data?.items ?? []
  const startT = items[0]?.start.t ?? null
  const scope: RuleScope = {
    calendarId,
    calendar: lens?.calendar ?? null,
    start: startT,
    baseUnit: dimension.baseUnit,
  }
  const [mode, setMode] = useState<PresetId>(() =>
    value === null ? 'yearly' : detectPreset(value, scope),
  )
  const [options, setOptions] = useState<PresetOptions>(() => presetOptionsOf(value))

  // Presets follow the series start and the calendar.
  const built =
    value === null || mode === 'custom'
      ? null
      : presetRule(mode, scope, { ...options, limit: value.limit })
  const builtJson = built === null ? null : JSON.stringify(built)
  useEffect(() => {
    if (builtJson !== null && builtJson !== JSON.stringify(value)) {
      onChange(JSON.parse(builtJson) as RecurrenceRule)
    }
    // `value` is compared, not followed: a preset rebuilds only when its inputs change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [builtJson])

  const resolved: Record<string, bigint> = {}
  for (const [index, [pointer]] of points.entries()) {
    const t = items[index + 1]?.start.t
    if (t !== undefined && t !== null) resolved[pointer] = t
  }
  const seriesEnd: EndSpec =
    end === null || end.kind === 'time_point' || end.kind === 'end_of_time'
      ? { kind: 'instant' }
      : end
  const ctx =
    startT === null
      ? null
      : {
          seriesStart: startT,
          end: seriesEnd,
          dimensionDuration: dimension.duration,
          calendar: value?.kind === 'calendar' ? (lens?.calendar ?? null) : null,
          resolved,
        }
  let problems: RuleValidationError[] = []
  let upcoming: bigint[] = []
  if (value !== null && ctx !== null) {
    try {
      problems = validateRule(value, ctx)
      if (!problems.some((problem) => problem.severity === 'error')) {
        upcoming = nextOccurrences(value, ctx, ctx.seriesStart - 1n, 10).map((item) => item.start)
      }
    } catch (error) {
      if (!(error instanceof RecurrenceError)) throw error
      problems = [
        ...error.errors,
        ...(error.errors.length === 0
          ? [{ code: error.code, path: '', message: error.message, severity: 'error' as const }]
          : []),
      ]
    }
  }
  const weekCycle = scope.calendar === null ? undefined : continuousCycles(scope.calendar)[0]
  const showLens = lens ?? lenses[0] ?? null
  const precision = start?.precision ?? 'base'
  const untilText = (() => {
    const t = resolved['/limit/until']
    if (t === undefined || showLens === null) return null
    return formatIn(showLens, { t, precision: 'day' }, dimension, lenses)
  })()

  return (
    <section aria-label="Recurrence" className="flex flex-col gap-3 rounded-md border p-3">
      <label className="flex items-center gap-2 text-sm font-medium">
        <input
          type="checkbox"
          checked={value !== null}
          onChange={(event) => {
            if (!event.target.checked) {
              onChange(null)
              return
            }
            const preset = scope.calendar === null ? 'interval' : 'yearly'
            setMode(preset)
            onChange(
              presetRule(preset, scope) ?? {
                kind: 'interval',
                every: '86400',
                limit: { kind: 'never' },
              },
            )
          }}
        />
        Repeats
      </label>
      {value !== null && (
        <>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <label htmlFor={`${id}-preset`}>Pattern</label>
            <select
              id={`${id}-preset`}
              className={SELECT}
              value={mode}
              onChange={(event) => {
                const next = event.target.value as PresetId
                setMode(next)
                if (next === 'custom') return
                // "Every N" counts periods or base units: it doesn't carry across.
                const kept =
                  (next === 'interval') === (mode === 'interval')
                    ? options
                    : { ...options, every: undefined }
                setOptions(kept)
                const rule = presetRule(next, scope, { ...kept, limit: value.limit })
                if (rule !== null) onChange(rule)
              }}
            >
              {availablePresets(scope).map((preset) => (
                <option key={preset} value={preset}>
                  {PRESET_LABELS[preset]}
                </option>
              ))}
            </select>
            {calendars.length > 1 && value.kind === 'calendar' && (
              <>
                <label htmlFor={`${id}-calendar`}>in</label>
                <select
                  id={`${id}-calendar`}
                  className={SELECT}
                  value={calendarId ?? ''}
                  onChange={(event) => {
                    setCalendarId(event.target.value)
                    if (mode === 'custom') {
                      onChange({ ...value, calendar_id: event.target.value })
                    }
                  }}
                >
                  {calendars.map((candidate) => (
                    <option key={candidate.id} value={candidate.id}>
                      {candidate.name}
                    </option>
                  ))}
                </select>
              </>
            )}
          </div>
          {mode !== 'custom' && mode !== 'interval' && (
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <label htmlFor={`${id}-every`}>Every</label>
              <Input
                id={`${id}-every`}
                className="h-8 w-16"
                value={options.every ?? '1'}
                onChange={(event) => {
                  setOptions({ ...options, every: event.target.value.trim() || '1' })
                }}
              />
              <span>
                {mode === 'yearly' ? 'year(s)' : mode === 'weekly' ? 'week(s)' : 'month(s)'}
              </span>
            </div>
          )}
          {mode === 'weekly' && weekCycle !== undefined && (
            <WeekdayPicker
              cycle={weekCycle}
              value={
                options.weekdays ??
                (value.kind === 'calendar' &&
                value.select?.path[0] &&
                'cycle' in value.select.path[0]
                  ? value.select.path[0].cycle.values
                  : [])
              }
              onChange={(weekdays) => {
                setOptions({ ...options, weekdays })
              }}
            />
          )}
          {mode === 'interval' && value.kind === 'interval' && (
            <div className="flex items-center gap-2 text-sm">
              Every
              <BigNumberInput
                aria-label="Every (base units)"
                className="w-48"
                value={BigInt(value.every)}
                min={1n}
                onChange={(every) => {
                  if (every !== null) setOptions({ ...options, every: every.toString() })
                }}
              />
              {dimension.baseUnit.plural}
            </div>
          )}
          {mode === 'custom' && (
            <AdvancedEditor
              vault={vault}
              dimension={dimension}
              lenses={lenses}
              scope={scope}
              rule={value}
              onChange={onChange}
            />
          )}
          <LimitEditor
            vault={vault}
            dimension={dimension}
            lenses={lenses}
            value={value.limit}
            onChange={(limit) => {
              onChange({ ...value, limit })
            }}
          />
          <p className="text-sm font-medium" data-testid="recurrence-summary">
            {summarize(value, scope, { until: untilText })}
          </p>
          {problems.length > 0 && (
            <ul aria-label="Rule problems" className="flex flex-col gap-0.5 text-sm">
              {problems.map((problem) => (
                <li
                  key={`${problem.code}:${problem.path}`}
                  className={cn(
                    problem.severity === 'warning'
                      ? 'text-amber-700 dark:text-amber-400'
                      : 'text-destructive',
                  )}
                >
                  {problemText(problem)}
                </li>
              ))}
            </ul>
          )}
          {start === null ? (
            <p className="text-xs text-muted-foreground">Set the start to preview occurrences.</p>
          ) : (
            <section aria-label="Next occurrences" className="text-sm">
              <h4 className="text-xs font-medium text-muted-foreground uppercase">
                Next occurrences
              </h4>
              {upcoming.length === 0 ? (
                <p className="text-muted-foreground">None.</p>
              ) : (
                <ol className="ml-5 list-decimal">
                  {upcoming.map((t) => (
                    <li key={t.toString()}>
                      {showLens === null
                        ? t.toString()
                        : (formatIn(showLens, { t, precision }, dimension, lenses) ?? t.toString())}
                    </li>
                  ))}
                </ol>
              )}
            </section>
          )}
        </>
      )}
    </section>
  )
}
