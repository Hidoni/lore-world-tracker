import { Link } from '@tanstack/react-router'
import { ChevronRightIcon, Undo2Icon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useKindRegistry } from '@/core/registry'
import {
  ApiError,
  useChangeset,
  useLinkTypes,
  useMutations,
  useRevertChange,
  type components,
} from '@/data'
import { cn } from '@/lib/utils'

import { describeChanges } from './describe'

type Summary = components['schemas']['ChangesetSummary']

export const ORIGIN_LABEL: Record<string, string> = {
  ui: 'App',
  api: 'API',
  cli: 'CLI',
  import: 'Import',
  migration: 'Migration',
  system: 'System',
  undo: 'Undo',
  compaction: 'Compacted',
}

/** What an undo refused, in words (`409 revert_conflict`: changed rows or broken rules). */
export function revertProblem(error: unknown): { message: string; details: string[] } {
  if (!(error instanceof ApiError)) {
    return { message: error instanceof Error ? error.message : 'The undo failed.', details: [] }
  }
  const problems = (error.context.problems as { message?: string }[] | undefined) ?? []
  const rows = (error.context.rows as { table_name?: string; op?: string }[] | undefined) ?? []
  if (error.code !== 'revert_conflict') return { message: error.detail, details: [] }
  return {
    message:
      rows.length > 0
        ? 'This change can’t be undone: what it changed was changed again since. Undo the later changes first.'
        : 'Undoing this would break the vault’s rules:',
    details: problems.map((problem) => problem.message ?? '').filter(Boolean),
  }
}

/**
 * Changesets with their summary, time, origin and entities; opening one shows its readable diff
 * (`describeChanges`), and authors can undo it (frontend.md §7, data-model.md §7).
 */
export function ChangesetList({
  vault,
  items,
  entityId,
}: {
  vault: string
  items: readonly Summary[]
  /** On an entity's history: link lines name the other end, and entities aren't listed. */
  entityId?: string
}) {
  return (
    <ol aria-label="Changes" className="flex flex-col divide-y rounded-md border">
      {items.map((item) => (
        <ChangesetRow key={item.id} vault={vault} item={item} entityId={entityId} />
      ))}
    </ol>
  )
}

function ChangesetRow({
  vault,
  item,
  entityId,
}: {
  vault: string
  item: Summary
  entityId: string | undefined
}) {
  const [open, setOpen] = useState(false)
  const editable = useMutations() !== null
  const revert = useRevertChange(vault)
  const undone = item.reverted_by_changeset_id !== null
  // compacted history (snapshots of old changes, data-model.md §7) can't be undone
  const undoable = !undone && item.origin !== 'compaction'
  const when = new Date(item.updated_at).toLocaleString()
  const problem = revert.isError ? revertProblem(revert.error) : null
  return (
    <li className="flex flex-col gap-2 p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          aria-expanded={open}
          aria-label={`${open ? 'Hide' : 'Show'} the changes of “${item.summary}”`}
          className="rounded p-0.5 text-muted-foreground hover:text-foreground"
          onClick={() => {
            setOpen(!open)
          }}
        >
          <ChevronRightIcon className={cn('size-4 transition-transform', open && 'rotate-90')} />
        </button>
        <span className={cn('font-medium', undone && 'text-muted-foreground line-through')}>
          {item.summary}
        </span>
        <Badge variant="outline">{ORIGIN_LABEL[item.origin] ?? item.origin}</Badge>
        {item.reverts_changeset_id !== null && <Badge variant="secondary">Undo</Badge>}
        {undone && <Badge variant="secondary">Undone</Badge>}
        <time dateTime={item.updated_at} className="text-xs text-muted-foreground">
          {when}
        </time>
        {editable && undoable && (
          <Button
            variant="ghost"
            size="sm"
            className="ml-auto"
            disabled={revert.isPending}
            aria-label={`Undo “${item.summary}”`}
            onClick={() => {
              revert.mutate(item.id, {
                onSuccess: (result) => {
                  toast.success(`Undone: ${item.summary}`, {
                    description: result.changeset.summary,
                  })
                },
              })
            }}
          >
            <Undo2Icon /> Undo
          </Button>
        )}
      </div>
      {entityId === undefined && item.entities.length > 0 && (
        <p className="pl-7 text-xs text-muted-foreground">
          {item.entities.map((entity, index) => (
            <span key={entity.id}>
              {index > 0 && ', '}
              {entity.exists ? (
                <Link
                  to="/v/$vault/e/$entity"
                  params={{ vault, entity: entity.id }}
                  className="hover:underline"
                >
                  {entity.name ?? 'Unnamed'}
                </Link>
              ) : (
                <span>{entity.name ?? 'Deleted'} (deleted)</span>
              )}
            </span>
          ))}
        </p>
      )}
      {problem && (
        <div
          role="alert"
          className="ml-7 rounded-md border border-destructive/40 bg-destructive/5 p-2"
        >
          <p>{problem.message}</p>
          {problem.details.length > 0 && (
            <ul className="mt-1 list-disc pl-5">
              {problem.details.map((detail) => (
                <li key={detail}>{detail}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      {open && <ChangesetDiff vault={vault} item={item} entityId={entityId} />}
    </li>
  )
}

function ChangesetDiff({
  vault,
  item,
  entityId,
}: {
  vault: string
  item: Summary
  entityId: string | undefined
}) {
  const detail = useChangeset(vault, item.id)
  const registry = useKindRegistry(vault)
  const linkTypes = useLinkTypes(vault)
  if (detail.isPending) return <p className="pl-7 text-muted-foreground">Loading…</p>
  if (detail.isError) return <p className="pl-7 text-destructive">The changes couldn’t load.</p>
  const names = new Map(item.entities.map((entity) => [entity.id, entity.name ?? 'Unnamed']))
  const lines = describeChanges(detail.data.changes, {
    registry,
    names,
    linkTypes: new Map((linkTypes.data?.items ?? []).map((type) => [type.key, type.label])),
    ...(entityId === undefined ? {} : { entityId }),
  })
  return (
    <ul aria-label={`Changes of “${item.summary}”`} className="flex flex-col gap-1 pl-7">
      {lines.map((line, index) => (
        <li key={index} className="flex flex-wrap items-baseline gap-x-2">
          <span>{line.label}</span>
          {line.before !== undefined && (
            <span className="text-muted-foreground">
              <del className="decoration-destructive/60">{line.before}</del>
              {' → '}
              <ins className="text-foreground no-underline">{line.after}</ins>
            </span>
          )}
        </li>
      ))}
      {lines.length === 0 && <li className="text-muted-foreground">No visible changes.</li>}
    </ul>
  )
}
