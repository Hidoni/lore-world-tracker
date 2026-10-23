import { Button } from '@/components/ui/button'
import { useChangesPages, useHistoryPages } from '@/data'
import { cn } from '@/lib/utils'

import { ChangesetList, ORIGIN_LABEL } from './changeset-list'

type Origin =
  | 'ui'
  | 'api'
  | 'cli'
  | 'mcp'
  | 'import'
  | 'migration'
  | 'system'
  | 'undo'
  | 'compaction'
  | 'refinement'
const ORIGINS = Object.keys(ORIGIN_LABEL) as Origin[]

/** An entity's history tab: the changesets touching it, newest first, with diffs and undo. */
export function EntityHistory({ vault, entityId }: { vault: string; entityId: string }) {
  const history = useHistoryPages(vault, entityId)
  const items = history.data?.pages.flatMap((page) => page.items) ?? []
  if (history.isPending) return <p className="text-sm text-muted-foreground">Loading…</p>
  return (
    <div className="flex flex-col gap-3">
      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground">No changes recorded.</p>
      ) : (
        <ChangesetList vault={vault} items={items} entityId={entityId} />
      )}
      {history.hasNextPage && (
        <Button
          variant="outline"
          className="self-center"
          disabled={history.isFetchingNextPage}
          onClick={() => {
            void history.fetchNextPage()
          }}
        >
          Show older changes
        </Button>
      )}
    </div>
  )
}

/** The recent changes page (`/v/$vault/changes`): the vault's changesets, filterable by origin. */
export function ChangesPage({
  vault,
  origins,
  onOriginsChange,
}: {
  vault: string
  origins: readonly string[]
  onOriginsChange: (origins: string[]) => void
}) {
  const chosen = ORIGINS.filter((origin) => origins.includes(origin))
  const changes = useChangesPages(vault, chosen.length > 0 ? { origin: chosen } : {})
  const items = changes.data?.pages.flatMap((page) => page.items) ?? []
  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-4 p-6">
      <h1 className="text-2xl font-semibold">Recent changes</h1>
      <div role="group" aria-label="Origin" className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-muted-foreground">From:</span>
        {ORIGINS.map((origin) => {
          const on = chosen.includes(origin)
          return (
            <button
              key={origin}
              type="button"
              aria-pressed={on}
              className={cn(
                'rounded-full border px-3 py-1',
                on ? 'border-primary bg-primary text-primary-foreground' : 'hover:bg-accent',
              )}
              onClick={() => {
                onOriginsChange(
                  on ? chosen.filter((value) => value !== origin) : [...chosen, origin],
                )
              }}
            >
              {ORIGIN_LABEL[origin]}
            </button>
          )
        })}
        {chosen.length > 0 && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              onOriginsChange([])
            }}
          >
            All
          </Button>
        )}
      </div>
      {changes.isPending && <p className="text-muted-foreground">Loading…</p>}
      {!changes.isPending && items.length === 0 && (
        <p className="text-muted-foreground">
          No changes{chosen.length > 0 ? ' from these origins' : ''}.
        </p>
      )}
      {items.length > 0 && <ChangesetList vault={vault} items={items} />}
      {changes.hasNextPage && (
        <Button
          variant="outline"
          className="self-center"
          disabled={changes.isFetchingNextPage}
          onClick={() => {
            void changes.fetchNextPage()
          }}
        >
          Show older changes
        </Button>
      )}
    </div>
  )
}
