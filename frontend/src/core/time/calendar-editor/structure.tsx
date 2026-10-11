import type {
  DefinitionTimePoint,
  Level,
  Predicate,
  Regime,
  SequenceChild,
  Template,
  ValidationError,
  YearPattern,
} from '@lore/chronology'
import { ArrowDownIcon, ArrowUpIcon, PlusIcon, Trash2Icon } from 'lucide-react'
import type { ComponentProps, ReactNode } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

import { SELECT_CLASS } from '../select'
import {
  childLevel,
  edit,
  errorMessage,
  errorsAt,
  freshId,
  levelsOf,
  NEW_PREDICATE,
  omit,
  omitKey,
  newChild,
  newPattern,
  newTemplate,
  part,
  regimeOf,
  regimePath,
  sharedSlotIds,
  templatesAt,
  type Definition,
} from './model'

export interface StructureProps {
  definition: Definition
  errors: readonly ValidationError[]
  onChange: (definition: Definition) => void
  /** The regime the regime-scoped editors show (default: the first). */
  regimeIndex?: number
}

/** A list the schema requires to be non-empty (the editors never empty them). */
function nonEmpty<T>(list: T[]): [T, ...T[]] {
  return list as [T, ...T[]]
}
const SMALL_INPUT = 'h-8'

/** The errors at `path` (and inside it), under the field. */
export function FieldErrors({
  errors,
  path,
  exact = false,
}: {
  errors: readonly ValidationError[]
  path: string
  /** Only errors at `path` itself (a section whose fields show their own). */
  exact?: boolean
}) {
  const found = (
    exact ? errors.filter((error) => error.path === path) : errorsAt(errors, path)
  ).filter((error) => error.code !== 'anchor.unresolved')
  if (found.length === 0) return null
  return (
    <p role="alert" className="text-xs text-destructive">
      {found.map(errorMessage).join(' ')}
    </p>
  )
}

/** An input bound to a JSON pointer (errors focus it). */
export function PathInput({ path, ...props }: { path: string } & ComponentProps<'input'>) {
  return <Input data-path={path} className={cn(SMALL_INPUT, props.className)} {...props} />
}

export function TemplateSelect({
  path,
  label,
  value,
  choices,
  optional,
  onChange,
}: {
  path: string
  label: string
  value: string
  choices: readonly string[]
  /** The text of the empty choice (none when required). */
  optional?: string
  onChange: (value: string) => void
}) {
  return (
    <select
      data-path={path}
      aria-label={label}
      className={cn(SELECT_CLASS, 'h-8')}
      value={value}
      onChange={(event) => {
        onChange(event.target.value)
      }}
    >
      {optional !== undefined && <option value="">{optional}</option>}
      {!optional && !choices.includes(value) && <option value={value}>{value || '—'}</option>}
      {choices.map((choice) => (
        <option key={choice} value={choice}>
          {choice}
        </option>
      ))}
    </select>
  )
}

export function IconButton({
  label,
  onClick,
  disabled,
  children,
}: {
  label: string
  onClick: () => void
  disabled?: boolean
  children: ReactNode
}) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      className="size-8"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
    >
      {children}
    </Button>
  )
}

// --- levels ------------------------------------------------------------------------------------

/** Renames a level everywhere it is named: templates, alignment fields. */
/** `fields` with the key `from` renamed `to` (or as it was). */
function renameKey<T>(fields: Record<string, T>, from: string, to: string): Record<string, T> {
  if (!(from in fields)) return fields
  return Object.fromEntries(
    Object.entries(fields).map(([key, value]) => [key === from ? to : key, value]),
  )
}

/**
 * Renames a level everywhere it is named: templates, alignment fields, cycles, formats, and the
 * dates and precisions of the time points in the definition.
 */
function renameLevel(definition: Definition, from: string, to: string): Definition {
  const point = (value: DefinitionTimePoint | null | undefined) => {
    if (value == null) return
    if (value.precision === from) value.precision = to
    if (value.anchor.kind === 'local')
      value.anchor.fields = renameKey(value.anchor.fields, from, to)
  }
  return edit(definition, (draft) => {
    for (const level of levelsOf(draft)) if (level.id === from) level.id = to
    for (const regime of draft.regimes) {
      for (const template of Object.values(regime.templates)) {
        if (template?.level === from) template.level = to
      }
      regime.alignment.fields = renameKey(regime.alignment.fields, from, to)
      if (regime.alignment.at.precision === from) regime.alignment.at.precision = to
      point(regime.starts_at)
      for (const cycle of regime.cycles ?? []) {
        if (cycle.level === from) cycle.level = to
        if (typeof cycle.mode === 'object' && cycle.mode.reset === from) cycle.mode = { reset: to }
        if (cycle.anchor?.fields != null) {
          cycle.anchor.fields = renameKey(cycle.anchor.fields, from, to)
        }
      }
    }
    for (const era of draft.eras ?? []) point(era.start)
    for (const overlay of draft.overlays ?? []) point(overlay.epoch)
    if (draft.formats != null) {
      // `{from}`, `{from.name}`, `{from:pad2}` (not after a literal `{{`).
      // The id may be anything while it's being typed.
      const escaped = from.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      const token = new RegExp(`(?<!\\{)\\{${escaped}(?=[}.:])`, 'g')
      const patterns = (formats: Record<string, string | undefined>) =>
        Object.fromEntries(
          Object.entries(renameKey(formats, from, to)).map(([key, value]) => [
            key,
            value?.replace(token, `{${to}`),
          ]),
        )
      const { intercalary, ...own } = draft.formats
      draft.formats = patterns(own as Record<string, string | undefined>)
      if (intercalary != null) draft.formats.intercalary = patterns(intercalary)
    }
  })
}

/**
 * The levels, coarse to fine (the top level first): ids, names, the first regular number and
 * the default template of each, with levels added below, moved and removed.
 */
export function LevelsEditor({ definition, errors, onChange, regimeIndex = 0 }: StructureProps) {
  const levels = levelsOf(definition)
  const regime = regimeOf(definition, regimeIndex)
  const top = levels.length - 1
  const set = (index: number, patch: Partial<Level>) => {
    onChange(
      edit(definition, (draft) => {
        Object.assign(levelsOf(draft)[index] ?? {}, patch)
      }),
    )
  }
  return (
    <section aria-label="Levels" className="flex flex-col gap-2">
      <h3 className="text-sm font-semibold">Levels</h3>
      <p className="text-xs text-muted-foreground">
        The top level is the year; each level is made of units of the level below. The finest level
        is made of base units.
      </p>
      <ol className="flex flex-col gap-2">
        {[...levels].reverse().map((level, shown) => {
          const index = top - shown
          const path = `/levels/${index}`
          const position = shown + 1
          return (
            <li
              key={index}
              aria-label={`Level ${position}`}
              className="grid grid-cols-2 gap-2 rounded-md border p-2 sm:grid-cols-[repeat(4,1fr)_auto]"
            >
              <PathInput
                path={`${path}/id`}
                aria-label={`Level ${position} id`}
                value={level.id}
                onChange={(event) => {
                  onChange(renameLevel(definition, level.id, event.target.value))
                }}
              />
              <PathInput
                path={`${path}/label`}
                aria-label={`Level ${position} label`}
                value={level.label}
                onChange={(event) => {
                  set(index, { label: event.target.value })
                }}
              />
              <PathInput
                path={`${path}/plural`}
                aria-label={`Level ${position} plural`}
                value={level.plural}
                onChange={(event) => {
                  set(index, { plural: event.target.value })
                }}
              />
              <PathInput
                path={`${path}/abbr`}
                aria-label={`Level ${position} abbreviation`}
                value={level.abbr ?? ''}
                onChange={(event) => {
                  set(index, { abbr: event.target.value === '' ? null : event.target.value })
                }}
              />
              <div className="flex items-center">
                <IconButton
                  label={`Move level ${position} up`}
                  disabled={index >= top - 1}
                  onClick={() => {
                    onChange(
                      edit(definition, (draft) => {
                        const all = levelsOf(draft)
                        const [moved] = all.splice(index, 1)
                        if (moved) all.splice(index + 1, 0, moved)
                      }),
                    )
                  }}
                >
                  <ArrowUpIcon />
                </IconButton>
                <IconButton
                  label={`Move level ${position} down`}
                  disabled={index === 0 || index === top}
                  onClick={() => {
                    onChange(
                      edit(definition, (draft) => {
                        const all = levelsOf(draft)
                        const [moved] = all.splice(index, 1)
                        if (moved) all.splice(index - 1, 0, moved)
                      }),
                    )
                  }}
                >
                  <ArrowDownIcon />
                </IconButton>
                <IconButton
                  label={`Remove level ${position}`}
                  disabled={index === top}
                  onClick={() => {
                    onChange(
                      edit(definition, (draft) => {
                        levelsOf(draft).splice(index, 1)
                        for (const each of draft.regimes) {
                          each.templates = Object.fromEntries(
                            Object.entries(each.templates).filter(
                              ([, template]) => template?.level !== level.id,
                            ),
                          )
                          each.alignment.fields = omitKey(each.alignment.fields, level.id)
                        }
                      }),
                    )
                  }}
                >
                  <Trash2Icon />
                </IconButton>
              </div>
              {index !== top && (
                <div className="col-span-full flex flex-wrap items-center gap-2 text-sm">
                  <div className="flex items-center gap-1">
                    First number
                    <PathInput
                      path={`${path}/numbering_start`}
                      aria-label={`Level ${position} first number`}
                      inputMode="numeric"
                      className="w-20"
                      value={String(level.numbering_start ?? 1)}
                      onChange={(event) => {
                        const value = Number.parseInt(event.target.value, 10)
                        set(index, { numbering_start: Number.isNaN(value) ? 0 : value })
                      }}
                    />
                  </div>
                  <div className="flex items-center gap-1">
                    Default template
                    <TemplateSelect
                      path={`${path}/default_template`}
                      label={`Level ${position} default template`}
                      value={level.default_template ?? ''}
                      choices={templatesAt(regime, level.id)}
                      optional="None"
                      onChange={(value) => {
                        set(index, { default_template: value === '' ? null : value })
                      }}
                    />
                  </div>
                </div>
              )}
              <div className="col-span-full">
                <FieldErrors errors={errors} path={path} />
              </div>
              <div className="col-span-full">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    onChange(
                      edit(definition, (draft) => {
                        const id = freshId(
                          levelsOf(draft).map((each) => each.id),
                          'level',
                        )
                        levelsOf(draft).splice(index, 0, {
                          id,
                          label: id,
                          plural: `${id}s`,
                          numbering_start: 1,
                        })
                      }),
                    )
                  }}
                >
                  <PlusIcon aria-hidden /> Add a level below {level.id}
                </Button>
              </div>
            </li>
          )
        })}
      </ol>
      <FieldErrors errors={errors} path="/levels" exact />
    </section>
  )
}

// --- templates ---------------------------------------------------------------------------------

/** Renames a template everywhere it is used (children, defaults, the year pattern). */
function renameTemplate(
  definition: Definition,
  regimeIndex: number,
  from: string,
  to: string,
): Definition {
  return edit(definition, (draft) => {
    const regime = regimeOf(draft, regimeIndex)
    const swap = (id: string) => (id === from ? to : id)
    regime.templates = Object.fromEntries(
      Object.entries(regime.templates).map(([id, template]) => [swap(id), template]),
    )
    for (const template of Object.values(regime.templates)) {
      if (template === undefined) continue
      if ('uniform' in template && template.uniform.template) {
        template.uniform.template = swap(template.uniform.template)
      }
      if ('sequence' in template) {
        for (const child of template.sequence) {
          if ('run' in child && child.run.template) child.run.template = swap(child.run.template)
          if ('template' in child) child.template = swap(child.template)
        }
      }
    }
    for (const level of levelsOf(draft)) {
      if (level.default_template) level.default_template = swap(level.default_template)
    }
    const pattern = regime.top.pattern
    if (pattern.kind === 'fixed') pattern.template = swap(pattern.template)
    if (pattern.kind === 'cycle') pattern.templates = nonEmpty(pattern.templates.map(swap))
    if (pattern.kind === 'rules') {
      pattern.default = swap(pattern.default)
      for (const rule of pattern.rules) rule.template = swap(rule.template)
    }
    for (const exception of regime.top.exceptions ?? [])
      exception.template = swap(exception.template)
  })
}

function ChildRow({
  path,
  child,
  index,
  count,
  choices,
  shared,
  cycles,
  onChange,
  onMove,
  onRemove,
}: {
  path: string
  child: SequenceChild
  index: number
  count: number
  choices: readonly string[]
  shared: ReadonlySet<string>
  /** The regime's cycles: a named unit may be skipped by them. */
  cycles: readonly string[]
  onChange: (child: SequenceChild) => void
  onMove: (to: number) => void
  onRemove: () => void
}) {
  const row = index + 1
  return (
    <li aria-label={`Unit ${row}`} className="flex flex-wrap items-center gap-1">
      {'run' in child ? (
        <>
          <Badge variant="outline">Numbered</Badge>
          <PathInput
            path={`${path}/run/count`}
            aria-label={`Unit ${row} count`}
            inputMode="numeric"
            className="w-24"
            value={child.run.count}
            onChange={(event) => {
              onChange({ run: { ...child.run, count: event.target.value } })
            }}
          />
          <TemplateSelect
            path={`${path}/run/template`}
            label={`Unit ${row} template`}
            value={child.run.template ?? ''}
            choices={choices}
            optional="Level default"
            onChange={(value) => {
              const rest = omit(child.run, 'template')
              onChange({ run: value === '' ? rest : { ...rest, template: value } })
            }}
          />
        </>
      ) : (
        <>
          <Badge
            variant={shared.has(child.id) ? 'default' : 'outline'}
            title={
              shared.has(child.id)
                ? 'Also in another template: dates keep it across templates'
                : undefined
            }
          >
            Named
          </Badge>
          <PathInput
            path={`${path}/id`}
            aria-label={`Unit ${row} id`}
            className="w-28"
            value={child.id}
            onChange={(event) => {
              onChange({ ...child, id: event.target.value })
            }}
          />
          <PathInput
            path={`${path}/name`}
            aria-label={`Unit ${row} name`}
            className="w-32"
            value={child.name}
            onChange={(event) => {
              onChange({ ...child, name: event.target.value })
            }}
          />
          <PathInput
            path={`${path}/abbr`}
            aria-label={`Unit ${row} abbreviation`}
            className="w-20"
            value={child.abbr ?? ''}
            onChange={(event) => {
              const rest = omit(child, 'abbr')
              onChange(event.target.value === '' ? rest : { ...rest, abbr: event.target.value })
            }}
          />
          <TemplateSelect
            path={`${path}/template`}
            label={`Unit ${row} template`}
            value={child.template}
            choices={choices}
            onChange={(value) => {
              onChange({ ...child, template: value })
            }}
          />
          <label className="flex items-center gap-1 text-xs">
            <input
              type="checkbox"
              checked={child.intercalary === true}
              onChange={(event) => {
                const rest = omit(child, 'intercalary')
                onChange(event.target.checked ? { ...rest, intercalary: true } : rest)
              }}
            />
            Intercalary
          </label>
          {cycles.map((cycle) => {
            const excluded = child.cycle_excluded ?? []
            return (
              <label key={cycle} className="flex items-center gap-1 text-xs">
                <input
                  type="checkbox"
                  checked={excluded.includes(cycle)}
                  onChange={(event) => {
                    const next = event.target.checked
                      ? [...excluded, cycle]
                      : excluded.filter((other) => other !== cycle)
                    const rest = omit(child, 'cycle_excluded')
                    onChange(next.length === 0 ? rest : { ...rest, cycle_excluded: next })
                  }}
                />
                Skips {cycle}
              </label>
            )
          })}
        </>
      )}
      <IconButton
        label={`Move unit ${row} up`}
        disabled={index === 0}
        onClick={() => {
          onMove(index - 1)
        }}
      >
        <ArrowUpIcon />
      </IconButton>
      <IconButton
        label={`Move unit ${row} down`}
        disabled={index === count - 1}
        onClick={() => {
          onMove(index + 1)
        }}
      >
        <ArrowDownIcon />
      </IconButton>
      <IconButton label={`Remove unit ${row}`} onClick={onRemove}>
        <Trash2Icon />
      </IconButton>
    </li>
  )
}

function TemplateCard({
  definition,
  errors,
  onChange,
  regimeIndex = 0,
  id,
  template,
  shared,
}: StructureProps & { id: string; template: Template; shared: ReadonlySet<string> }) {
  const path = `${regimePath(regimeIndex)}/templates/${part(id)}`
  const child = childLevel(definition, template.level)
  const choices = child === null ? [] : templatesAt(regimeOf(definition, regimeIndex), child)
  const set = (next: Template) => {
    onChange(
      edit(definition, (draft) => {
        regimeOf(draft, regimeIndex).templates[id] = next
      }),
    )
  }
  const sequence = 'sequence' in template ? template.sequence : null
  return (
    <li aria-label={`Template ${id}`} className="flex flex-col gap-2 rounded-md border p-2">
      <div className="flex flex-wrap items-center gap-2">
        <PathInput
          path={path}
          aria-label="Template id"
          className="w-40"
          value={id}
          onChange={(event) => {
            onChange(renameTemplate(definition, regimeIndex, id, event.target.value))
          }}
        />
        <Badge variant="secondary">{template.level}</Badge>
        {child !== null && (
          <select
            aria-label="Layout"
            className={cn(SELECT_CLASS, 'h-8')}
            value={sequence === null ? 'uniform' : 'sequence'}
            onChange={(event) => {
              set(
                event.target.value === 'sequence'
                  ? { level: template.level, sequence: [newChild('run', '')] }
                  : { level: template.level, uniform: { count: '1' } },
              )
            }}
          >
            <option value="uniform">Uniform: n equal units</option>
            <option value="sequence">Sequence: listed units</option>
          </select>
        )}
        <div className="flex-1" />
        <IconButton
          label={`Remove template ${id}`}
          onClick={() => {
            onChange(
              edit(definition, (draft) => {
                const target = regimeOf(draft, regimeIndex)
                target.templates = omitKey(target.templates, id)
              }),
            )
          }}
        >
          <Trash2Icon />
        </IconButton>
      </div>
      {'uniform' in template && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <div className="flex items-center gap-1">
            {child === null ? 'Base units' : `Count of ${child}`}
            <PathInput
              path={`${path}/uniform/count`}
              aria-label="Count"
              inputMode="numeric"
              className="w-28"
              value={template.uniform.count}
              onChange={(event) => {
                set({ ...template, uniform: { ...template.uniform, count: event.target.value } })
              }}
            />
          </div>
          {child !== null && (
            <div className="flex items-center gap-1">
              of template
              <TemplateSelect
                path={`${path}/uniform/template`}
                label="Child template"
                value={template.uniform.template ?? ''}
                choices={choices}
                optional="Level default"
                onChange={(value) => {
                  const rest = omit(template.uniform, 'template')
                  set({ ...template, uniform: value === '' ? rest : { ...rest, template: value } })
                }}
              />
            </div>
          )}
        </div>
      )}
      {sequence !== null && (
        <>
          <ol className="flex flex-col gap-1">
            {sequence.map((each, index) => (
              <ChildRow
                key={index}
                path={`${path}/sequence/${index}`}
                child={each}
                index={index}
                count={sequence.length}
                choices={choices}
                shared={shared}
                cycles={(regimeOf(definition, regimeIndex).cycles ?? []).map((cycle) => cycle.id)}
                onChange={(next) => {
                  set({
                    ...template,
                    sequence: sequence.map((old, at) =>
                      at === index ? next : old,
                    ) as typeof sequence,
                  })
                }}
                onMove={(to) => {
                  const list = [...sequence]
                  const [moved] = list.splice(index, 1)
                  if (moved) list.splice(to, 0, moved)
                  set({ ...template, sequence: list as typeof sequence })
                }}
                onRemove={() => {
                  const list = sequence.filter((_, at) => at !== index)
                  if (list.length > 0) set({ ...template, sequence: list as typeof sequence })
                }}
              />
            ))}
          </ol>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                set({ ...template, sequence: [...sequence, newChild('slot', choices[0] ?? '')] })
              }}
            >
              <PlusIcon aria-hidden /> Named unit
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                set({ ...template, sequence: [...sequence, newChild('run', '')] })
              }}
            >
              <PlusIcon aria-hidden /> Numbered units
            </Button>
          </div>
        </>
      )}
      <FieldErrors errors={errors} path={path} />
    </li>
  )
}

/**
 * The templates of the first regime, by level (coarse to fine): uniform (n units of a child
 * template) or a sequence of named units (slot ids, names, intercalary) and numbered runs. Slot
 * ids shared across templates are highlighted: they keep typed dates when years differ.
 */
export function TemplatesEditor(props: StructureProps) {
  const { definition, errors, onChange, regimeIndex = 0 } = props
  const regime = regimeOf(definition, regimeIndex)
  const shared = sharedSlotIds(regime)
  const levels = [...levelsOf(definition)].reverse()
  return (
    <section aria-label="Templates" className="flex flex-col gap-3">
      <h3 className="text-sm font-semibold">Templates</h3>
      {levels.map((level) => {
        const ids = templatesAt(regime, level.id)
        return (
          <div key={level.id} className="flex flex-col gap-2">
            <h4 className="text-xs font-medium text-muted-foreground uppercase">{level.plural}</h4>
            <ul className="flex flex-col gap-2">
              {ids.map((id, index) => {
                const template = regime.templates[id]
                // Keyed by position: renaming a template mustn't remount its card.
                return template === undefined ? null : (
                  <TemplateCard
                    key={index}
                    {...props}
                    id={id}
                    template={template}
                    shared={shared}
                  />
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
                    target.templates[freshId(Object.keys(target.templates), level.id)] =
                      newTemplate(level.id)
                  }),
                )
              }}
            >
              <PlusIcon aria-hidden /> Add a {level.label} template
            </Button>
          </div>
        )
      })}
      <FieldErrors errors={errors} path={`${regimePath(regimeIndex)}/templates`} exact />
    </section>
  )
}

// --- top pattern -------------------------------------------------------------------------------

function PredicateEditor({
  path,
  predicate,
  label,
  onChange,
}: {
  path: string
  predicate: Predicate
  label: string
  onChange: (predicate: Predicate) => void
}) {
  const kind =
    'mod' in predicate ? 'mod' : 'all' in predicate ? 'all' : 'any' in predicate ? 'any' : 'not'
  return (
    <div className="flex flex-col gap-1 border-l-2 pl-2">
      <div className="flex flex-wrap items-center gap-1 text-sm">
        <select
          aria-label={`${label} kind`}
          className={cn(SELECT_CLASS, 'h-8')}
          value={kind}
          onChange={(event) => {
            const next = event.target.value
            onChange(
              next === 'mod'
                ? NEW_PREDICATE
                : next === 'not'
                  ? { not: NEW_PREDICATE }
                  : next === 'all'
                    ? { all: [NEW_PREDICATE] }
                    : { any: [NEW_PREDICATE] },
            )
          }}
        >
          <option value="mod">Year divisible…</option>
          <option value="all">All of</option>
          <option value="any">Any of</option>
          <option value="not">Not</option>
        </select>
        {'mod' in predicate && (
          <>
            <span>year mod</span>
            <PathInput
              path={`${path}/mod`}
              aria-label={`${label} divisor`}
              inputMode="numeric"
              className="w-20"
              value={predicate.mod}
              onChange={(event) => {
                onChange({ ...predicate, mod: event.target.value })
              }}
            />
            <span>=</span>
            <PathInput
              path={`${path}/eq`}
              aria-label={`${label} remainder`}
              inputMode="numeric"
              className="w-20"
              value={predicate.eq}
              onChange={(event) => {
                onChange({ ...predicate, eq: event.target.value })
              }}
            />
          </>
        )}
      </div>
      {'not' in predicate && (
        <PredicateEditor
          path={`${path}/not`}
          predicate={predicate.not}
          label={`${label} › not`}
          onChange={(not) => {
            onChange({ not })
          }}
        />
      )}
      {('all' in predicate || 'any' in predicate) &&
        (() => {
          const key = 'all' in predicate ? 'all' : 'any'
          const list: Predicate[] = 'all' in predicate ? predicate.all : predicate.any
          const wrap = (items: Predicate[]): Predicate =>
            (key === 'all' ? { all: items } : { any: items }) as Predicate
          return (
            <>
              {list.map((item, index) => (
                <div key={index} className="flex items-start gap-1">
                  <div className="flex-1">
                    <PredicateEditor
                      path={`${path}/${key}/${index}`}
                      predicate={item}
                      label={`${label} › ${index + 1}`}
                      onChange={(next) => {
                        onChange(wrap(list.map((old, at) => (at === index ? next : old))))
                      }}
                    />
                  </div>
                  <IconButton
                    label={`Remove ${label} › ${index + 1}`}
                    disabled={list.length === 1}
                    onClick={() => {
                      onChange(wrap(list.filter((_, at) => at !== index)))
                    }}
                  >
                    <Trash2Icon />
                  </IconButton>
                </div>
              ))}
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="self-start"
                onClick={() => {
                  onChange(wrap([...list, NEW_PREDICATE]))
                }}
              >
                <PlusIcon aria-hidden /> Condition
              </Button>
            </>
          )
        })()}
    </div>
  )
}

/**
 * Which template each year uses (chronology-engine.md §3.5): one for every year, a cycle of
 * templates from a starting year, or rules (divisibility conditions combined with all/any/not,
 * the first that matches wins), plus exceptions for single years.
 */
export function TopEditor({ definition, errors, onChange, regimeIndex = 0 }: StructureProps) {
  const regime = regimeOf(definition, regimeIndex)
  const levels = levelsOf(definition)
  const topLevel = levels[levels.length - 1]?.id ?? ''
  const choices = templatesAt(regime, topLevel)
  const pattern = regime.top.pattern
  const path = `${regimePath(regimeIndex)}/top/pattern`
  const setPattern = (next: YearPattern) => {
    onChange(
      edit(definition, (draft) => {
        regimeOf(draft, regimeIndex).top.pattern = next
      }),
    )
  }
  const exceptions = regime.top.exceptions ?? []
  const setExceptions = (next: typeof exceptions) => {
    onChange(
      edit(definition, (draft) => {
        const top = regimeOf(draft, regimeIndex).top
        if (next.length === 0) delete top.exceptions
        else top.exceptions = next
      }),
    )
  }
  return (
    <section aria-label="Years" className="flex flex-col gap-2">
      <h3 className="text-sm font-semibold">Years</h3>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-muted-foreground">Rules</span>
        <PathInput
          path={`${regimePath(regimeIndex)}/id`}
          aria-label="Rules id"
          className="w-36"
          value={regime.id}
          onChange={(event) => {
            onChange(
              edit(definition, (draft) => {
                regimeOf(draft, regimeIndex).id = event.target.value
              }),
            )
          }}
        />
        <PathInput
          path={`${regimePath(regimeIndex)}/name`}
          aria-label="Rules name"
          className="w-56"
          value={regime.name}
          onChange={(event) => {
            onChange(
              edit(definition, (draft) => {
                regimeOf(draft, regimeIndex).name = event.target.value
              }),
            )
          }}
        />
      </div>
      <select
        aria-label="Year pattern"
        className={cn(SELECT_CLASS, 'h-8 self-start')}
        value={pattern.kind}
        onChange={(event) => {
          setPattern(newPattern(event.target.value as YearPattern['kind'], choices[0] ?? ''))
        }}
      >
        <option value="fixed">Every year alike</option>
        <option value="cycle">A cycle of templates</option>
        <option value="rules">Rules</option>
      </select>
      {pattern.kind === 'fixed' && (
        <TemplateSelect
          path={`${path}/template`}
          label="Year template"
          value={pattern.template}
          choices={choices}
          onChange={(template) => {
            setPattern({ ...pattern, template })
          }}
        />
      )}
      {pattern.kind === 'cycle' && (
        <div className="flex flex-col gap-1 text-sm">
          <ol className="flex flex-col gap-1">
            {pattern.templates.map((template, index) => (
              <li key={index} className="flex items-center gap-1">
                <span className="w-16 text-muted-foreground">Year {index + 1}</span>
                <TemplateSelect
                  path={`${path}/templates/${index}`}
                  label={`Cycle year ${index + 1}`}
                  value={template}
                  choices={choices}
                  onChange={(value) => {
                    setPattern({
                      ...pattern,
                      templates: nonEmpty(
                        pattern.templates.map((old, at) => (at === index ? value : old)),
                      ),
                    })
                  }}
                />
                <IconButton
                  label={`Remove cycle year ${index + 1}`}
                  disabled={pattern.templates.length === 1}
                  onClick={() => {
                    setPattern({
                      ...pattern,
                      templates: nonEmpty(pattern.templates.filter((_, at) => at !== index)),
                    })
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
              setPattern({ ...pattern, templates: [...pattern.templates, choices[0] ?? ''] })
            }}
          >
            <PlusIcon aria-hidden /> Year in the cycle
          </Button>
          <div className="flex items-center gap-1">
            The cycle starts in year
            <PathInput
              path={`${path}/start`}
              aria-label="Cycle start"
              inputMode="numeric"
              className="w-24"
              value={pattern.start}
              onChange={(event) => {
                setPattern({ ...pattern, start: event.target.value })
              }}
            />
          </div>
        </div>
      )}
      {pattern.kind === 'rules' && (
        <div className="flex flex-col gap-2 text-sm">
          {pattern.rules.map((rule, index) => (
            <div
              key={index}
              aria-label={`Rule ${index + 1}`}
              role="group"
              className="flex flex-col gap-1 rounded-md border p-2"
            >
              <PredicateEditor
                path={`${path}/rules/${index}/when`}
                predicate={rule.when}
                label={`Rule ${index + 1}`}
                onChange={(when) => {
                  setPattern({
                    ...pattern,
                    rules: pattern.rules.map((old, at) => (at === index ? { ...old, when } : old)),
                  })
                }}
              />
              <div className="flex items-center gap-1">
                <span>then</span>
                <TemplateSelect
                  path={`${path}/rules/${index}/template`}
                  label={`Rule ${index + 1} template`}
                  value={rule.template}
                  choices={choices}
                  onChange={(template) => {
                    setPattern({
                      ...pattern,
                      rules: pattern.rules.map((old, at) =>
                        at === index ? { ...old, template } : old,
                      ),
                    })
                  }}
                />
                <IconButton
                  label={`Remove rule ${index + 1}`}
                  onClick={() => {
                    setPattern({ ...pattern, rules: pattern.rules.filter((_, at) => at !== index) })
                  }}
                >
                  <Trash2Icon />
                </IconButton>
              </div>
            </div>
          ))}
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="self-start"
            onClick={() => {
              setPattern({
                ...pattern,
                rules: [...pattern.rules, { when: NEW_PREDICATE, template: choices[0] ?? '' }],
              })
            }}
          >
            <PlusIcon aria-hidden /> Rule
          </Button>
          <div className="flex items-center gap-1">
            Otherwise
            <TemplateSelect
              path={`${path}/default`}
              label="Default year template"
              value={pattern.default}
              choices={choices}
              onChange={(value) => {
                setPattern({ ...pattern, default: value })
              }}
            />
          </div>
        </div>
      )}
      <FieldErrors errors={errors} path={path} />
      <h4 className="text-xs font-medium text-muted-foreground uppercase">Exceptions</h4>
      <table className="text-sm">
        <tbody>
          {exceptions.map((exception, index) => (
            <tr key={index}>
              <td className="pr-2">
                <PathInput
                  path={`${regimePath(regimeIndex)}/top/exceptions/${index}/year`}
                  aria-label={`Exception ${index + 1} year`}
                  inputMode="numeric"
                  className="w-28"
                  value={exception.year}
                  onChange={(event) => {
                    setExceptions(
                      exceptions.map((old, at) =>
                        at === index ? { ...old, year: event.target.value } : old,
                      ),
                    )
                  }}
                />
              </td>
              <td className="pr-2">
                <TemplateSelect
                  path={`${regimePath(regimeIndex)}/top/exceptions/${index}/template`}
                  label={`Exception ${index + 1} template`}
                  value={exception.template}
                  choices={choices}
                  onChange={(template) => {
                    setExceptions(
                      exceptions.map((old, at) => (at === index ? { ...old, template } : old)),
                    )
                  }}
                />
              </td>
              <td>
                <IconButton
                  label={`Remove exception ${index + 1}`}
                  onClick={() => {
                    setExceptions(exceptions.filter((_, at) => at !== index))
                  }}
                >
                  <Trash2Icon />
                </IconButton>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="self-start"
        onClick={() => {
          setExceptions([...exceptions, { year: '1', template: choices[0] ?? '' }])
        }}
      >
        <PlusIcon aria-hidden /> Exception
      </Button>
      <FieldErrors errors={errors} path={`${regimePath(regimeIndex)}/top/exceptions`} />
    </section>
  )
}

// --- alignment ---------------------------------------------------------------------------------

/**
 * Where the calendar sits in time (chronology-engine.md §3.6): a date of this calendar (from the
 * year down, slot ids or numbers) and the moment it begins (`at`, edited by `atEditor`).
 */
export function AlignmentEditor({
  definition,
  errors,
  onChange,
  regimeIndex = 0,
  atEditor,
}: StructureProps & { atEditor: ReactNode }) {
  const regime: Regime = regimeOf(definition, regimeIndex)
  const levels = [...levelsOf(definition)].reverse()
  const fields = regime.alignment.fields
  const path = `${regimePath(regimeIndex)}/alignment`
  return (
    <section aria-label="Alignment" className="flex flex-col gap-2">
      <h3 className="text-sm font-semibold">Alignment</h3>
      <p className="text-xs text-muted-foreground">
        A date of this calendar and the moment it begins: the year counts astronomically (no era).
      </p>
      <div className="flex flex-wrap gap-2">
        {levels.map((level) => (
          <label key={level.id} className="flex flex-col gap-1 text-xs">
            {level.label}
            <PathInput
              path={`${path}/fields/${part(level.id)}`}
              aria-label={`Alignment ${level.label}`}
              className="w-28"
              value={fields[level.id] ?? ''}
              onChange={(event) => {
                onChange(
                  edit(definition, (draft) => {
                    const target = regimeOf(draft, regimeIndex).alignment
                    const rest = omitKey(target.fields, level.id)
                    target.fields =
                      event.target.value === '' ? rest : { ...rest, [level.id]: event.target.value }
                  }),
                )
              }}
            />
          </label>
        ))}
      </div>
      <FieldErrors errors={errors} path={`${path}/fields`} />
      {atEditor}
      <FieldErrors errors={errors} path={`${path}/at`} />
    </section>
  )
}
