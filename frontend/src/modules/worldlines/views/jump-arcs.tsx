import { toPx, type Viewport } from '@lore/chronology/viewport'
import { Link } from '@tanstack/react-router'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import type { TimelineLayerProps } from '@/core/modules'
import { useQuickSearch, useWorldline, type WorldlineSegment } from '@/data'

const ARC_TOP = 18

export interface Jump {
  from: WorldlineSegment
  to: WorldlineSegment
}

/** The jumps of a worldline: from each segment's end to the next one's start. */
export function jumpsOf(segments: readonly WorldlineSegment[]): Jump[] {
  return segments.slice(1).flatMap((to, index) => {
    const from = segments[index]
    return from === undefined ? [] : [{ from, to }]
  })
}

/** One entity's jumps drawn on this dimension's axis. */
function EntityArcs({
  vault,
  entity,
  dimensionId,
  v,
  height,
}: {
  vault: string
  entity: { id: string; name: string }
  dimensionId: string
  v: Viewport
  height: number
}) {
  const worldline = useWorldline(vault, entity.id)
  const jumps = worldline.data?.implicit === false ? jumpsOf(worldline.data.segments) : []
  return (
    <g data-testid="jump-arcs" data-entity={entity.id}>
      {jumps.map(({ from, to }) => {
        const leaves = from.dimension_id === dimensionId && from.end_t !== null
        const arrives = to.dimension_id === dimensionId && to.start_t !== null
        const x1 = leaves && from.end_t !== null ? toPx(v, from.end_t) : null
        const x2 = arrives && to.start_t !== null ? toPx(v, to.start_t) : null
        const key = `${from.id ?? from.seq}-${to.id ?? to.seq}`
        if (x1 !== null && x2 !== null) {
          // Both ends here: an arc over the lanes, from the departure to the arrival.
          const mid = (x1 + x2) / 2
          return (
            <g key={key} data-testid="jump-arc">
              <path
                d={`M ${x1} ${height} Q ${mid} ${ARC_TOP - 40} ${x2} ${height}`}
                fill="none"
                strokeWidth={2}
                strokeDasharray="5 3"
                className="stroke-violet-500"
              />
              <title>{`${entity.name} jumps`}</title>
            </g>
          )
        }
        // One end elsewhere (another dimension): an edge marker at the end that is here.
        const x = x1 ?? x2
        if (x === null) return null
        return (
          <g key={key} data-testid="jump-edge">
            <line
              x1={x}
              x2={x}
              y1={ARC_TOP}
              y2={height}
              strokeWidth={2}
              strokeDasharray="2 3"
              className="stroke-violet-500"
            />
            <text
              x={x + 3}
              y={ARC_TOP + 8}
              className="fill-violet-600 text-[10px] dark:fill-violet-400"
            >
              {x1 !== null ? `${entity.name} leaves this dimension` : `${entity.name} arrives`}
            </text>
          </g>
        )
      })}
    </g>
  )
}

/** Choose entities whose jumps to draw (search, then toggle). */
function Chooser({
  vault,
  chosen,
  onChange,
}: {
  vault: string
  chosen: readonly { id: string; name: string }[]
  onChange: (next: { id: string; name: string }[]) => void
}) {
  const [query, setQuery] = useState('')
  const q = query.trim()
  const results = useQuickSearch(vault, { q })
  const hits = q === '' ? [] : (results.data?.items ?? []).slice(0, 8)
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" className="pointer-events-auto h-7 text-xs">
          Jumps{chosen.length > 0 ? ` (${chosen.length})` : ''}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="flex w-64 flex-col gap-2">
        <p className="text-xs text-muted-foreground">Draw the time jumps of…</p>
        {chosen.map((entity) => (
          <div key={entity.id} className="flex items-center gap-2 text-sm">
            <label className="flex flex-1 items-center gap-2">
              <input
                type="checkbox"
                checked
                onChange={() => {
                  onChange(chosen.filter((each) => each.id !== entity.id))
                }}
              />
              {entity.name}
            </label>
            {/* The jumps as a list (frontend.md §9.6): the personal timeline's list view. */}
            <Link
              to="/v/$vault/m/$module/$"
              params={{ vault, module: 'worldlines', _splat: `entities/${entity.id}` }}
              aria-label={`Personal timeline of ${entity.name}`}
              className="text-xs text-primary underline-offset-2 hover:underline"
            >
              Personal timeline
            </Link>
          </div>
        ))}
        <Input
          aria-label="Find an entity"
          placeholder="Find an entity…"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value)
          }}
        />
        {hits.map((hit) => (
          <button
            key={hit.entity_id}
            type="button"
            className="rounded px-2 py-1 text-left text-sm hover:bg-accent"
            onClick={() => {
              if (!chosen.some((each) => each.id === hit.entity_id)) {
                onChange([...chosen, { id: hit.entity_id, name: hit.name }])
              }
              setQuery('')
            }}
          >
            {hit.name}
          </button>
        ))}
      </PopoverContent>
    </Popover>
  )
}

/**
 * The timeline's worldline layer (docs/modules/worldlines.md, UI): for chosen entities, an arc
 * from each jump's departure to its arrival when both are in this dimension, and an edge marker
 * at the end that is here when the jump leads to (or comes from) another dimension.
 */
export function JumpArcsLayer({ vault, dimensionId, v, height }: TimelineLayerProps) {
  const [chosen, setChosen] = useState<{ id: string; name: string }[]>([])
  return (
    <>
      <svg
        width={v.widthPx}
        height={height}
        className="pointer-events-none absolute top-0 left-0 z-10"
        aria-hidden
      >
        {chosen.map((entity) => (
          <EntityArcs
            key={entity.id}
            vault={vault}
            entity={entity}
            dimensionId={dimensionId}
            v={v}
            height={height}
          />
        ))}
      </svg>
      <div className="pointer-events-none absolute top-1 right-1 z-20">
        <Chooser vault={vault} chosen={chosen} onChange={setChosen} />
      </div>
    </>
  )
}
