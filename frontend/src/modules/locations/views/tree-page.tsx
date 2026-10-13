import { Link, useParams } from '@tanstack/react-router'
import { ChevronRightIcon } from 'lucide-react'
import { useState } from 'react'

import { KindIcon, useKind, type Kind } from '@/core/registry'
import { useLocationTree, type LocationNode } from '@/data'
import { cn } from '@/lib/utils'

import { LOCATION, typeLabel } from '../types'

const DEPTH = 6

/** The nodes of `nodes` with `type`, or with a descendant of that type (loaded ones). */
export function filterTree(nodes: readonly LocationNode[], type: string): LocationNode[] {
  return nodes.flatMap((node) => {
    const children = node.children === null ? null : filterTree(node.children, type)
    if (node.location_type === type || (children !== null && children.length > 0)) {
      return [{ ...node, children }]
    }
    return []
  })
}

/**
 * The location tree view (`/m/locations/tree`): every location in its containment tree, as a
 * collapsible outline (the first levels open), with a filter by type.
 */
export default function LocationTreePage() {
  const vault = useParams({ strict: false }).vault ?? ''
  const kind = useKind(LOCATION, vault)
  const [type, setType] = useState('')
  const tree = useLocationTree(vault, { depth: DEPTH, limit: 500 })
  const options = kind?.fields.find((field) => field.key === 'location_type')?.options ?? []
  const items = tree.data?.items ?? []
  const shown = type === '' ? items : filterTree(items, type)
  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-4 p-6">
      <h1 className="text-2xl font-semibold">Location tree</h1>
      <label className="flex items-center gap-2 text-sm">
        Type
        <select
          className="h-8 rounded-md border bg-transparent px-2 text-sm"
          value={type}
          onChange={(event) => {
            setType(event.target.value)
          }}
        >
          <option value="">All types</option>
          {options.map((option) => (
            <option key={option.key} value={option.key}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      {tree.isPending ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : shown.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {items.length === 0 ? 'No locations yet.' : 'No locations of this type.'}
        </p>
      ) : (
        <Outline vault={vault} kind={kind} nodes={shown} depth={0} open={type !== ''} />
      )}
    </div>
  )
}

function Outline({
  vault,
  kind,
  nodes,
  depth,
  open,
}: {
  vault: string
  kind: Kind | undefined
  nodes: readonly LocationNode[]
  depth: number
  /** Open every node (a filtered tree). */
  open: boolean
}) {
  return (
    <ul aria-label={depth === 0 ? 'Locations' : undefined}>
      {nodes.map((node) => (
        <OutlineNode
          key={node.id}
          vault={vault}
          kind={kind}
          node={node}
          depth={depth}
          open={open}
        />
      ))}
    </ul>
  )
}

function OutlineNode({
  vault,
  kind,
  node,
  depth,
  open: forced,
}: {
  vault: string
  kind: Kind | undefined
  node: LocationNode
  depth: number
  open: boolean
}) {
  const [open, setOpen] = useState(forced || depth < 2)
  const label = typeLabel(kind, node.location_type)
  const expandable = node.child_count > 0
  return (
    <li aria-label={node.name}>
      <div className="flex items-center gap-1 py-0.5" style={{ paddingLeft: `${depth * 1.25}rem` }}>
        {expandable ? (
          <button
            type="button"
            aria-label={`${open ? 'Collapse' : 'Expand'} ${node.name}`}
            className="rounded p-0.5 text-muted-foreground hover:text-foreground"
            onClick={() => {
              setOpen(!open)
            }}
          >
            <ChevronRightIcon
              aria-hidden
              className={cn('size-4 transition-transform', open && 'rotate-90')}
            />
          </button>
        ) : (
          <span className="w-5 shrink-0" aria-hidden />
        )}
        {kind && (
          <KindIcon
            kind={kind}
            value={node.location_type}
            className="size-4 shrink-0"
            style={{ color: kind.color }}
          />
        )}
        <Link
          to="/v/$vault/e/$entity"
          params={{ vault, entity: node.id }}
          className="text-sm hover:underline"
        >
          {node.name}
        </Link>
        {label !== null && <span className="text-xs text-muted-foreground">{label}</span>}
      </div>
      {open &&
        expandable &&
        (node.children === null ? (
          <LazyLevel vault={vault} kind={kind} root={node.id} depth={depth + 1} />
        ) : (
          <Outline
            vault={vault}
            kind={kind}
            nodes={node.children}
            depth={depth + 1}
            open={forced}
          />
        ))}
    </li>
  )
}

/** Levels below the first load: fetched when opened. */
function LazyLevel({
  vault,
  kind,
  root,
  depth,
}: {
  vault: string
  kind: Kind | undefined
  root: string
  depth: number
}) {
  const tree = useLocationTree(vault, { root, depth: DEPTH, limit: 500 })
  if (tree.data === undefined) {
    return (
      <p className="text-xs text-muted-foreground" style={{ paddingLeft: `${depth * 1.25}rem` }}>
        Loading…
      </p>
    )
  }
  return <Outline vault={vault} kind={kind} nodes={tree.data.items} depth={depth} open={false} />
}
