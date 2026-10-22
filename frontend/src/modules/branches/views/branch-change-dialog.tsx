import { Link } from '@tanstack/react-router'
import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { MomentDisplay } from '@/core/time'
import {
  ApiError,
  useApplyBranchProposal,
  useProposeBranchChange,
  type BranchProposal,
  type BranchRecord,
  type BranchStrategy,
  type TimelineNode,
} from '@/data'

export type BranchChange = 'reparent' | 'merge'

const RECORD_WORDS: Record<string, string> = {
  event: 'Event',
  fact: 'Value',
  link: 'Link',
  segment: 'Worldline',
}

const ACTION_WORDS: Record<string, string> = {
  move: 'Moves to the parent',
  replace: 'Replaces the parent’s change',
  apply: 'Changes the parent’s record',
  rehome: 'Becomes the parent’s change',
  drop: 'Dropped: the branch no longer has the record',
}

const STRATEGY_WORDS: Record<BranchStrategy, string> = {
  keep: 'Keep',
  discard: 'Discard',
}

/** The timelines of a tree, depth first, with their depth (for indenting the choice). */
function flatten(nodes: readonly TimelineNode[], depth = 0): [TimelineNode, number][] {
  return nodes.flatMap((node) => [
    [node, depth] as [TimelineNode, number],
    ...flatten(node.children, depth + 1),
  ])
}

function subtree(node: TimelineNode): Set<string> {
  return new Set(flatten([node]).map(([found]) => found.id))
}

function problemOf(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.detail
  return fallback
}

function RecordName({ vault, record }: { vault: string; record: BranchRecord }) {
  const word = RECORD_WORDS[record.record_type] ?? record.record_type
  return (
    <span className="flex flex-wrap items-baseline gap-x-2">
      <span className="text-xs text-muted-foreground">
        {word}
        {record.override ? ' change' : ''}
      </span>
      {record.entity_id === null ? (
        <span>{record.name ?? 'Unnamed'}</span>
      ) : (
        <Link
          to="/v/$vault/e/$entity"
          params={{ vault, entity: record.entity_id }}
          className="font-medium underline-offset-2 hover:underline"
        >
          {record.name ?? 'Unnamed'}
        </Link>
      )}
    </span>
  )
}

function Starts({
  vault,
  dimension,
  record,
}: {
  vault: string
  dimension: string
  record: BranchRecord
}) {
  if (record.start_t === null) return <span className="text-muted-foreground">Always</span>
  return (
    <MomentDisplay
      vault={vault}
      dimension={dimension}
      moment={{ t: record.start_t, precision: 'base' }}
    />
  )
}

function Preview({
  vault,
  dimension,
  proposal,
  strategies,
  onStrategy,
}: {
  vault: string
  dimension: string
  proposal: BranchProposal
  strategies: Record<string, BranchStrategy>
  onStrategy: (key: string, strategy: BranchStrategy) => void
}) {
  const { summary } = proposal
  const shown = (items: { name: string | null }[]) =>
    items.map((item) => item.name ?? 'Unnamed').join(', ')
  return (
    <div className="flex flex-col gap-3 text-sm">
      {proposal.records.length > 0 && (
        <section aria-label="Records of the branch" className="flex flex-col gap-1">
          <h3 className="text-xs font-medium text-muted-foreground uppercase">
            {proposal.operation === 'merge' ? 'Merged into the parent' : 'Changes'} (
            {summary.records})
          </h3>
          <ul className="flex flex-col gap-0.5">
            {proposal.records.map((record) => (
              <li key={record.id} className="flex flex-wrap items-baseline justify-between gap-x-3">
                <RecordName vault={vault} record={record} />
                <span className="text-xs text-muted-foreground">
                  {ACTION_WORDS[record.action ?? ''] ?? record.action}
                </span>
              </li>
            ))}
          </ul>
          {summary.records > proposal.records.length && (
            <p className="text-xs text-muted-foreground">
              and {summary.records - proposal.records.length} more
            </p>
          )}
        </section>
      )}
      {proposal.conflicts.length > 0 && (
        <table aria-label="The parent’s records after the branch point" className="w-full">
          <caption className="pb-1 text-left text-xs text-muted-foreground">
            The parent’s own records from the branch point on, which the branch never had. Keep them
            next to the merged ones, or discard them (to the trash).
          </caption>
          <thead>
            <tr className="text-left text-xs text-muted-foreground">
              <th className="py-1 pr-2 font-normal">Record</th>
              <th className="py-1 pr-2 font-normal">Starts</th>
              <th className="py-1 font-normal">Choice</th>
            </tr>
          </thead>
          <tbody>
            {proposal.conflicts.map((record) => {
              const key = record.key ?? record.id
              const choices = (record.strategies ?? ['keep']) as BranchStrategy[]
              return (
                <tr key={key} aria-label={record.name ?? key} className="border-t align-top">
                  <td className="py-1 pr-2">
                    <RecordName vault={vault} record={record} />
                  </td>
                  <td className="py-1 pr-2">
                    <Starts vault={vault} dimension={dimension} record={record} />
                  </td>
                  <td className="py-1">
                    {choices.length === 1 ? (
                      <span className="text-muted-foreground">Kept</span>
                    ) : (
                      <select
                        aria-label={`Choice for ${record.name ?? key}`}
                        className="h-8 rounded-md border border-input bg-transparent px-2 text-sm"
                        value={strategies[key] ?? 'keep'}
                        onChange={(event) => {
                          onStrategy(key, event.target.value as BranchStrategy)
                        }}
                      >
                        {choices.map((strategy) => (
                          <option key={strategy} value={strategy}>
                            {STRATEGY_WORDS[strategy]}
                          </option>
                        ))}
                      </select>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
      <ul className="flex flex-col gap-1 text-muted-foreground">
        {proposal.timelines.length > 0 && proposal.operation === 'merge' && (
          <li>Its branches move to the parent: {shown(proposal.timelines)}.</li>
        )}
        {proposal.pinned.length > 0 && (
          <li>
            Branch points kept at their moment (their anchors would no longer be in their parent):{' '}
            {shown(proposal.pinned)}.
          </li>
        )}
        {proposal.siblings.length > 0 && (
          <li>
            The parent’s later branches will inherit merged records from before their branch point:{' '}
            {shown(proposal.siblings)}.
          </li>
        )}
        {summary.notes_moved > 0 && (
          <li>
            {summary.notes_moved} {summary.notes_moved === 1 ? 'note moves' : 'notes move'} to the
            parent.
          </li>
        )}
        {summary.notes_kept > 0 && (
          <li>
            {summary.notes_kept} {summary.notes_kept === 1 ? 'note stays' : 'notes stay'} with the
            branch in the trash.
          </li>
        )}
        {summary.hidden_references > 0 && (
          <li>
            {summary.hidden_references}{' '}
            {summary.hidden_references === 1 ? 'date of the branch is' : 'dates of the branch are'}{' '}
            anchored to records it will no longer have.
          </li>
        )}
        {proposal.operation === 'merge' && <li>The emptied branch goes to the trash.</li>}
      </ul>
    </div>
  )
}

/**
 * Moving a branch under another timeline, or merging it into its parent (time-model.md §4.7,
 * ADR-0019): the impact preview (the branch's records and what happens to each, the parent's
 * own records after the branch point with a keep/discard choice, branches and branch points that
 * move), then one undoable apply. Re-parenting first asks for the new parent. A stale or expired
 * preview can be run again.
 */
export function BranchChangeDialog({
  vault,
  dimension,
  timeline,
  parentId,
  nodes,
  change,
  onDone,
  onClose,
}: {
  vault: string
  dimension: string
  timeline: TimelineNode
  parentId: string
  /** The dimension's timeline tree. */
  nodes: readonly TimelineNode[]
  change: BranchChange
  /** Applied: the operation and the parent the branch moved under or merged into. */
  onDone: (change: BranchChange, parentId: string) => void
  onClose: () => void
}) {
  const propose = useProposeBranchChange(vault)
  const apply = useApplyBranchProposal(vault)
  const [proposal, setProposal] = useState<BranchProposal | null>(null)
  const [strategies, setStrategies] = useState<Record<string, BranchStrategy>>({})
  const [stale, setStale] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const excluded = subtree(timeline)
  const parents = flatten(nodes).filter(
    ([node]) => !node.trashed && !excluded.has(node.id) && node.id !== parentId,
  )
  const [target, setTarget] = useState<string>(parents[0]?.[0].id ?? '')

  const request = (parent: string | null) => {
    propose.mutate(
      {
        timeline: timeline.id,
        body:
          change === 'merge'
            ? { operation: 'merge' }
            : { operation: 'reparent', parent_timeline_id: parent },
      },
      {
        onSuccess: (found) => {
          setProposal(found)
          setStrategies({})
        },
        onError: (error) => {
          setProposal(null)
          setMessage(problemOf(error, 'The change couldn’t be previewed.'))
        },
      },
    )
  }

  const preview = (parent: string | null) => {
    setMessage(null)
    setStale(false)
    request(parent)
  }

  // A merge has nothing to ask first: preview it right away.
  useEffect(() => {
    if (change === 'merge') request(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once, when the dialog opens
  }, [])

  // Awaited rather than a mutate callback: the page may unmount as the branch goes to the trash.
  const run = async () => {
    if (proposal === null) return
    try {
      await apply.mutateAsync({
        timeline: timeline.id,
        proposal: proposal.id,
        body: { strategies },
      })
    } catch (error) {
      const expired =
        error instanceof ApiError && (error.status === 404 || error.code === 'proposal_stale')
      setStale(expired)
      setMessage(expired ? null : problemOf(error, 'The change couldn’t be applied.'))
      return
    }
    onDone(change, proposal.parent_timeline_id)
  }

  const title =
    change === 'merge' ? `Merge “${timeline.name}” into its parent` : `Move “${timeline.name}”`
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent className="max-h-[90svh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            {change === 'merge'
              ? 'The parent takes over everything the branch holds: its records, its changes to inherited records and its branches.'
              : 'The branch and its own branches move under another timeline, keeping their branch point. It then inherits that timeline’s past.'}
          </DialogDescription>
        </DialogHeader>
        {change === 'reparent' && (
          <div className="flex flex-wrap items-end gap-2">
            <div className="flex flex-col gap-1">
              <Label htmlFor="branch-new-parent">New parent</Label>
              <select
                id="branch-new-parent"
                className="h-8 rounded-md border border-input bg-transparent px-2 text-sm"
                value={target}
                onChange={(event) => {
                  setTarget(event.target.value)
                  setProposal(null)
                }}
              >
                {parents.map(([node, depth]) => (
                  <option key={node.id} value={node.id}>
                    {'  '.repeat(depth)}
                    {node.name}
                  </option>
                ))}
              </select>
            </div>
            <Button
              variant="outline"
              disabled={target === '' || propose.isPending}
              onClick={() => {
                preview(target)
              }}
            >
              {propose.isPending ? 'Previewing…' : 'Preview'}
            </Button>
            {parents.length === 0 && (
              <p className="text-sm text-muted-foreground">
                There is no other timeline to move to.
              </p>
            )}
          </div>
        )}
        {propose.isPending && change === 'merge' && (
          <p className="text-sm text-muted-foreground">Previewing…</p>
        )}
        {stale && (
          <div role="alert" className="flex flex-col items-start gap-2 text-sm">
            <p>
              The timelines changed since this preview (or it expired). Preview the change again.
            </p>
            <Button
              onClick={() => {
                preview(change === 'merge' ? null : target)
              }}
            >
              Preview again
            </Button>
          </div>
        )}
        {proposal !== null && !stale && (
          <Preview
            vault={vault}
            dimension={dimension}
            proposal={proposal}
            strategies={strategies}
            onStrategy={(key, strategy) => {
              setStrategies((current) => ({ ...current, [key]: strategy }))
            }}
          />
        )}
        {message !== null && (
          <p role="alert" className="text-sm text-destructive">
            {message}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            disabled={proposal === null || stale || apply.isPending}
            onClick={() => {
              void run()
            }}
          >
            {apply.isPending ? 'Applying…' : change === 'merge' ? 'Merge' : 'Move'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
