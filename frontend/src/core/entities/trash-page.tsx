import { Link } from '@tanstack/react-router'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { forget } from '@/core/navigation/places'
import { useKindRegistry } from '@/core/registry'
import {
  useDeleteEntity,
  useMutations,
  useRestoreEntity,
  useTrashList,
  type components,
} from '@/data'

import { PurgeDialog } from './trash-dialogs'

type TrashItem = components['schemas']['TrashItem']

/**
 * The trash (frontend.md §4): trashed entities, most recent first, with restore and permanent
 * deletion. Children left behind are shown as roots meanwhile (`orphan_count`).
 */
export function TrashPage({ vault }: { vault: string }) {
  const trash = useTrashList(vault)
  const items = trash.data?.pages.flatMap((page) => page.items) ?? []
  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-4 p-6">
      <header>
        <h1 className="text-2xl font-semibold">Trash</h1>
        <p className="text-sm text-muted-foreground">
          Restore entities, or delete them permanently with their links.
        </p>
      </header>
      {trash.isPending && <p className="text-muted-foreground">Loading…</p>}
      {!trash.isPending && items.length === 0 && (
        <p className="text-muted-foreground">The trash is empty.</p>
      )}
      {items.length > 0 && (
        <ul aria-label="Trashed entities" className="flex flex-col divide-y rounded-md border">
          {items.map((item) => (
            <TrashRow key={item.id} vault={vault} item={item} />
          ))}
        </ul>
      )}
      {trash.hasNextPage && (
        <Button
          variant="outline"
          className="self-center"
          disabled={trash.isFetchingNextPage}
          onClick={() => {
            void trash.fetchNextPage()
          }}
        >
          Show more
        </Button>
      )}
    </div>
  )
}

function TrashRow({ vault, item }: { vault: string; item: TrashItem }) {
  const editable = useMutations() !== null
  const registry = useKindRegistry(vault)
  const kind = registry?.kind(item.kind)
  const restore = useRestoreEntity(vault)
  const purge = useDeleteEntity(vault)
  const [purging, setPurging] = useState(false)
  const Icon = kind?.icon
  const when = item.deleted_at ? new Date(item.deleted_at).toLocaleString() : ''
  return (
    <li className="flex flex-wrap items-center gap-3 p-3">
      {Icon && <Icon aria-hidden className="size-5 shrink-0" style={{ color: kind.color }} />}
      <div className="flex min-w-0 flex-1 flex-col">
        <Link
          to="/v/$vault/e/$entity"
          params={{ vault, entity: item.id }}
          className="truncate font-medium hover:underline"
        >
          {item.name}
        </Link>
        <span className="text-xs text-muted-foreground">
          {kind?.label ?? item.kind} · trashed {when}
          {item.orphan_count > 0 &&
            ` · ${item.orphan_count} ${item.orphan_count === 1 ? 'child stays' : 'children stay'} outside the trash`}
        </span>
      </div>
      {editable && (
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={restore.isPending}
            aria-label={`Restore ${item.name}`}
            onClick={() => {
              restore.mutate(item.id, {
                onSuccess: () => {
                  toast.success(`Restored ${item.name}`)
                },
              })
            }}
          >
            Restore
          </Button>
          <Button
            size="sm"
            variant="destructive"
            aria-label={`Delete ${item.name} permanently`}
            onClick={() => {
              setPurging(true)
            }}
          >
            Delete permanently
          </Button>
        </div>
      )}
      {purging && (
        <PurgeDialog
          name={item.name}
          busy={purge.isPending}
          onClose={() => {
            setPurging(false)
          }}
          onConfirm={() => {
            purge.mutate(
              { id: item.id, purge: true },
              {
                onSuccess: () => {
                  setPurging(false)
                  forget(vault, item.id)
                },
              },
            )
          }}
        />
      )}
    </li>
  )
}
