import { toPx, viewport } from '@lore/chronology/viewport'
import { Link, useParams } from '@tanstack/react-router'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { MomentDisplay } from '@/core/time'
import { useDimensions, useEntity, usePersonalTimeline, type PersonalItem } from '@/data'

const WIDTH = 960
const HEIGHT = 150
const AXIS_Y = 96
const PAD = 24

const KIND_LABEL: Record<PersonalItem['kind'], string> = {
  participation: 'Takes part',
  existence_start: 'Begins to exist',
  existence_end: 'Stops existing',
  jump: 'Jumps',
}

/** Subjective time floored to a base unit (the age's `t`), for placing on the axis. */
const lived = (item: PersonalItem): bigint | null => item.age?.t ?? null

function ItemMoment({ vault, item }: { vault: string; item: PersonalItem }) {
  if (item.t === null || item.dimension_id === null) return <span>—</span>
  return (
    <MomentDisplay
      vault={vault}
      dimension={item.dimension_id}
      moment={{ t: item.t, precision: 'base' }}
    />
  )
}

function Destination({
  vault,
  item,
  names,
}: {
  vault: string
  item: PersonalItem
  names: ReadonlyMap<string, string>
}) {
  const toT = item.to_t ?? null
  const toDimension = item.to_dimension_id ?? null
  const toTimeline = item.to_timeline_id ?? null
  if (item.kind !== 'jump' || toT === null || toDimension === null) return null
  return (
    <span className="text-muted-foreground">
      to{' '}
      <MomentDisplay vault={vault} dimension={toDimension} moment={{ t: toT, precision: 'base' }} />
      {toDimension !== item.dimension_id && ` in ${names.get(toDimension) ?? 'another dimension'}`}
      {toTimeline !== null &&
        toTimeline !== item.timeline_id &&
        ` (${names.get(toTimeline) ?? 'another timeline'})`}
    </span>
  )
}

/** The personal timeline as a horizontal axis of lived time: items as marks, jumps as breaks. */
function SubjectiveAxis({
  items,
  names,
}: {
  items: readonly PersonalItem[]
  names: ReadonlyMap<string, string>
}) {
  const placed = items.filter((item) => lived(item) !== null)
  const ends = placed.map((item) => lived(item) ?? 0n)
  const max = ends.reduce((a, b) => (b > a ? b : a), 1n)
  const v = viewport(0n, max, WIDTH - 2 * PAD)
  const x = (t: bigint) => PAD + toPx(v, t)
  return (
    <svg
      role="img"
      aria-label="Lived time, from the start of the worldline"
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      className="w-full"
      data-testid="subjective-axis"
    >
      <line
        x1={PAD}
        x2={WIDTH - PAD}
        y1={AXIS_Y}
        y2={AXIS_Y}
        className="stroke-border"
        strokeWidth={2}
      />
      {placed.map((item, index) => {
        const at = x(lived(item) ?? 0n)
        const key = `${item.kind}-${item.event_id ?? ''}-${index}`
        if (item.kind === 'jump') {
          return (
            <g key={key} data-testid="jump-break">
              <path
                d={`M ${at - 4} ${AXIS_Y - 10} L ${at + 4} ${AXIS_Y - 3} L ${at - 4} ${AXIS_Y + 3} L ${at + 4} ${AXIS_Y + 10}`}
                fill="none"
                strokeWidth={2}
                className="stroke-amber-500"
              />
              <text x={at + 6} y={AXIS_Y + 26} className="fill-muted-foreground text-[10px]">
                jump
                {item.to_dimension_id != null && item.to_dimension_id !== item.dimension_id
                  ? ` to ${names.get(item.to_dimension_id) ?? 'another dimension'}`
                  : ''}
              </text>
            </g>
          )
        }
        const row = index % 3
        return (
          <g key={key} data-testid="lived-mark">
            <line x1={at} x2={at} y1={AXIS_Y - 8} y2={AXIS_Y} className="stroke-muted-foreground" />
            <circle
              cx={at}
              cy={AXIS_Y}
              r={4}
              strokeWidth={2}
              className={
                item.kind === 'participation'
                  ? 'fill-primary stroke-background'
                  : 'fill-muted-foreground stroke-background'
              }
            />
            <text x={at} y={AXIS_Y - 24 - row * 24} className="fill-foreground text-[11px]">
              {item.name ?? KIND_LABEL[item.kind]}
            </text>
            {item.age?.display != null && (
              <text x={at} y={AXIS_Y - 13 - row * 24} className="fill-muted-foreground text-[9px]">
                {item.age.display}
              </text>
            )}
          </g>
        )
      })}
    </svg>
  )
}

/**
 * The personal timeline view (`/m/worldlines/entities/<id>`, docs/modules/worldlines.md, UI):
 * what the entity lives through in its own order, on an axis of lived (subjective) time, with
 * jumps drawn as breaks labelled with where they lead, and existence changes. List mode shows
 * the same items as a table (also the accessible alternative).
 */
export default function PersonalTimelinePage() {
  // Module routes aren't in the router's generated types.
  const params: { vault?: string; entity?: string } = useParams({ strict: false })
  const vault = params.vault ?? ''
  const entityId = params.entity ?? ''
  const entity = useEntity(vault, entityId)
  const timeline = usePersonalTimeline(vault, entityId)
  const dimensions = useDimensions(vault)
  const [list, setList] = useState(false)
  const names = new Map((dimensions.data?.items ?? []).map((item) => [item.id, item.name]))
  const items = timeline.data?.items ?? []
  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-4 p-6">
      <header className="flex flex-wrap items-center gap-2">
        <h1 className="text-2xl font-semibold">{entity.data?.name ?? '…'}: personal timeline</h1>
        <div className="flex-1" />
        <Button
          variant="outline"
          size="sm"
          aria-pressed={list}
          onClick={() => {
            setList((current) => !current)
          }}
        >
          {list ? 'Axis view' : 'List view'}
        </Button>
        <Button variant="ghost" size="sm" asChild>
          <Link to="/v/$vault/e/$entity" params={{ vault, entity: entityId }}>
            Back to {entity.data?.name ?? 'the entity'}
          </Link>
        </Button>
      </header>
      {timeline.data?.implicit === true && (
        <p className="text-sm text-muted-foreground">
          No time travel: this is the lifespan in order.
        </p>
      )}
      {timeline.isPending ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-muted-foreground">Nothing lived through yet.</p>
      ) : list ? (
        <table className="w-full text-sm" aria-label="Personal timeline">
          <thead className="text-left text-xs text-muted-foreground">
            <tr>
              <th className="py-1">Age</th>
              <th>What</th>
              <th>When in the world</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item, index) => (
              <tr key={`${item.kind}-${item.event_id ?? ''}-${index}`} className="border-t">
                <td className="py-1 pr-3 text-muted-foreground">
                  {item.age?.display ?? (item.subjective_t === null ? 'not there' : '')}
                </td>
                <td className="pr-3">
                  {item.event_id != null && item.kind !== 'jump' ? (
                    <Link
                      to="/v/$vault/e/$entity"
                      params={{ vault, entity: item.event_id }}
                      className="text-primary underline-offset-2 hover:underline"
                    >
                      {item.name}
                    </Link>
                  ) : (
                    KIND_LABEL[item.kind]
                  )}
                  {(item.roles ?? []).length > 0 && (
                    <span className="text-xs text-muted-foreground">
                      {' '}
                      as {(item.roles ?? []).join(', ')}
                    </span>
                  )}
                  {item.assignment === 'ambiguous' && (
                    <span className="text-xs text-amber-600"> (which visit?)</span>
                  )}
                </td>
                <td>
                  <ItemMoment vault={vault} item={item} />{' '}
                  <Destination vault={vault} item={item} names={names} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <SubjectiveAxis items={items} names={names} />
      )}
      {timeline.data?.truncated === true && (
        <p className="text-xs text-muted-foreground">Only the first items are shown.</p>
      )}
    </div>
  )
}
