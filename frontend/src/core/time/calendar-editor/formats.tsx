import {
  type CompiledCalendar,
  DateError,
  type DisplayOptions,
  formatDate,
  type Formats,
} from '@lore/chronology'
import { useState } from 'react'

import { Button } from '@/components/ui/button'

import { BigNumberInput } from '../big-number-input'
import { edit, levelsOf, part, type Definition } from './model'
import { FieldErrors, PathInput, type StructureProps } from './structure'

/** Every token a pattern of this definition may use (chronology-engine.md §3.11). */
export function tokensFor(definition: Definition): string[] {
  const cycles = [
    ...new Set(
      definition.regimes.flatMap((regime) => (regime.cycles ?? []).map((cycle) => cycle.id)),
    ),
  ]
  const tokens = [
    ...levelsOf(definition)
      .toReversed()
      .flatMap((level) => [
        `{${level.id}}`,
        `{${level.id}.name}`,
        `{${level.id}.abbr}`,
        `{${level.id}:pad2}`,
      ]),
    '{year}',
    '{era_year}',
    '{era}',
    '{era.name}',
    '{base}',
    ...cycles.flatMap((cycle) => [
      `{cycle.${cycle}}`,
      `{cycle.${cycle}.abbr}`,
      `{cycle.${cycle}.n}`,
    ]),
    ...(definition.overlays ?? []).flatMap((overlay) => [
      `{overlay.${overlay.id}}`,
      `{overlay.${overlay.id}.fraction}`,
    ]),
  ]
  // A level named `year` has the same token as the year number.
  return [...new Set(tokens)]
}

/** The token being typed at the end of `text` (after an unclosed `{`), or `null`. */
export function typedToken(text: string): string | null {
  const open = text.lastIndexOf('{')
  if (open < 0 || text.includes('}', open)) return null
  // `{{` is a literal brace.
  if (text.slice(open - 1, open) === '{') return null
  return text.slice(open)
}

function sample(calendar: CompiledCalendar | null, t: bigint, precision: string): string {
  if (calendar === null) return '—'
  try {
    return formatDate(calendar, t, precision)
  } catch (error) {
    if (error instanceof DateError) return error.message
    throw error
  }
}

function PatternRow({
  path,
  label,
  value,
  tokens,
  example,
  errors,
  onChange,
}: {
  errors: StructureProps['errors']
  path: string
  label: string
  value: string
  tokens: readonly string[]
  example: string
  onChange: (pattern: string) => void
}) {
  const [focused, setFocused] = useState(false)
  const typed = typedToken(value)
  const suggestions =
    focused && typed !== null ? tokens.filter((token) => token.startsWith(typed)).slice(0, 12) : []
  return (
    <li className="flex flex-col gap-1">
      <div className="grid grid-cols-[8rem_1fr] items-center gap-2 text-sm">
        <span className="text-muted-foreground">{label}</span>
        <PathInput
          path={path}
          aria-label={`${label} format`}
          placeholder="The default format"
          value={value}
          onFocus={() => {
            setFocused(true)
          }}
          onBlur={() => {
            setFocused(false)
          }}
          onChange={(event) => {
            onChange(event.target.value)
          }}
        />
      </div>
      {suggestions.length > 0 && (
        <div
          aria-label={`${label} tokens`}
          role="group"
          className="ml-[8.5rem] flex flex-wrap gap-1"
        >
          {suggestions.map((token) => (
            <Button
              key={token}
              type="button"
              variant="outline"
              size="sm"
              className="h-6 px-1.5 font-mono text-xs"
              // Keep the input focused while picking.
              onMouseDown={(event) => {
                event.preventDefault()
              }}
              onClick={() => {
                onChange(value.slice(0, value.length - (typed?.length ?? 0)) + token)
              }}
            >
              {token}
            </Button>
          ))}
        </div>
      )}
      <p className="ml-[8.5rem] text-xs text-muted-foreground" data-testid={`sample-${label}`}>
        {example}
      </p>
      <FieldErrors errors={errors} path={path} />
    </li>
  )
}

/**
 * Formats per precision (§3.11): a pattern for each level (empty: the generated default), with
 * the tokens this calendar offers suggested while typing `{`, and a live sample at a chosen
 * moment; intercalary units can have their own patterns.
 */
export function FormatsEditor({
  definition,
  errors,
  onChange,
  calendar,
  sampleAt,
}: StructureProps & { calendar: CompiledCalendar | null; sampleAt: bigint }) {
  const [t, setT] = useState<bigint | null>(sampleAt)
  const [intercalary, setIntercalary] = useState(
    Object.keys(definition.formats?.intercalary ?? {}).length > 0,
  )
  const tokens = tokensFor(definition)
  const levels = levelsOf(definition).toReversed()
  const formats: Formats = definition.formats ?? {}
  const own = (key: string) => {
    const value = formats[key]
    return typeof value === 'string' ? value : ''
  }
  const set = (key: string, pattern: string, inIntercalary: boolean) => {
    onChange(
      edit(definition, (draft) => {
        let next: Formats
        if (inIntercalary) {
          next = { ...(draft.formats ?? {}) }
          const inner = Object.fromEntries(
            Object.entries(next.intercalary ?? {}).filter(([name]) => name !== key),
          )
          if (pattern !== '') inner[key] = pattern
          if (Object.keys(inner).length === 0) delete next.intercalary
          else next.intercalary = inner
        } else {
          next = Object.fromEntries(
            Object.entries(draft.formats ?? {}).filter(([name]) => name !== key),
          )
          if (pattern !== '') next[key] = pattern
        }
        if (Object.keys(next).length === 0) delete draft.formats
        else draft.formats = next
      }),
    )
  }
  const at = t ?? sampleAt
  return (
    <section aria-label="Formats" className="flex flex-col gap-2">
      <h3 className="text-sm font-semibold">Formats</h3>
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        Sample moment
        <BigNumberInput aria-label="Sample moment" value={t} min={0n} onChange={setT} />
      </div>
      <ul className="flex flex-col gap-2">
        {levels.map((level) => (
          <PatternRow
            key={level.id}
            path={`/formats/${part(level.id)}`}
            label={level.label}
            value={own(level.id)}
            tokens={tokens}
            errors={errors}
            example={sample(calendar, at, level.id)}
            onChange={(pattern) => {
              set(level.id, pattern, false)
            }}
          />
        ))}
      </ul>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={intercalary}
          onChange={(event) => {
            setIntercalary(event.target.checked)
          }}
        />
        Other formats for intercalary units
      </label>
      {intercalary && (
        <ul className="flex flex-col gap-2">
          {levels.map((level) => (
            <PatternRow
              key={level.id}
              path={`/formats/intercalary/${part(level.id)}`}
              label={`Intercalary ${level.label}`}
              value={formats.intercalary?.[level.id] ?? ''}
              tokens={tokens}
              errors={errors}
              example=""
              onChange={(pattern) => {
                set(level.id, pattern, true)
              }}
            />
          ))}
        </ul>
      )}
      <FieldErrors errors={errors} path="/formats" exact />
    </section>
  )
}

const DISPLAY_DEFAULTS: Required<DisplayOptions> = {
  circa: 'c. ',
  digit_group: ',',
  scientific_threshold: 16,
  significant_digits: 4,
  range_separator: ' – ',
}

/** Display options (circa prefix, digit grouping, scientific notation, range separator). */
export function DisplayEditor({ definition, errors, onChange }: StructureProps) {
  const display = definition.display ?? {}
  const set = (key: keyof DisplayOptions, value: string | number | null) => {
    onChange(
      edit(definition, (draft) => {
        const next: DisplayOptions = Object.fromEntries(
          Object.entries(draft.display ?? {}).filter(([name]) => name !== key),
        )
        if (value !== null) Object.assign(next, { [key]: value })
        if (Object.keys(next).length === 0) delete draft.display
        else draft.display = next
      }),
    )
  }
  const text = (key: 'circa' | 'digit_group' | 'range_separator', label: string) => (
    <label className="grid grid-cols-[12rem_1fr] items-center gap-2">
      {label}
      <PathInput
        path={`/display/${key}`}
        aria-label={label}
        placeholder={JSON.stringify(DISPLAY_DEFAULTS[key])}
        value={display[key] ?? ''}
        onChange={(event) => {
          set(key, event.target.value === '' ? null : event.target.value)
        }}
      />
    </label>
  )
  const number = (key: 'scientific_threshold' | 'significant_digits', label: string) => (
    <label className="grid grid-cols-[12rem_1fr] items-center gap-2">
      {label}
      <PathInput
        path={`/display/${key}`}
        aria-label={label}
        inputMode="numeric"
        placeholder={String(DISPLAY_DEFAULTS[key])}
        value={display[key] === undefined ? '' : String(display[key])}
        onChange={(event) => {
          const value = Number.parseInt(event.target.value, 10)
          set(key, Number.isNaN(value) ? null : value)
        }}
      />
    </label>
  )
  return (
    <section aria-label="Display" className="flex flex-col gap-2 text-sm">
      <h3 className="text-sm font-semibold">Display</h3>
      {text('circa', 'Circa prefix')}
      {text('digit_group', 'Digit grouping')}
      {number('scientific_threshold', 'Scientific notation from (digits)')}
      {number('significant_digits', 'Significant digits')}
      {text('range_separator', 'Range separator')}
      <FieldErrors errors={errors} path="/display" />
    </section>
  )
}
