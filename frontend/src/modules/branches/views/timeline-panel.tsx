import { Link } from '@tanstack/react-router'
import { ChevronRightIcon, EyeIcon } from 'lucide-react'
import type { ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import type { EntityViewProps } from '@/core/modules'
import { lineageOf, MomentDisplay, useTimeContext } from '@/core/time'
import { useBranchDiff, useEntity, useTimelines, type DiffRecord, type TimelineNode } from '@/data'

/** How many records of each kind of difference the summary lists. */
const SHOWN = 8

const RECORD_WORDS: Record<string, string> = { event: 'Event', fact: 'Value', link: 'Link' }

function find(nodes: readonly TimelineNode[], id: string): TimelineNode | null {
  for (const node of nodes) {
    if (node.id === id) return node
    const found = find(node.children, id)
    if (found !== null) return found
  }
  return null
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd>{children}</dd>
    </>
  )
}

function DiffList({
  vault,
  title,
  records,
}: {
  vault: string
  title: string
  records: readonly DiffRecord[]
}) {
  if (records.length === 0) return null
  return (
    <section aria-label={title} className="flex flex-col gap-1">
      <h3 className="text-xs font-medium text-muted-foreground uppercase">
        {title} ({records.length})
      </h3>
      <ul className="flex flex-col text-sm">
        {records.slice(0, SHOWN).map((record) => (
          <li key={`${record.record_type}:${record.id}`} className="flex flex-wrap gap-x-2">
            <span className="text-xs text-muted-foreground">
              {RECORD_WORDS[record.record_type] ?? record.record_type}
            </span>
            <Link
              to="/v/$vault/e/$entity"
              params={{ vault, entity: record.entity_id }}
              className="font-medium hover:underline"
            >
              {record.name}
            </Link>
            {record.detail !== null && (
              <span className="text-muted-foreground">{record.detail}</span>
            )}
            {record.after != null && Object.keys(record.after).length > 0 && (
              <span className="text-xs text-muted-foreground">
                changed: {Object.keys(record.after).join(', ')}
              </span>
            )}
          </li>
        ))}
      </ul>
      {records.length > SHOWN && (
        <p className="text-xs text-muted-foreground">and {records.length - SHOWN} more</p>
      )}
    </section>
  )
}

/**
 * A timeline entity's page (docs/modules/branches.md, UI): its lineage, branch point and child
 * branches, and for a branch what it changed against its parent: the records it created, those
 * it overrode and the inherited ones still going at its branch point (the diff). Its premise is
 * the entity's summary.
 */
export function TimelinePanel({ vault, entityId }: EntityViewProps) {
  const entity = useEntity(vault, entityId)
  const dimensionId = entity.data?.dimension_id ?? null
  const tree = useTimelines(vault, dimensionId)
  const time = useTimeContext(vault)
  const nodes = tree.data?.items ?? []
  const node = find(nodes, entityId)
  const lineage = lineageOf(nodes, entityId)
  const isBranch = node !== null && !node.is_prime
  const diff = useBranchDiff(vault, isBranch ? entityId : null)
  if (tree.isPending || entity.isPending) {
    return <p className="text-sm text-muted-foreground">Loading…</p>
  }
  if (node === null || dimensionId === null) {
    return <p className="text-sm text-muted-foreground">Not in its dimension’s timelines.</p>
  }
  const viewed = time.timelineId === entityId
  const children = node.children.filter((child) => !child.trashed)
  const ancestors = [...lineage].reverse()
  return (
    <div className="flex flex-col gap-4 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <nav aria-label="Lineage" className="flex flex-wrap items-center gap-1">
          {ancestors.map((entry, index) => (
            <span key={entry.timeline.id} className="flex items-center gap-1">
              {index > 0 && (
                <ChevronRightIcon aria-hidden className="size-3.5 text-muted-foreground" />
              )}
              {entry.timeline.id === entityId ? (
                <span aria-current="page" className="font-medium">
                  {entry.timeline.name}
                </span>
              ) : (
                <Link
                  to="/v/$vault/e/$entity"
                  params={{ vault, entity: entry.timeline.id }}
                  className="hover:underline"
                >
                  {entry.timeline.name}
                </Link>
              )}
            </span>
          ))}
        </nav>
        <div className="flex-1" />
        {!viewed && time.dimensionId === dimensionId && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              time.setTimeline(entityId)
            }}
          >
            <EyeIcon aria-hidden /> View this timeline
          </Button>
        )}
      </div>
      <dl className="grid grid-cols-[8rem_1fr] gap-x-3 gap-y-2">
        <Row label="Kind">{node.is_prime ? 'Prime timeline' : 'Branch'}</Row>
        {isBranch && (
          <Row label="Branch point">
            {node.branch_t === null ? (
              'Not resolved'
            ) : (
              <MomentDisplay
                vault={vault}
                dimension={dimensionId}
                moment={{ t: node.branch_t, precision: 'base' }}
              />
            )}
          </Row>
        )}
        {isBranch && diff.data !== undefined && (
          <Row label="Differences">
            {diff.data.created.length} created · {diff.data.overridden.length} changed ·{' '}
            {diff.data.inherited_spanning.length} carried over
            {diff.data.truncated && ' (some left out)'}
          </Row>
        )}
        <Row label="Branches">
          {children.length === 0 ? (
            <span className="text-muted-foreground">None</span>
          ) : (
            <ul aria-label="Child branches" className="flex flex-col">
              {children.map((child) => (
                <li key={child.id}>
                  <Link
                    to="/v/$vault/e/$entity"
                    params={{ vault, entity: child.id }}
                    className="hover:underline"
                  >
                    {child.name}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Row>
      </dl>
      {isBranch && diff.data !== undefined && (
        <div className="flex flex-col gap-3">
          <DiffList vault={vault} title="Created in this branch" records={diff.data.created} />
          <DiffList vault={vault} title="Changed in this branch" records={diff.data.overridden} />
          <DiffList
            vault={vault}
            title="Carried over the branch point"
            records={diff.data.inherited_spanning}
          />
        </div>
      )}
    </div>
  )
}
