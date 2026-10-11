import { Link } from '@tanstack/react-router'

import { useKindRegistry } from '@/core/registry'
import { useBacklinks, type components } from '@/data'

type Backlink = components['schemas']['Backlink']

const mentionText = (counts: Backlink['mentions']) => {
  const total = counts.public + counts.spoiler + counts.private
  if (total === 0) return null
  const secret = counts.spoiler + counts.private
  return `mentioned ${total === 1 ? 'once' : `${total} times`}${secret > 0 ? ` (${secret} in hidden text)` : ''}`
}

/**
 * What points at an entity (frontend.md §3, right panel): the entities linking to it (with the
 * links' labels from their side) and those mentioning it in text, with counts.
 */
export function BacklinksPanel({ vault, entityId }: { vault: string; entityId: string }) {
  const backlinks = useBacklinks(vault, entityId)
  const registry = useKindRegistry(vault)
  const items = backlinks.data?.items ?? []
  return (
    <section aria-label="Backlinks" className="flex flex-col gap-2">
      <h2 className="font-medium text-foreground">
        Backlinks
        {items.length > 0 && <span className="ml-1 text-muted-foreground">({items.length})</span>}
      </h2>
      {backlinks.isPending && <p>Loading…</p>}
      {!backlinks.isPending && items.length === 0 && <p>Nothing links here yet.</p>}
      <ul className="flex flex-col gap-2">
        {items.map(({ entity, links, mentions }) => {
          const kind = registry?.kind(entity.kind)
          const Icon = kind?.icon
          const mentioned = mentionText(mentions)
          return (
            <li key={entity.id} className="flex flex-col">
              <span className="flex items-center gap-1.5">
                {Icon && (
                  <Icon aria-hidden className="size-4 shrink-0" style={{ color: kind.color }} />
                )}
                <Link
                  to="/v/$vault/e/$entity"
                  params={{ vault, entity: entity.id }}
                  className="font-medium text-foreground hover:underline"
                >
                  {entity.name}
                </Link>
              </span>
              <span className="pl-5.5 text-xs">
                {[
                  // Labels read from this entity's side ("member of", "participant").
                  ...links.map(
                    ({ label, link }) => `${label}${link.role ? ` (${link.role})` : ''}`,
                  ),
                  ...(mentioned ? [mentioned] : []),
                ].join(' · ')}
              </span>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
