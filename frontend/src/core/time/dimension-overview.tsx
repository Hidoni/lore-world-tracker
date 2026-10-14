import { formatAbsolute, formatInteger, type TimePoint } from '@lore/chronology'
import { Link } from '@tanstack/react-router'
import { useState, type ReactNode } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useExtensionList } from '@/core/modules'
import {
  ApiError,
  useEntities,
  useEntity,
  useMutations,
  useTimelines,
  useUpdateLatest,
} from '@/data'

import { BigNumberInput } from './big-number-input'
import { MomentDisplay } from './moment-display'
import { useDimensionLenses } from './time-context'
import { TimePointPicker } from './time-point-picker'

/** A timeline of `GET /dimensions/{id}/timelines` (moments already `bigint`). */
interface TimelineNode {
  id: string
  name: string
  is_prime: boolean
  children: readonly TimelineNode[]
}

/** Counts shown as "500+" past one page. */
const COUNT_PAGE = 500

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section aria-label={title} className="flex flex-col gap-2 rounded-lg border p-4">
      <h2 className="text-sm font-semibold">{title}</h2>
      {children}
    </section>
  )
}

/** Why a change of the dimension was refused, with the records that stand in the way. */
function DimensionProblem({ vault, error }: { vault: string; error: unknown }) {
  if (!(error instanceof ApiError)) return null
  const records = Array.isArray(error.context.records)
    ? (error.context.records as { record_type?: unknown; id?: unknown; slot?: unknown }[])
    : []
  return (
    <div role="alert" className="text-sm text-destructive">
      <p>
        {error.errors[0]?.message && records.length === 0 ? error.errors[0].message : error.detail}
      </p>
      {records.length > 0 && (
        <ul className="ml-4 list-disc">
          {records.slice(0, 10).map((record, index) =>
            typeof record.id === 'string' ? (
              <li key={`${record.id}:${String(record.slot)}:${index}`}>
                <RecordLink vault={vault} id={record.id} />{' '}
                <span className="text-muted-foreground">({String(record.slot)})</span>
              </li>
            ) : null,
          )}
          {records.length > 10 && <li>and {records.length - 10} more</li>}
        </ul>
      )}
    </div>
  )
}

function RecordLink({ vault, id }: { vault: string; id: string }) {
  const entity = useEntity(vault, id)
  return (
    <Link to="/v/$vault/e/$entity" params={{ vault, entity: id }} className="underline">
      {entity.data?.name ?? 'a record'}
    </Link>
  )
}

function DurationEditor({
  vault,
  id,
  duration,
  unit,
  editable,
}: {
  vault: string
  id: string
  duration: bigint
  unit: { singular: string; plural: string; abbr: string }
  editable: boolean
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<bigint | null>(duration)
  const update = useUpdateLatest(vault, { toast: false })
  if (!editing) {
    return (
      <div className="flex items-center gap-2">
        <span>{formatAbsolute(duration, unit)}</span>
        {editable && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              update.reset()
              setDraft(duration)
              setEditing(true)
            }}
          >
            Change
          </Button>
        )}
      </div>
    )
  }
  return (
    <div className="flex flex-col gap-2">
      <BigNumberInput
        aria-label={`Duration (${unit.plural})`}
        value={draft}
        min={1n}
        onChange={setDraft}
      />
      <div className="flex gap-2">
        <Button
          size="sm"
          disabled={draft === null || update.isPending}
          onClick={() => {
            if (draft === null) return
            update.mutate(
              { id, change: { ext: { duration: draft.toString() } } },
              {
                onSuccess: () => {
                  setEditing(false)
                },
              },
            )
          }}
        >
          Save
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            setEditing(false)
          }}
        >
          Cancel
        </Button>
      </div>
      {update.isError && <DimensionProblem vault={vault} error={update.error} />}
    </div>
  )
}

function PresentEditor({
  vault,
  dimensionId,
  present,
}: {
  vault: string
  dimensionId: string
  present: TimePoint | null
}) {
  const { dimension, lenses } = useDimensionLenses(vault, dimensionId)
  const [editing, setEditing] = useState(false)
  const [point, setPoint] = useState<TimePoint | null>(present)
  const update = useUpdateLatest(vault, { toast: false })
  if (dimension === null) return null
  if (!editing) {
    return (
      <div className="flex items-center gap-2">
        {dimension.present === null ? (
          <span className="text-muted-foreground">Not set (all time is shown)</span>
        ) : (
          <MomentDisplay
            vault={vault}
            dimension={dimensionId}
            moment={{ t: dimension.present, precision: present?.precision ?? 'base' }}
          />
        )}
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            update.reset()
            setPoint(present)
            setEditing(true)
          }}
        >
          {dimension.present === null ? 'Set' : 'Change'}
        </Button>
      </div>
    )
  }
  const save = (value: TimePoint | null) => {
    update.mutate(
      { id: dimensionId, change: { ext: { present: value } } },
      {
        onSuccess: () => {
          setEditing(false)
        },
      },
    )
  }
  return (
    <div className="flex flex-col gap-2">
      <TimePointPicker
        vault={vault}
        dimension={dimension}
        lenses={lenses}
        value={present}
        label="The present"
        owner={{ type: 'dimension', id: dimensionId, slot: 'present' }}
        onChange={setPoint}
        onConfirm={save}
      />
      <div className="flex gap-2">
        <Button
          size="sm"
          disabled={point === null || update.isPending}
          onClick={() => {
            save(point)
          }}
        >
          Save
        </Button>
        {present !== null && (
          <Button
            size="sm"
            variant="outline"
            disabled={update.isPending}
            onClick={() => {
              save(null)
            }}
          >
            Clear
          </Button>
        )}
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            setEditing(false)
          }}
        >
          Cancel
        </Button>
      </div>
      {update.isError && <DimensionProblem vault={vault} error={update.error} />}
    </div>
  )
}

function TimelineTree({ vault, nodes }: { vault: string; nodes: readonly TimelineNode[] }) {
  return (
    <ul className="ml-4 list-disc text-sm">
      {nodes.map((node) => (
        <li key={node.id}>
          <Link
            to="/v/$vault/e/$entity"
            params={{ vault, entity: node.id }}
            className="underline-offset-2 hover:underline"
          >
            {node.name}
          </Link>
          {node.is_prime && (
            <Badge variant="outline" className="ml-2">
              Prime
            </Badge>
          )}
          {node.children.length > 0 && <TimelineTree vault={vault} nodes={node.children} />}
        </li>
      ))}
    </ul>
  )
}

function count(page: { items: unknown[]; next_cursor: string | null } | undefined): string {
  if (page === undefined) return '…'
  return page.next_cursor === null ? String(page.items.length) : `${COUNT_PAGE}+`
}

/**
 * A dimension's overview (`/v/$vault/d/$dimension`, frontend.md §4): its time spec (base unit,
 * an editable duration `D` that explains which records stand in the way of shrinking it), its
 * calendars with the default, its timelines, the present moment, counts and recent events.
 */
export function DimensionOverview({ vault, dimensionId }: { vault: string; dimensionId: string }) {
  const entity = useEntity(vault, dimensionId)
  const { dimension, lenses } = useDimensionLenses(vault, dimensionId)
  const timelines = useTimelines(vault, dimensionId)
  const sections = useExtensionList('dimensionSections', vault)
  const editable = useMutations() !== null
  const update = useUpdateLatest(vault, { toast: false })
  const events = useEntities(vault, {
    kind: ['event'],
    dimension: dimensionId,
    include_multiversal: false,
    limit: COUNT_PAGE,
  })
  const recent = useEntities(vault, {
    kind: ['event'],
    dimension: dimensionId,
    include_multiversal: false,
    sort: '-updated',
    limit: 5,
  })
  if (entity.isPending) return <p className="p-6 text-sm text-muted-foreground">Loading…</p>
  if (entity.data === undefined || dimension === null) {
    return <p className="p-6 text-sm text-muted-foreground">This dimension can’t be shown.</p>
  }
  const ext = (entity.data.ext ?? {}) as { present?: TimePoint | null }
  const calendars = lenses.filter((lens) => lens.calendar !== null)

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-4 p-6">
      <header className="flex flex-wrap items-center gap-2">
        <h1 className="text-2xl font-semibold">{entity.data.name}</h1>
        <Badge variant="secondary">Dimension</Badge>
        <div className="flex-1" />
        <Button variant="outline" size="sm" asChild>
          <Link to="/v/$vault/d/$dimension/timeline" params={{ vault, dimension: dimensionId }}>
            Open the timeline
          </Link>
        </Button>
        <Button variant="outline" size="sm" asChild>
          <Link to="/v/$vault/d/$dimension/events" params={{ vault, dimension: dimensionId }}>
            Event outline
          </Link>
        </Button>
        <Button variant="ghost" size="sm" asChild>
          <Link to="/v/$vault/e/$entity" params={{ vault, entity: dimensionId }}>
            Details
          </Link>
        </Button>
      </header>
      {entity.data.summary && <p className="text-muted-foreground">{entity.data.summary}</p>}
      <div className="grid gap-4 md:grid-cols-2">
        <Section title="Time">
          <dl className="grid grid-cols-[7rem_1fr] items-baseline gap-x-3 gap-y-2 text-sm">
            <dt className="text-muted-foreground">Base unit</dt>
            <dd>
              {dimension.baseUnit.singular} ({dimension.baseUnit.abbr})
            </dd>
            <dt className="text-muted-foreground">Duration</dt>
            <dd>
              <DurationEditor
                vault={vault}
                id={dimensionId}
                duration={dimension.duration}
                unit={dimension.baseUnit}
                editable={editable}
              />
            </dd>
            <dt className="text-muted-foreground">The present</dt>
            <dd>
              {editable ? (
                <PresentEditor
                  vault={vault}
                  dimensionId={dimensionId}
                  present={ext.present ?? null}
                />
              ) : dimension.present === null ? (
                <span className="text-muted-foreground">Not set</span>
              ) : (
                <MomentDisplay
                  vault={vault}
                  dimension={dimensionId}
                  moment={{ t: dimension.present, precision: ext.present?.precision ?? 'base' }}
                />
              )}
            </dd>
          </dl>
        </Section>
        <Section title="Calendars">
          {calendars.length === 0 ? (
            <p className="text-sm text-muted-foreground">No calendars yet.</p>
          ) : (
            <ul className="flex flex-col gap-1 text-sm">
              {calendars.map((lens) => {
                const isDefault = lens.id === dimension.defaultCalendarId
                return (
                  <li key={lens.id} className="flex items-center gap-2">
                    <Link
                      to="/v/$vault/e/$entity"
                      params={{ vault, entity: lens.id }}
                      className="underline-offset-2 hover:underline"
                    >
                      {lens.name}
                    </Link>
                    {isDefault && <Badge>Default</Badge>}
                    <div className="flex-1" />
                    {editable && !isDefault && (
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={update.isPending}
                        onClick={() => {
                          update.mutate({
                            id: dimensionId,
                            change: { ext: { default_calendar_id: lens.id } },
                          })
                        }}
                      >
                        Make default
                      </Button>
                    )}
                    <Button variant="ghost" size="sm" asChild>
                      <Link
                        to="/v/$vault/calendars/$calendar/edit"
                        params={{ vault, calendar: lens.id }}
                      >
                        Edit
                      </Link>
                    </Button>
                  </li>
                )
              })}
            </ul>
          )}
          {editable && (
            <Button variant="outline" size="sm" className="self-start" asChild>
              <Link
                to="/v/$vault/calendars/new"
                params={{ vault }}
                search={{ dimension: dimensionId }}
              >
                New calendar
              </Link>
            </Button>
          )}
          {update.isError && <DimensionProblem vault={vault} error={update.error} />}
        </Section>
        <Section title="Timelines">
          {timelines.data === undefined ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : (
            <TimelineTree vault={vault} nodes={timelines.data.items} />
          )}
        </Section>
        <Section title="Statistics">
          <dl className="grid grid-cols-[7rem_1fr] gap-x-3 gap-y-1 text-sm">
            <dt className="text-muted-foreground">Events</dt>
            <dd>{count(events.data)}</dd>
            <dt className="text-muted-foreground">Calendars</dt>
            <dd>{formatInteger(BigInt(calendars.length))}</dd>
          </dl>
        </Section>
      </div>
      {sections.map((section) => (
        <Section key={section.id} title={section.title}>
          <section.component vault={vault} dimensionId={dimensionId} />
        </Section>
      ))}
      <Section title="Recent events">
        {(recent.data?.items.length ?? 0) === 0 ? (
          <p className="text-sm text-muted-foreground">No events yet.</p>
        ) : (
          <ul className="flex flex-col gap-1 text-sm">
            {recent.data?.items.map((event) => (
              <li key={event.id}>
                <Link
                  to="/v/$vault/e/$entity"
                  params={{ vault, entity: event.id }}
                  className="underline-offset-2 hover:underline"
                >
                  {event.name}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  )
}
