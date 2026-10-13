import { Link } from '@tanstack/react-router'
import { MapPinIcon, XIcon } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import type { EntityViewProps } from '@/core/modules'
import {
  useCreateLink,
  useDeleteLink,
  useEntities,
  useEntity,
  useLinks,
  useMutations,
} from '@/data'

import { EVENT_SITE, LOCATION } from '../types'

/**
 * The event's "Location" quick field: where it took place (`locations.event_site`). Choosing a
 * location replaces the current site; the relations panel edits several sites.
 */
export function EventSitePanel({ vault, entityId }: EntityViewProps) {
  const entity = useEntity(vault, entityId)
  const links = useLinks(vault, entityId, { type: [EVENT_SITE], direction: 'out' })
  const editable = useMutations() !== null && entity.data?.deleted_at === null
  const [query, setQuery] = useState('')
  const [choosing, setChoosing] = useState(false)
  const sites = links.data?.items ?? []

  return (
    <div className="flex flex-col gap-2">
      {sites.length === 0 && !choosing && (
        <p className="text-sm text-muted-foreground">Where it took place isn’t set.</p>
      )}
      {sites.length > 0 && (
        <ul aria-label="Sites" className="flex flex-col gap-1">
          {sites.map(({ link, other }) => (
            <li key={link.id} className="flex items-center gap-1.5 text-sm">
              <MapPinIcon aria-hidden className="size-3.5 shrink-0 text-muted-foreground" />
              <Link
                to="/v/$vault/e/$entity"
                params={{ vault, entity: other.id }}
                className="flex-1 truncate text-primary underline-offset-2 hover:underline"
              >
                {other.name}
              </Link>
              {editable && <RemoveSite vault={vault} linkId={link.id} name={other.name} />}
            </li>
          ))}
        </ul>
      )}
      {editable &&
        (choosing ? (
          <SitePicker
            vault={vault}
            eventId={entityId}
            dimension={entity.data?.dimension_id ?? null}
            replace={sites.map(({ link }) => link.id)}
            query={query}
            onQuery={setQuery}
            onDone={() => {
              setChoosing(false)
              setQuery('')
            }}
          />
        ) : (
          <Button
            variant="outline"
            size="sm"
            className="self-start"
            onClick={() => {
              setChoosing(true)
            }}
          >
            {sites.length === 0 ? 'Set location' : 'Change location'}
          </Button>
        ))}
    </div>
  )
}

function RemoveSite({ vault, linkId, name }: { vault: string; linkId: string; name: string }) {
  const remove = useDeleteLink(vault)
  return (
    <Button
      variant="ghost"
      size="icon"
      className="size-6"
      aria-label={`Remove ${name}`}
      disabled={remove.isPending}
      onClick={() => {
        remove.mutate(linkId)
      }}
    >
      <XIcon className="size-3.5" />
    </Button>
  )
}

function SitePicker({
  vault,
  eventId,
  dimension,
  replace,
  query,
  onQuery,
  onDone,
}: {
  vault: string
  eventId: string
  dimension: string | null
  /** The current site links, removed once the new one exists. */
  replace: readonly string[]
  query: string
  onQuery: (query: string) => void
  onDone: () => void
}) {
  const q = query.trim()
  const found = useEntities(vault, {
    kind: [LOCATION],
    limit: 8,
    ...(q === '' ? {} : { q }),
    ...(dimension === null ? {} : { dimension }),
  })
  const create = useCreateLink(vault)
  const remove = useDeleteLink(vault)
  const choose = (target: string) => {
    create.mutate(
      { link_type: EVENT_SITE, source_id: eventId, target_id: target },
      {
        onSuccess: () => {
          void Promise.all(replace.map((id) => remove.mutateAsync(id))).then(onDone)
        },
      },
    )
  }
  return (
    <div className="flex flex-col gap-1">
      <Input
        aria-label="Find a location"
        placeholder="Find a location…"
        autoComplete="off"
        value={query}
        onChange={(event) => {
          onQuery(event.target.value)
        }}
        onKeyDown={(event) => {
          if (event.key === 'Escape') onDone()
        }}
      />
      <ul aria-label="Locations" className="flex max-h-48 flex-col overflow-y-auto text-sm">
        {found.data?.items.length === 0 && (
          <li className="px-2 py-1 text-muted-foreground">No matching locations</li>
        )}
        {found.data?.items.map((location) => (
          <li key={location.id}>
            <button
              type="button"
              disabled={create.isPending}
              className="w-full truncate rounded-sm px-2 py-1 text-left hover:bg-accent"
              onClick={() => {
                choose(location.id)
              }}
            >
              {location.name}
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
