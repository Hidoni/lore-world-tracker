import { Link } from '@tanstack/react-router'
import { GlobeIcon, PinIcon, PlusIcon } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { usePlaceList } from '@/core/navigation/places'
import { DimensionWizard } from '@/core/time'
import { useDimensions, useMutations, useVault } from '@/data'

/**
 * The vault home (`/v/$vault`, frontend.md §4): the vault's dimensions, with "Create dimension"
 * (a call to action when there are none yet), and the pinned entities.
 */
export function VaultHome({ vault }: { vault: string }) {
  const found = useVault(vault)
  const dimensions = useDimensions(vault)
  const pinned = usePlaceList('pinned', vault)
  const editable = useMutations() !== null
  const [creating, setCreating] = useState(false)
  const items = dimensions.data?.items ?? []
  const create = () => {
    setCreating(true)
  }

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6 p-6">
      <h1 className="text-2xl font-semibold">{found.data?.name ?? 'Vault'}</h1>
      <section aria-labelledby="home-dimensions" className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <h2 id="home-dimensions" className="text-lg font-semibold">
            Dimensions
          </h2>
          <div className="flex-1" />
          {editable && items.length > 0 && (
            <Button variant="outline" size="sm" onClick={create}>
              <PlusIcon aria-hidden />
              Create dimension
            </Button>
          )}
        </div>
        {dimensions.isPending ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : items.length === 0 ? (
          <div className="flex flex-col items-start gap-3 rounded-lg border border-dashed p-6">
            <p className="text-sm text-muted-foreground">
              A dimension is a universe with its own flow of time: from its inception to its end,
              counted in a base unit and read through calendars. Everything else lives in one.
            </p>
            {editable && (
              <Button onClick={create}>
                <PlusIcon aria-hidden />
                Create dimension
              </Button>
            )}
          </div>
        ) : (
          <ul className="grid gap-2 sm:grid-cols-2">
            {items.map((dimension) => (
              <li key={dimension.id}>
                <Link
                  to="/v/$vault/d/$dimension"
                  params={{ vault, dimension: dimension.id }}
                  className="flex items-center gap-2 rounded-lg border p-3 hover:bg-accent"
                >
                  <GlobeIcon className="size-4 text-muted-foreground" aria-hidden />
                  <span className="font-medium">{dimension.name}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
      {pinned.length > 0 && (
        <section aria-labelledby="home-pinned" className="flex flex-col gap-2">
          <h2 id="home-pinned" className="text-lg font-semibold">
            Pinned
          </h2>
          <ul className="flex flex-col gap-1 text-sm">
            {pinned.map((place) => (
              <li key={place.id} className="flex items-center gap-2">
                <PinIcon className="size-3 text-muted-foreground" aria-hidden />
                <Link
                  to="/v/$vault/e/$entity"
                  params={{ vault, entity: place.id }}
                  className="underline-offset-2 hover:underline"
                >
                  {place.name}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
      <p className="text-sm">
        <Link to="/v/$vault/changes" params={{ vault }} className="underline">
          Recent changes
        </Link>
      </p>
      {creating && (
        <DimensionWizard
          vault={vault}
          onClose={() => {
            setCreating(false)
          }}
        />
      )}
    </div>
  )
}
