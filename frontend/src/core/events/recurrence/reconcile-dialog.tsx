import { Link } from '@tanstack/react-router'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { formatIn, type DimensionTime, type Lens } from '@/core/time'
import type { components, RecurrenceProposal } from '@/data'

type Strategy = components['schemas']['RecurrenceStrategy']
type Item = RecurrenceProposal['items'][number]

const STATUS: Record<Item['status'], string> = {
  unchanged: 'Unchanged',
  moved: 'Moves',
  orphaned: 'No longer an occurrence',
}

const STRATEGY: Record<Strategy, string> = {
  keep_key: 'Move with the rule',
  rekey: 'Stay at its date (re-key)',
  detach: 'Detach (a standalone event)',
  trash: 'Move to the trash',
}

/**
 * The reconciliation preview of a rule change (recurrence.md §8, R-REC-6): each materialized
 * occurrence with its status (unchanged, moved, orphaned), its start before and after, and a
 * strategy (keep the key, re-key onto the occurrence at its original date, detach, trash),
 * defaulting to the server's. Re-keying onto a key another occurrence holds is flagged before
 * applying; a stale proposal can be previewed again.
 */
export function ReconcileDialog({
  vault,
  proposal,
  dimension,
  lens,
  lenses,
  precision,
  applying,
  stale,
  message,
  onApply,
  onRerun,
  onClose,
}: {
  vault: string
  proposal: RecurrenceProposal
  dimension: DimensionTime
  lens: Lens | null
  lenses: readonly Lens[]
  /** The series start's precision: occurrences are shown at it. */
  precision: string
  applying: boolean
  stale: boolean
  message: string | null
  onApply: (strategies: Record<string, Strategy>) => void
  onRerun: () => void
  onClose: () => void
}) {
  const [strategies, setStrategies] = useState<Record<string, Strategy>>(() =>
    Object.fromEntries(
      proposal.items.flatMap((item) =>
        item.default_strategy === null ? [] : [[item.entity_id, item.default_strategy]],
      ),
    ),
  )
  const shown = (t: bigint | null) =>
    t === null || lens === null
      ? '—'
      : (formatIn(lens, { t, precision }, dimension, lenses) ?? t.toString())
  // Two occurrences ending on one key: one re-keyed onto a key another holds, unless that one
  // leaves it (re-keyed or detached; one in the trash still holds its key, recurrence.md §8).
  const conflicts = new Set(
    proposal.items.flatMap((item) => {
      if (strategies[item.entity_id] !== 'rekey' || item.rekey_held_by === null) return []
      const holder = strategies[item.rekey_held_by]
      return holder === 'detach' || holder === 'rekey' ? [] : [item.entity_id]
    }),
  )
  const { summary } = proposal
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent showCloseButton={false} className="max-h-[90svh] overflow-y-auto sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle>Review the occurrences</DialogTitle>
          <DialogDescription>
            {summary.moved} customized{' '}
            {summary.moved === 1 ? 'occurrence moves' : 'occurrences move'}, {summary.orphaned}{' '}
            {summary.orphaned === 1 ? 'is' : 'are'} no longer an occurrence and {summary.unchanged}{' '}
            {summary.unchanged === 1 ? 'stays' : 'stay'} as{' '}
            {summary.unchanged === 1 ? 'it is' : 'they are'}.
          </DialogDescription>
        </DialogHeader>
        {stale ? (
          <div role="alert" className="flex flex-col items-start gap-2 text-sm">
            <p>The series changed since this preview (or it expired). Preview the change again.</p>
            <Button onClick={onRerun}>Preview again</Button>
          </div>
        ) : (
          <table aria-label="Customized occurrences" className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-foreground">
                <th className="py-1 pr-2 font-normal">Occurrence</th>
                <th className="py-1 pr-2 font-normal">Status</th>
                <th className="py-1 pr-2 font-normal">Was</th>
                <th className="py-1 pr-2 font-normal">After</th>
                <th className="py-1 font-normal">Choice</th>
              </tr>
            </thead>
            <tbody>
              {proposal.items.map((item) => {
                const choice = strategies[item.entity_id] ?? null
                const after =
                  choice === 'rekey'
                    ? item.rekey_start_t
                    : choice === 'keep_key'
                      ? item.new_start_t
                      : item.start_t
                return (
                  <tr key={item.entity_id} aria-label={item.name} className="border-t align-top">
                    <td className="py-1 pr-2">
                      <Link
                        to="/v/$vault/e/$entity"
                        params={{ vault, entity: item.entity_id }}
                        className="underline-offset-2 hover:underline"
                      >
                        {item.name}
                      </Link>
                    </td>
                    <td className="py-1 pr-2">{STATUS[item.status]}</td>
                    <td className="py-1 pr-2">{shown(item.original_start_t)}</td>
                    <td className="py-1 pr-2">
                      {choice === 'trash' ? 'In the trash' : shown(after)}
                      {conflicts.has(item.entity_id) && (
                        <p role="alert" className="text-xs text-destructive">
                          Another customized occurrence holds that date: choose something else for
                          one of them.
                        </p>
                      )}
                    </td>
                    <td className="py-1">
                      {item.strategies.length === 0 ? (
                        <span className="text-muted-foreground">Nothing to do</span>
                      ) : (
                        <select
                          aria-label={`Choice for ${item.name}`}
                          className="h-8 rounded-md border border-input bg-transparent px-2 text-sm"
                          value={choice ?? ''}
                          onChange={(event) => {
                            const value = event.target.value as Strategy
                            setStrategies((current) => ({ ...current, [item.entity_id]: value }))
                          }}
                        >
                          {item.strategies.map((strategy) => (
                            <option key={strategy} value={strategy}>
                              {STRATEGY[strategy]}
                              {strategy === item.default_strategy ? ' (default)' : ''}
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
        {message !== null && (
          <p role="alert" className="text-sm text-destructive">
            {message}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          {!stale && (
            <Button
              disabled={applying || conflicts.size > 0}
              onClick={() => {
                onApply(strategies)
              }}
            >
              {applying ? 'Applying…' : 'Apply the change'}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
