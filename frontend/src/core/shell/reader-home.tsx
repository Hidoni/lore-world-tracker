import { Link } from '@tanstack/react-router'
import { CalendarRangeIcon, GlobeIcon, ListTreeIcon } from 'lucide-react'

import { useKindRegistry } from '@/core/registry'
import { useDimensions, useEntities, useVault } from '@/data'

/**
 * The readers' landing page (`/v/$vault` in reader mode, frontend.md §13): the vault's dimensions
 * with their summary and ways in (timeline, events), what to browse by kind, and the latest
 * updated pages.
 */
export function ReaderHome({ vault }: { vault: string }) {
  const found = useVault(vault)
  const dimensions = useDimensions(vault)
  const registry = useKindRegistry(vault)
  const latest = useEntities(vault, { sort: '-updated', limit: 8 })
  const kinds = (registry?.kinds ?? []).filter((kind) => !kind.capabilities.is_system)
  const items = dimensions.data?.items ?? []
  const updated = (latest.data?.items ?? []).filter(
    (entity) => registry?.kind(entity.kind)?.capabilities.is_system !== true,
  )

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-8 p-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-3xl font-semibold">{found.data?.name ?? 'Vault'}</h1>
        <p className="text-muted-foreground">
          {items.length === 1
            ? 'One world to explore.'
            : `${String(items.length)} worlds to explore.`}{' '}
          Search with Ctrl K, or start from a dimension below.
        </p>
      </header>
      <section aria-labelledby="reader-dimensions" className="flex flex-col gap-3">
        <h2 id="reader-dimensions" className="text-lg font-semibold">
          Dimensions
        </h2>
        {dimensions.isPending ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : items.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nothing has been shared yet.</p>
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2">
            {items.map((dimension) => (
              <li key={dimension.id} className="flex flex-col gap-2 rounded-lg border p-4">
                <Link
                  to="/v/$vault/d/$dimension"
                  params={{ vault, dimension: dimension.id }}
                  className="flex items-center gap-2 text-lg font-medium hover:underline"
                >
                  <GlobeIcon className="size-4 text-muted-foreground" aria-hidden />
                  {dimension.name}
                </Link>
                {dimension.summary && (
                  <p className="text-sm text-muted-foreground">{dimension.summary}</p>
                )}
                <div className="flex flex-wrap gap-3 text-sm">
                  <Link
                    to="/v/$vault/d/$dimension/timeline"
                    params={{ vault, dimension: dimension.id }}
                    className="inline-flex min-h-8 items-center gap-1 underline-offset-2 hover:underline"
                    aria-label={`Timeline of ${dimension.name}`}
                  >
                    <CalendarRangeIcon className="size-4" aria-hidden />
                    Timeline
                  </Link>
                  <Link
                    to="/v/$vault/d/$dimension/events"
                    params={{ vault, dimension: dimension.id }}
                    className="inline-flex min-h-8 items-center gap-1 underline-offset-2 hover:underline"
                    aria-label={`Events of ${dimension.name}`}
                  >
                    <ListTreeIcon className="size-4" aria-hidden />
                    Events
                  </Link>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
      {kinds.length > 0 && (
        <section aria-labelledby="reader-browse" className="flex flex-col gap-3">
          <h2 id="reader-browse" className="text-lg font-semibold">
            Browse
          </h2>
          <ul className="flex flex-wrap gap-2">
            {kinds.map((kind) => {
              const Icon = kind.icon
              return (
                <li key={kind.key}>
                  <Link
                    to="/v/$vault/k/$kind"
                    params={{ vault, kind: kind.key }}
                    className="inline-flex min-h-9 items-center gap-1.5 rounded-full border px-3 text-sm hover:bg-accent"
                  >
                    <Icon className="size-4" style={{ color: kind.color }} aria-hidden />
                    {kind.plural}
                  </Link>
                </li>
              )
            })}
          </ul>
        </section>
      )}
      {updated.length > 0 && (
        <section aria-labelledby="reader-latest" className="flex flex-col gap-3">
          <h2 id="reader-latest" className="text-lg font-semibold">
            Recently updated
          </h2>
          <ul className="grid gap-2 sm:grid-cols-2">
            {updated.map((entity) => {
              const kind = registry?.kind(entity.kind)
              const Icon = kind?.icon
              return (
                <li key={entity.id}>
                  <Link
                    to="/v/$vault/e/$entity"
                    params={{ vault, entity: entity.id }}
                    className="flex min-h-11 items-center gap-2 rounded-md border px-3 py-2 hover:bg-accent"
                  >
                    {Icon && (
                      <Icon className="size-4 shrink-0" style={{ color: kind.color }} aria-hidden />
                    )}
                    <span className="truncate font-medium">{entity.name}</span>
                    <span className="ml-auto text-xs text-muted-foreground">{kind?.label}</span>
                  </Link>
                </li>
              )
            })}
          </ul>
        </section>
      )}
    </div>
  )
}
