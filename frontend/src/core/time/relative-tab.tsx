import type { Duration, EndSpec, SlotRef, TimePoint } from '@lore/chronology'
import { useEffect, useId, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useKindRegistry } from '@/core/registry'
import { useEntity, useMutations, useQuickSearch, useTimeResolution, type components } from '@/data'

import type { DimensionTime, Lens } from './calendars'
import { DurationPicker } from './duration-picker'
import { SELECT_CLASS } from './select'
import { timeProblemMessage } from './time-problems'

/**
 * A level id, `base`, or `default`: the precision the anchor takes from its target and offset
 * (time-model.md §5.3).
 */
export type PrecisionChoice = string

export interface RelativeDraft {
  type: string | null
  /** `name` is `null` for a target restored from a stored anchor, until it loads. */
  target: { id: string; name: string | null } | null
  slot: string | null
  occurrence: string
  offset: Duration | null
  precision: PrecisionChoice
}

const ZERO: Duration = { kind: 'base', units: '0' }
const OCCURRENCE_KEY = /^(0|[1-9][0-9]*)(\.(0|[1-9][0-9]*))?$/

const SLOT_LABELS: Record<string, string> = {
  start: 'Start',
  end: 'End',
  branch_point: 'Branch point',
}

export function relativeDraftOf(value: TimePoint | null): RelativeDraft {
  const empty: RelativeDraft = {
    type: null,
    target: null,
    slot: null,
    occurrence: '',
    offset: null,
    precision: 'default',
  }
  if (value?.anchor.kind !== 'relative') return empty
  const { ref, offset } = value.anchor
  return {
    type: ref.type,
    target: { id: ref.id, name: null },
    slot: ref.slot,
    occurrence: ref.occurrence ?? '',
    offset,
    precision: value.precision,
  }
}

/** The anchor's ref, once a target and slot are picked and the occurrence key is well formed. */
function refOf(draft: RelativeDraft): SlotRef | null {
  if (draft.type === null || draft.target === null || draft.slot === null) return null
  const occurrence = draft.occurrence.trim()
  if (occurrence !== '' && !OCCURRENCE_KEY.test(occurrence)) return null
  return {
    type: draft.type,
    id: draft.target.id,
    slot: draft.slot,
    ...(occurrence === '' ? {} : { occurrence }),
  }
}

type WireTimePoint = components['schemas']['ResolveRequestItem']['time_point']
type WireEnd = NonNullable<components['schemas']['ResolveRequestItem']['end']>

/** A time point for the API: the engine's types allow `undefined` field values, never sent. */
export function wire(point: TimePoint): WireTimePoint {
  return point as WireTimePoint
}

/** An end spec for the API (see `wire`). */
export function wireEnd(spec: EndSpec): WireEnd {
  return spec as WireEnd
}

function slotLabel(slot: string): string {
  return SLOT_LABELS[slot] ?? slot.replaceAll('_', ' ')
}

/** Finds the target among the record types that are entity kinds (events, timelines, …). */
function TargetSearch({
  vault,
  dimension,
  type,
  onPick,
}: {
  vault: string
  dimension: DimensionTime
  type: string
  onPick: (target: { id: string; name: string }) => void
}) {
  const [q, setQ] = useState('')
  const id = useId()
  const hits = useQuickSearch(vault, { q: q.trim(), kind: [type], dimension: dimension.id })
  const items = q.trim() === '' ? [] : (hits.data?.items ?? [])
  return (
    <div className="flex flex-col gap-1">
      <Input
        id={id}
        aria-label="Find the target"
        placeholder="Type a name…"
        value={q}
        onChange={(event) => {
          setQ(event.target.value)
        }}
      />
      {items.length > 0 && (
        <ul aria-label="Targets" className="flex flex-col rounded-md border">
          {items.map((hit) => (
            <li key={hit.entity_id}>
              <button
                type="button"
                className="w-full px-2 py-1 text-left text-sm hover:bg-accent focus-visible:bg-accent focus-visible:outline-none"
                onClick={() => {
                  onPick({ id: hit.entity_id, name: hit.name })
                }}
              >
                {hit.name}
                {hit.alias && (
                  <span className="ml-2 text-xs text-muted-foreground">alias {hit.alias}</span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
      {q.trim() !== '' && hits.isSuccess && items.length === 0 && (
        <p className="text-xs text-muted-foreground">Nothing found in this dimension.</p>
      )}
    </div>
  )
}

/**
 * The picker's **Relative** tab (time-model.md §5.2, D3): a target found by name among the record
 * types whose slots may be referenced (`referenceable_slots` in the registry), its slot, an
 * occurrence key for recurring events, and an offset. The server resolves it live
 * (`/time/resolve`): the preview shows the moment and the resulting precision, problems (an
 * unset or hidden target, a cycle, out of bounds) show inline, and only a resolvable anchor is
 * reported.
 */
export function RelativeTab({
  vault,
  dimension,
  lenses,
  draft,
  approximate,
  owner,
  onDraft,
  onPoint,
}: {
  vault: string
  dimension: DimensionTime
  lenses: readonly Lens[]
  draft: RelativeDraft
  approximate: boolean
  /** The slot being edited: referencing it would be a cycle. */
  owner?: SlotRef | undefined
  onDraft: (draft: RelativeDraft) => void
  onPoint: (point: TimePoint | null) => void
}) {
  const registry = useKindRegistry(vault)
  const author = useMutations() !== null
  const id = useId()
  const types = (registry?.referenceableSlots ?? []).filter(
    (entry) => registry?.kind(entry.record_type) !== undefined,
  )
  const type = draft.type ?? types[0]?.record_type ?? null
  const slots = types.find((entry) => entry.record_type === type)?.slots ?? []
  const slot = draft.slot !== null && slots.includes(draft.slot) ? draft.slot : (slots[0] ?? null)
  const current = { ...draft, type, slot }
  const target = useEntity(vault, draft.target?.id ?? '', {}, { enabled: draft.target !== null })
  const targetName = draft.target?.name ?? target.data?.name ?? '…'
  const ext = (target.data?.ext ?? {}) as Record<string, unknown>
  const recurring = ext.recurrence !== null && ext.recurrence !== undefined
  const ref = refOf(current)
  const selfReference =
    ref !== null &&
    owner?.type === ref.type &&
    owner.type === ref.type &&
    owner.id === ref.id &&
    owner.slot === ref.slot
  const offset = draft.offset ?? ZERO
  const sent: TimePoint | null =
    ref === null || selfReference
      ? null
      : {
          anchor: { kind: 'relative', ref, offset },
          precision: draft.precision === 'default' ? 'base' : draft.precision,
          approximate,
        }
  const probe = useTimeResolution(
    vault,
    sent === null ? null : { dimension_id: dimension.id, items: [{ time_point: wire(sent) }] },
  )
  const probed = probe.isPlaceholderData ? undefined : probe.data?.items[0]?.start
  // The default precision is only known once resolved: the final point is resolved again with it
  // (unless it is the probe's own), so the preview shows what will be stored.
  const precision =
    draft.precision === 'default' ? (probed?.default_precision ?? null) : draft.precision
  const candidate: TimePoint | null =
    sent === null || precision === null || probed?.t == null ? null : { ...sent, precision }
  const again = candidate !== null && candidate.precision !== sent?.precision
  const final = useTimeResolution(
    vault,
    again ? { dimension_id: dimension.id, items: [{ time_point: wire(candidate) }] } : null,
  )
  const resolved = again
    ? final.isPlaceholderData
      ? undefined
      : final.data?.items[0]?.start
    : probed
  const failure = probed?.error ?? resolved?.error ?? null
  const problem = selfReference
    ? 'A time point can’t be relative to itself.'
    : failure !== null
      ? timeProblemMessage(failure.code, failure.message)
      : null
  const point: TimePoint | null =
    candidate === null || resolved?.t == null || problem !== null ? null : candidate
  const reported = JSON.stringify(point)
  useEffect(() => {
    onPoint(point)
    // `reported` stands for `point` (a new object each render).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reported])

  // The precision names a level of the offset's calendar, else of the dimension's default one.
  const precisionLens =
    lenses.find(
      (lens) =>
        lens.calendar !== null &&
        lens.id === (offset.kind === 'calendar' ? offset.calendar_id : dimension.defaultCalendarId),
    ) ?? null
  const levels = precisionLens?.calendar ? [...precisionLens.calendar.levels].reverse() : []

  if (!author) {
    return <p className="text-sm text-muted-foreground">Relative times need edit access.</p>
  }
  if (types.length === 0) {
    return <p className="text-sm text-muted-foreground">Nothing can be referenced yet.</p>
  }
  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-[8rem_1fr] items-start gap-x-3 gap-y-2">
        {types.length > 1 && (
          <>
            <label htmlFor={`${id}-type`} className="pt-2 text-sm text-muted-foreground">
              Relative to
            </label>
            <select
              id={`${id}-type`}
              className={SELECT_CLASS}
              value={type ?? ''}
              onChange={(event) => {
                onDraft({ ...draft, type: event.target.value, target: null, slot: null })
              }}
            >
              {types.map((entry) => (
                <option key={entry.record_type} value={entry.record_type}>
                  {registry?.kind(entry.record_type)?.label ?? entry.record_type}
                </option>
              ))}
            </select>
          </>
        )}
        <span className="pt-2 text-sm text-muted-foreground">Target</span>
        {draft.target === null || type === null ? (
          type === null ? null : (
            <TargetSearch
              vault={vault}
              dimension={dimension}
              type={type}
              onPick={(picked) => {
                onDraft({ ...current, target: picked, occurrence: '' })
              }}
            />
          )
        ) : (
          <div className="flex items-center gap-2 text-sm">
            <span className="font-medium">{targetName}</span>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                onDraft({ ...current, target: null })
              }}
            >
              Change
            </Button>
          </div>
        )}
        <label htmlFor={`${id}-slot`} className="pt-2 text-sm text-muted-foreground">
          Edge
        </label>
        <select
          id={`${id}-slot`}
          className={SELECT_CLASS}
          value={slot ?? ''}
          onChange={(event) => {
            onDraft({ ...current, slot: event.target.value })
          }}
        >
          {slots.map((name) => (
            <option key={name} value={name}>
              {slotLabel(name)}
            </option>
          ))}
        </select>
        {recurring && (
          <>
            <label htmlFor={`${id}-occurrence`} className="pt-2 text-sm text-muted-foreground">
              Occurrence key
            </label>
            <div className="flex flex-col gap-1">
              <Input
                id={`${id}-occurrence`}
                placeholder="The series itself"
                aria-invalid={
                  draft.occurrence.trim() !== '' && !OCCURRENCE_KEY.test(draft.occurrence.trim())
                }
                value={draft.occurrence}
                onChange={(event) => {
                  onDraft({ ...current, occurrence: event.target.value })
                }}
              />
              <p className="text-xs text-muted-foreground">
                One occurrence of the series, by key (e.g. 12 or 12.0); empty for the series.
              </p>
            </div>
          </>
        )}
        <label htmlFor={`${id}-precision`} className="pt-2 text-sm text-muted-foreground">
          Precision
        </label>
        <select
          id={`${id}-precision`}
          className={SELECT_CLASS}
          value={draft.precision}
          onChange={(event) => {
            onDraft({ ...current, precision: event.target.value })
          }}
        >
          <option value="default">
            {probed?.default_precision
              ? `Default (${probed.default_precision})`
              : 'Default (from the target)'}
          </option>
          <option value="base">Exact ({dimension.baseUnit.singular})</option>
          {levels.map((level) => (
            <option key={level} value={level}>
              {level}
            </option>
          ))}
        </select>
      </div>
      <DurationPicker
        dimension={dimension}
        lenses={lenses}
        value={draft.offset}
        label="Offset"
        onChange={(next) => {
          onDraft({ ...current, offset: next })
        }}
      />
      {problem !== null ? (
        <p role="alert" className="text-sm text-destructive">
          {problem}
        </p>
      ) : resolved?.t !== null && resolved !== undefined ? (
        <p className="text-sm text-muted-foreground" data-testid="relative-resolution">
          {resolved.display ?? `t = ${resolved.t}`} · precision {precision}
          {draft.precision === 'default' ? ' (default)' : ''}
        </p>
      ) : null}
    </div>
  )
}
