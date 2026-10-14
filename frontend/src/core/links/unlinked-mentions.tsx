import { Link } from '@tanstack/react-router'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { useKindRegistry } from '@/core/registry'
import {
  isRevisionConflict,
  useDataSource,
  useMutations,
  useUnlinkedMentions,
  useUpdateEntity,
  type components,
} from '@/data'

import { linkOccurrences } from './unlinked'

type Source = components['schemas']['UnlinkedSource']
type Found = components['schemas']['UnlinkedOccurrence']

/**
 * Where other entities' text names this entity without linking to it (R-LNK-3): each occurrence
 * in context, with "Link" (marks that occurrence) and "Link all" (every occurrence in that
 * source). Linking edits the source's text at its current revision. Read-only without mutations.
 */
export function UnlinkedMentions({ vault, entityId }: { vault: string; entityId: string }) {
  const unlinked = useUnlinkedMentions(vault, entityId)
  const registry = useKindRegistry(vault)
  const editable = useMutations() !== null
  const source = useDataSource()
  const update = useUpdateEntity(vault)
  const [busy, setBusy] = useState<string | null>(null)
  const items = unlinked.data?.items ?? []
  if (items.length === 0) return null

  const apply = async (item: Source, occurrences: readonly Found[], key: string) => {
    setBusy(key)
    try {
      const entity = await source.entity(vault, item.entity.id)
      const result = linkOccurrences(entity.body, occurrences, entityId)
      if (result.linked > 0) {
        await update.mutateAsync({
          id: entity.id,
          body: {
            body: result.doc as components['schemas']['JsonObject'],
            revision: entity.revision,
          },
        })
      }
      if (result.skipped > 0) {
        toast.warning(`${item.entity.name} changed meanwhile: ${result.skipped} left as is.`)
        await unlinked.refetch()
      }
    } catch (error) {
      toast.error(
        isRevisionConflict(error)
          ? `${item.entity.name} changed meanwhile: try again.`
          : `Couldn’t link: ${error instanceof Error ? error.message : String(error)}`,
      )
      await unlinked.refetch()
    } finally {
      setBusy(null)
    }
  }

  return (
    <section aria-label="Unlinked mentions" className="flex flex-col gap-2">
      <h3 className="font-medium text-foreground">
        Unlinked mentions <span className="text-muted-foreground">({items.length})</span>
      </h3>
      <ul className="flex flex-col gap-3">
        {items.map((item) => {
          const kind = registry?.kind(item.entity.kind)
          const Icon = kind?.icon
          return (
            <li key={item.entity.id} className="flex flex-col gap-1">
              <span className="flex items-center gap-1.5">
                {Icon && (
                  <Icon aria-hidden className="size-4 shrink-0" style={{ color: kind.color }} />
                )}
                <Link
                  to="/v/$vault/e/$entity"
                  params={{ vault, entity: item.entity.id }}
                  className="font-medium text-foreground hover:underline"
                >
                  {item.entity.name}
                </Link>
                {editable && item.occurrences.length > 1 && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="ml-auto h-6 px-2 text-xs"
                    disabled={busy !== null}
                    aria-label={`Link all in ${item.entity.name}`}
                    onClick={() => void apply(item, item.occurrences, item.entity.id)}
                  >
                    Link all
                  </Button>
                )}
              </span>
              <ul className="flex flex-col gap-1 pl-5.5">
                {item.occurrences.map((occurrence) => {
                  const key = `${item.entity.id}:${occurrence.path.join('.')}:${occurrence.offset}`
                  return (
                    <li key={key} className="flex items-start gap-1 text-xs">
                      <span className="min-w-0 flex-1">
                        {occurrence.before.length > 0 && '…'}
                        {occurrence.before}
                        <mark className="rounded-sm bg-yellow-200/60 px-0.5 text-foreground dark:bg-yellow-500/30">
                          {occurrence.text}
                        </mark>
                        {occurrence.after}
                        {occurrence.after.length > 0 && '…'}
                      </span>
                      {editable && (
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-6 px-2 text-xs"
                          disabled={busy !== null}
                          aria-label={`Link “${occurrence.text}” in ${item.entity.name}`}
                          onClick={() => void apply(item, [occurrence], key)}
                        >
                          Link
                        </Button>
                      )}
                    </li>
                  )
                })}
              </ul>
            </li>
          )
        })}
      </ul>
      {unlinked.data?.truncated === true && (
        <p className="text-xs">More sources name it: link these to see the rest.</p>
      )}
    </section>
  )
}
