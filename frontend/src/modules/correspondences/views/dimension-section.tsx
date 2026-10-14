import { Link, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  useCorrespondences,
  useDeleteCorrespondence,
  useDimensions,
  useMutations,
  type CorrespondenceOut,
} from '@/data'

import { CorrespondenceEditor } from './editor'

const SIZE = 220
const RADIUS = 80

/**
 * The dimensions connected to this one through correspondences (docs/modules/correspondences.md,
 * UI): this dimension in the middle, the others of its connected group around it, a line per
 * correspondence. A node opens that dimension's overview. The list beside it is the text view.
 */
export function ConnectedDimensions({
  vault,
  dimensionId,
  rows,
  names,
}: {
  vault: string
  dimensionId: string
  rows: readonly CorrespondenceOut[]
  names: ReadonlyMap<string, string>
}) {
  const navigate = useNavigate()
  // The connected group: breadth first over the correspondences.
  const group = [dimensionId]
  for (const current of group) {
    for (const row of rows) {
      const other =
        row.dimension_a_id === current
          ? row.dimension_b_id
          : row.dimension_b_id === current
            ? row.dimension_a_id
            : null
      if (other !== null && !group.includes(other)) group.push(other)
    }
  }
  const others = group.slice(1)
  if (others.length === 0) return null
  const center = SIZE / 2
  const position = new Map<string, { x: number; y: number }>([
    [dimensionId, { x: center, y: center }],
  ])
  others.forEach((id, index) => {
    const angle = (index / others.length) * 2 * Math.PI - Math.PI / 2
    position.set(id, { x: center + RADIUS * Math.cos(angle), y: center + RADIUS * Math.sin(angle) })
  })
  const edges = rows.filter(
    (row) => position.has(row.dimension_a_id) && position.has(row.dimension_b_id),
  )
  return (
    <svg
      role="img"
      aria-label="Connected dimensions"
      viewBox={`0 0 ${SIZE} ${SIZE}`}
      className="mx-auto w-full max-w-60"
      data-testid="connected-dimensions"
    >
      {edges.map((row) => {
        const from = position.get(row.dimension_a_id)
        const to = position.get(row.dimension_b_id)
        if (from === undefined || to === undefined) return null
        return (
          <line
            key={row.id}
            x1={from.x}
            y1={from.y}
            x2={to.x}
            y2={to.y}
            strokeWidth={2}
            className="stroke-border"
          >
            <title>{row.name}</title>
          </line>
        )
      })}
      {group.map((id) => {
        const at = position.get(id)
        if (at === undefined) return null
        const self = id === dimensionId
        const name = names.get(id) ?? 'Dimension'
        return (
          <g
            key={id}
            role={self ? undefined : 'link'}
            tabIndex={self ? undefined : 0}
            aria-label={self ? undefined : `Open ${name}`}
            className={self ? undefined : 'cursor-pointer'}
            onClick={() => {
              if (!self)
                void navigate({ to: '/v/$vault/d/$dimension', params: { vault, dimension: id } })
            }}
            onKeyDown={(event) => {
              if (!self && event.key === 'Enter') {
                void navigate({ to: '/v/$vault/d/$dimension', params: { vault, dimension: id } })
              }
            }}
          >
            <circle
              cx={at.x}
              cy={at.y}
              r={self ? 8 : 6}
              strokeWidth={2}
              className={
                self ? 'fill-primary stroke-background' : 'fill-muted-foreground stroke-background'
              }
            />
            <text
              x={at.x}
              y={at.y + (at.y > center ? 20 : -12)}
              textAnchor="middle"
              className={`text-[11px] ${self ? 'fill-foreground font-medium' : 'fill-muted-foreground'}`}
            >
              {name}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

/**
 * The dimension overview's Correspondences section: how this dimension's time relates to others
 * (its correspondences, each with the other dimension and its sync points), the connected
 * dimensions, and for authors new / edit / delete through the correspondence editor.
 */
export function CorrespondencesSection({
  vault,
  dimensionId,
}: {
  vault: string
  dimensionId: string
}) {
  const own = useCorrespondences(vault, dimensionId)
  const all = useCorrespondences(vault)
  const dimensions = useDimensions(vault)
  const editable = useMutations() !== null
  const remove = useDeleteCorrespondence(vault)
  const [editing, setEditing] = useState<CorrespondenceOut | 'new' | null>(null)
  const names = new Map((dimensions.data?.items ?? []).map((item) => [item.id, item.name]))
  const items = own.data?.items ?? []
  const otherDimensions = (dimensions.data?.items ?? []).filter((item) => item.id !== dimensionId)

  return (
    <div className="flex flex-col gap-3">
      {own.isPending ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          This dimension’s time isn’t related to any other dimension yet.
        </p>
      ) : (
        <div className="grid items-start gap-3 md:grid-cols-[1fr_auto]">
          <ul className="flex flex-col gap-2 text-sm" aria-label="Correspondences">
            {items.map((row) => {
              const other =
                row.dimension_a_id === dimensionId ? row.dimension_b_id : row.dimension_a_id
              return (
                <li key={row.id} className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{row.name}</span>
                  <span className="text-muted-foreground">with</span>
                  <Link
                    to="/v/$vault/d/$dimension"
                    params={{ vault, dimension: other }}
                    className="underline-offset-2 hover:underline"
                  >
                    {names.get(other) ?? 'another dimension'}
                  </Link>
                  <Badge variant="secondary">
                    {row.points.length} sync {row.points.length === 1 ? 'point' : 'points'}
                  </Badge>
                  {row.extrapolation === 'rate' && <Badge variant="outline">extrapolates</Badge>}
                  <div className="flex-1" />
                  {editable && (
                    <>
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`Edit ${row.name}`}
                        onClick={() => {
                          setEditing(row)
                        }}
                      >
                        Edit
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`Delete ${row.name}`}
                        disabled={remove.isPending}
                        onClick={() => {
                          if (!window.confirm(`Move “${row.name}” to the trash?`)) return
                          remove.mutate(row.id, {
                            onSuccess: () => toast.success(`“${row.name}” moved to the trash`),
                          })
                        }}
                      >
                        Delete
                      </Button>
                    </>
                  )}
                </li>
              )
            })}
          </ul>
          <ConnectedDimensions
            vault={vault}
            dimensionId={dimensionId}
            rows={all.data?.items ?? items}
            names={names}
          />
        </div>
      )}
      {editable && (
        <Button
          variant="outline"
          size="sm"
          className="self-start"
          disabled={otherDimensions.length === 0}
          title={otherDimensions.length === 0 ? 'Create another dimension first' : undefined}
          onClick={() => {
            setEditing('new')
          }}
        >
          New correspondence
        </Button>
      )}
      {editing !== null && (
        <CorrespondenceEditor
          vault={vault}
          dimensionId={dimensionId}
          existing={editing === 'new' ? undefined : editing}
          onClose={() => {
            setEditing(null)
          }}
        />
      )}
    </div>
  )
}
