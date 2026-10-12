import { FilterIcon, XIcon } from 'lucide-react'
import { useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { IMPORTANCE } from '@/core/events'
import { useKindRegistry } from '@/core/registry'
import { useQuickSearch, useTags, type WindowFilters } from '@/data'

/** An entity picked in a filter, with its name for the chips. */
export interface Named {
  id: string
  name: string
}

/** The timeline's filters (frontend.md §9.3): what the window asks for. */
export interface TimelineFilters {
  minImportance: number | null
  categories: string[]
  tags: Named[]
  participants: Named[]
  participantKinds: string[]
}

export const NO_FILTERS: TimelineFilters = {
  minImportance: null,
  categories: [],
  tags: [],
  participants: [],
  participantKinds: [],
}

/** How lanes are grouped (frontend.md §9.3). */
export type GroupMode = 'auto' | 'category' | 'importance' | 'participant'

export const GROUP_MODES: { value: GroupMode; label: string }[] = [
  { value: 'auto', label: 'No grouping' },
  { value: 'category', label: 'By category' },
  { value: 'importance', label: 'By importance' },
  { value: 'participant', label: 'By participant' },
]

/** The window query of the filters. */
export function windowFilters(filters: TimelineFilters): WindowFilters {
  return {
    ...(filters.minImportance === null ? {} : { min_importance: filters.minImportance }),
    ...(filters.categories.length === 0 ? {} : { category: filters.categories }),
    ...(filters.tags.length === 0 ? {} : { tag: filters.tags.map((tag) => tag.id) }),
    ...(filters.participants.length === 0
      ? {}
      : { participant: filters.participants.map((entity) => entity.id) }),
    ...(filters.participantKinds.length === 0
      ? {}
      : { participant_kind: filters.participantKinds }),
  }
}

export function filterCount(filters: TimelineFilters): number {
  return (
    (filters.minImportance === null ? 0 : 1) +
    filters.categories.length +
    filters.tags.length +
    filters.participants.length +
    filters.participantKinds.length
  )
}

function toggled<T>(list: readonly T[], value: T, same: (a: T, b: T) => boolean): T[] {
  return list.some((each) => same(each, value))
    ? list.filter((each) => !same(each, value))
    : [...list, value]
}

function Checkbox({
  label,
  checked,
  onChange,
}: {
  label: string
  checked: boolean
  onChange: () => void
}) {
  return (
    <label className="flex items-center gap-1.5 text-sm">
      <input type="checkbox" checked={checked} onChange={onChange} />
      {label}
    </label>
  )
}

function ParticipantSearch({
  vault,
  dimensionId,
  picked,
  onPick,
}: {
  vault: string
  dimensionId: string
  picked: readonly Named[]
  onPick: (entity: Named) => void
}) {
  const [query, setQuery] = useState('')
  const q = query.trim()
  const results = useQuickSearch(vault, { q, dimension: dimensionId })
  const hits =
    q === ''
      ? []
      : (results.data?.items ?? []).filter(
          (hit) => hit.kind !== 'event' && !picked.some((each) => each.id === hit.entity_id),
        )
  return (
    <div className="flex flex-col gap-1">
      <Input
        aria-label="Find a participant"
        placeholder="Find a participant…"
        className="h-8"
        value={query}
        onChange={(event) => {
          setQuery(event.target.value)
        }}
      />
      {hits.length > 0 && (
        <ul aria-label="Participants found" className="flex flex-col rounded-md border text-sm">
          {hits.slice(0, 6).map((hit) => (
            <li key={hit.entity_id}>
              <button
                type="button"
                className="w-full px-2 py-1 text-left hover:bg-accent"
                onClick={() => {
                  onPick({ id: hit.entity_id, name: hit.name })
                  setQuery('')
                }}
              >
                {hit.name}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/**
 * The timeline's filters (frontend.md §9.3) in a popover: minimum importance, categories (those
 * shown or picked), tags in use, participants (search) and kinds of participants. They go to the
 * window query, so culled counts and density follow them.
 */
export function FiltersPanel({
  vault,
  dimensionId,
  categories,
  value,
  onChange,
}: {
  vault: string
  dimensionId: string
  /** Categories to offer: those of the events shown, plus the picked ones. */
  categories: readonly string[]
  value: TimelineFilters
  onChange: (filters: TimelineFilters) => void
}) {
  const registry = useKindRegistry(vault)
  const tags = useTags(vault)
  const count = filterCount(value)
  const participantType = registry?.linkType('core.participant')
  const targetKinds = participantType?.target_kinds
  const kinds = (registry?.kinds ?? []).filter(
    (kind) =>
      !kind.capabilities.is_system &&
      kind.key !== 'event' &&
      (targetKinds === undefined || targetKinds === '*' || targetKinds.includes(kind.key)),
  )
  const offered = [...new Set([...categories, ...value.categories])].sort()
  const set = (patch: Partial<TimelineFilters>) => {
    onChange({ ...value, ...patch })
  }
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" aria-label={`Filters (${count})`}>
          <FilterIcon aria-hidden /> Filters
          {count > 0 && (
            <Badge variant="secondary" className="h-4 px-1 text-[10px]">
              {count}
            </Badge>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="flex w-80 flex-col gap-3">
        <label className="flex items-center justify-between gap-2 text-sm">
          Importance at least
          <select
            aria-label="Minimum importance"
            className="h-8 rounded-md border border-input bg-transparent px-1 text-sm"
            value={value.minImportance ?? ''}
            onChange={(event) => {
              set({
                minImportance: event.target.value === '' ? null : Number(event.target.value),
              })
            }}
          >
            <option value="">Any</option>
            {[2, 3, 4, 5].map((level) => (
              <option key={level} value={level}>
                {level} · {IMPORTANCE[level] ?? ''}
              </option>
            ))}
          </select>
        </label>
        {offered.length > 0 && (
          <fieldset className="flex flex-col gap-1">
            <legend className="text-xs font-medium text-muted-foreground uppercase">
              Categories
            </legend>
            {offered.map((category) => (
              <Checkbox
                key={category}
                label={category}
                checked={value.categories.includes(category)}
                onChange={() => {
                  set({ categories: toggled(value.categories, category, (a, b) => a === b) })
                }}
              />
            ))}
          </fieldset>
        )}
        {(tags.data?.items.length ?? 0) > 0 && (
          <fieldset className="flex max-h-40 flex-col gap-1 overflow-y-auto">
            <legend className="text-xs font-medium text-muted-foreground uppercase">
              Tags (all of them)
            </legend>
            {(tags.data?.items ?? []).map((tag) => (
              <Checkbox
                key={tag.id}
                label={`${tag.name} (${tag.count})`}
                checked={value.tags.some((each) => each.id === tag.id)}
                onChange={() => {
                  set({
                    tags: toggled(
                      value.tags,
                      { id: tag.id, name: tag.name },
                      (a, b) => a.id === b.id,
                    ),
                  })
                }}
              />
            ))}
          </fieldset>
        )}
        <fieldset className="flex flex-col gap-1">
          <legend className="text-xs font-medium text-muted-foreground uppercase">
            Participants (any of them)
          </legend>
          {value.participants.length > 0 && (
            <ul className="flex flex-wrap gap-1">
              {value.participants.map((entity) => (
                <li key={entity.id}>
                  <Badge variant="outline" className="gap-1">
                    {entity.name}
                    <button
                      type="button"
                      aria-label={`Remove ${entity.name}`}
                      onClick={() => {
                        set({ participants: value.participants.filter((p) => p.id !== entity.id) })
                      }}
                    >
                      <XIcon aria-hidden className="size-3" />
                    </button>
                  </Badge>
                </li>
              ))}
            </ul>
          )}
          <ParticipantSearch
            vault={vault}
            dimensionId={dimensionId}
            picked={value.participants}
            onPick={(entity) => {
              set({ participants: [...value.participants, entity] })
            }}
          />
        </fieldset>
        {kinds.length > 0 && (
          <fieldset className="flex flex-col gap-1">
            <legend className="text-xs font-medium text-muted-foreground uppercase">
              With a participant who is
            </legend>
            {kinds.map((kind) => (
              <Checkbox
                key={kind.key}
                label={kind.label}
                checked={value.participantKinds.includes(kind.key)}
                onChange={() => {
                  set({
                    participantKinds: toggled(value.participantKinds, kind.key, (a, b) => a === b),
                  })
                }}
              />
            ))}
          </fieldset>
        )}
        {count > 0 && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              onChange(NO_FILTERS)
            }}
          >
            Clear the filters
          </Button>
        )}
      </PopoverContent>
    </Popover>
  )
}
