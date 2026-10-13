import { Link } from '@tanstack/react-router'
import { PlusIcon } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { CreateEntityDialog } from '@/core/entities'
import type { EntityViewProps } from '@/core/modules'
import { childKinds } from '@/core/navigation'
import { useKindRegistry, type Kind } from '@/core/registry'
import { useChildren, useEntity, useMutations, type components } from '@/data'

type TreeNode = components['schemas']['TreeNode']

/**
 * A misc entry's children of every kind and dimension, grouped by kind (in registry order), with
 * "Add child" for every kind that may be placed under it (docs/modules/misc.md, UI).
 */
export function ChildrenPanel({ vault, entityId }: EntityViewProps) {
  const registry = useKindRegistry(vault)
  const entity = useEntity(vault, entityId)
  const children = useChildren(vault, entityId, { limit: 500 })
  const editable = useMutations() !== null && entity.data?.deleted_at === null
  const [creating, setCreating] = useState<Kind | null>(null)
  if (registry === undefined || entity.data === undefined) return null
  const items = children.data?.items ?? []
  const byKind = new Map<string, TreeNode[]>()
  for (const child of items) byKind.set(child.kind, [...(byKind.get(child.kind) ?? []), child])
  const groups = registry.kinds.filter((kind) => byKind.has(kind.key))
  // Children of kinds no longer registered (a disabled module's) aren't returned at all.
  const creatable = childKinds(registry, entity.data.kind)

  return (
    <div className="flex flex-col gap-3">
      {children.isPending ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : groups.length === 0 ? (
        <p className="text-sm text-muted-foreground">Nothing is inside {entity.data.name} yet.</p>
      ) : (
        groups.map((kind) => {
          const Icon = kind.icon
          const members = byKind.get(kind.key) ?? []
          return (
            <section key={kind.key} aria-label={kind.plural} className="flex flex-col gap-1">
              <h4 className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                <Icon aria-hidden className="size-3.5" style={{ color: kind.color }} />
                {kind.plural} <span aria-hidden>({members.length})</span>
              </h4>
              <ul className="flex flex-wrap gap-x-4 gap-y-1">
                {members.map((child) => (
                  <li key={child.id}>
                    <Link
                      to="/v/$vault/e/$entity"
                      params={{ vault, entity: child.id }}
                      className="text-sm text-primary underline-offset-2 hover:underline"
                    >
                      {child.name}
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          )
        })
      )}
      {children.data?.next_cursor != null && (
        <p className="text-xs text-muted-foreground">Showing the first {items.length}.</p>
      )}
      {editable && creatable.length > 0 && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm" className="self-start">
              <PlusIcon aria-hidden /> Add child
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            {creatable.map((kind) => {
              const Icon = kind.icon
              return (
                <DropdownMenuItem
                  key={kind.key}
                  onSelect={() => {
                    setCreating(kind)
                  }}
                >
                  <Icon aria-hidden style={{ color: kind.color }} /> {kind.label}
                </DropdownMenuItem>
              )
            })}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
      {creating !== null && (
        <CreateEntityDialog
          vault={vault}
          initialKind={creating.key}
          initialParent={{
            id: entity.data.id,
            name: entity.data.name,
            dimension_id: entity.data.dimension_id,
          }}
          onClose={() => {
            setCreating(null)
          }}
        />
      )}
    </div>
  )
}
