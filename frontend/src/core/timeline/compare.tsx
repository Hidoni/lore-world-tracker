import { toPx, type Viewport } from '@lore/chronology/viewport'
import { ChevronDownIcon, ColumnsIcon } from 'lucide-react'
import { useMemo } from 'react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import type { Branching } from '@/core/time'
import { useBranchDiffs, type TimelineNode } from '@/data'

/**
 * Compare mode's control (frontend.md §9.5): the dimension's other timelines, each shown in lane
 * groups of its own under the viewed one when checked. Hidden while the dimension has only one.
 */
export function CompareMenu({
  branching,
  value,
  onChange,
}: {
  branching: Branching
  value: readonly string[]
  onChange: (next: string[]) => void
}) {
  const others = branching.timelines.filter(
    ({ node }) => !node.trashed && node.id !== branching.timelineId,
  )
  if (others.length === 0) return null
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant={value.length > 0 ? 'secondary' : 'outline'}
          size="sm"
          aria-label={
            value.length > 0 ? `Compare with ${value.length} timelines` : 'Compare timelines'
          }
        >
          <ColumnsIcon aria-hidden /> Compare
          {value.length > 0 && <span className="text-xs">({value.length})</span>}
          <ChevronDownIcon aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>Compare with</DropdownMenuLabel>
        {others.map(({ node, depth }) => (
          <DropdownMenuCheckboxItem
            key={node.id}
            checked={value.includes(node.id)}
            onSelect={(event) => {
              event.preventDefault()
            }}
            onCheckedChange={(checked) => {
              onChange(checked ? [...value, node.id] : value.filter((each) => each !== node.id))
            }}
          >
            <span style={{ paddingLeft: `${depth * 0.75}rem` }}>{node.name}</span>
          </DropdownMenuCheckboxItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/**
 * The events each compared branch created or changed after its branch point (its diff against its
 * parent), by timeline: compare mode outlines them. Prime timelines have none.
 */
export function useDifferences(
  vault: string,
  timelines: readonly (TimelineNode | null)[],
): Map<string, ReadonlySet<string>> {
  const branches = timelines
    .filter((node): node is TimelineNode => node !== null && !node.is_prime)
    .map((node) => node.id)
  const diffs = useBranchDiffs(vault, branches)
  return useMemo(() => {
    const found = new Map<string, ReadonlySet<string>>()
    for (const [timeline, diff] of diffs) {
      found.set(
        timeline,
        new Set(
          [...diff.created, ...diff.overridden]
            .filter((record) => record.record_type === 'event')
            .map((record) => record.entity_id),
        ),
      )
    }
    return found
  }, [diffs])
}

/**
 * Where the compared branches diverge (frontend.md §9.5): a dashed line at each one's branch
 * point across the lanes, with its name.
 */
export function DivergenceMarkers({
  v,
  height,
  timelines,
}: {
  v: Viewport
  height: number
  timelines: readonly TimelineNode[]
}) {
  return (
    <svg
      width={v.widthPx}
      height={height}
      className="pointer-events-none absolute top-0 left-0 z-10"
      aria-hidden
    >
      {timelines.map((node) => {
        if (node.is_prime || node.branch_t === null) return null
        const x = toPx(v, node.branch_t)
        if (x < 0 || x > v.widthPx) return null
        return (
          <g key={node.id} data-testid="divergence-marker" data-timeline={node.id}>
            <line
              x1={x}
              x2={x}
              y1={0}
              y2={height}
              className="stroke-amber-500"
              strokeWidth={1.5}
              strokeDasharray="4 3"
            />
            <text x={x + 3} y={10} className="fill-amber-600 text-[10px] dark:fill-amber-400">
              {node.name} branches
            </text>
          </g>
        )
      })}
    </svg>
  )
}
