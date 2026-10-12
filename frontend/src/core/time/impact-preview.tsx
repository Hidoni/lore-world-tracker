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
import type { CalendarProposal, components } from '@/data'

import { SELECT_CLASS } from './select'

type Proposal = CalendarProposal
type Item = Proposal['items'][number]
export type Strategy = components['schemas']['CalendarStrategy']

const STRATEGY_LABEL: Record<Strategy, string> = {
  keep_date: 'Keep the date',
  pin_moment: 'Keep the moment',
  constrain: 'Nearest valid date',
}

/** Rows with a problem need an explicit choice (time-model.md §7.4): the default never applies. */
function isProblem(item: Item): boolean {
  return item.problem !== null
}

function initial(items: readonly Item[]): Record<string, Strategy | ''> {
  return Object.fromEntries(items.map((item) => [item.key, isProblem(item) ? '' : 'keep_date']))
}

function slotLabel(item: Item): string {
  return item.slot.replaceAll('_', ' ')
}

/**
 * The impact preview of a calendar edit (frontend.md §8, D1): every time slot the edit moves or
 * breaks, before and after, with a strategy per row: keep the typed date (it moves), keep the
 * moment (the anchor becomes absolute), or the nearest valid date (for dates that no longer
 * exist). Bulk actions set every row that offers them; rows with a problem must be decided before
 * applying. A stale proposal (the calendar or a dependent changed meanwhile) can be previewed
 * again.
 */
export function ImpactPreviewDialog({
  vault,
  proposal,
  applying,
  stale,
  problems,
  message,
  onApply,
  onRerun,
  onClose,
}: {
  vault: string
  proposal: Proposal
  applying: boolean
  /** The server refused the proposal as stale or expired. */
  stale: boolean
  /** Per item key: why its strategy was refused. */
  problems: Readonly<Record<string, string>>
  message: string | null
  onApply: (strategies: Record<string, Strategy>) => void
  onRerun: () => void
  onClose: () => void
}) {
  const [strategies, setStrategies] = useState(() => initial(proposal.items))
  const undecided = proposal.items.filter((item) => strategies[item.key] === '').length
  const bulk = (strategy: Strategy) => {
    setStrategies((current) =>
      Object.fromEntries(
        proposal.items.map((item) => [
          item.key,
          item.strategies.includes(strategy) && !(strategy === 'keep_date' && isProblem(item))
            ? strategy
            : (current[item.key] ?? ''),
        ]),
      ),
    )
  }
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
          <DialogTitle>Review the calendar change</DialogTitle>
          <DialogDescription>
            {summary.changed} time {summary.changed === 1 ? 'point changes' : 'points change'}
            {summary.problems > 0 ? `, ${summary.problems} of them broken` : ''}
            {summary.series > 0
              ? `; ${summary.series} recurring ${summary.series === 1 ? 'series moves' : 'series move'}`
              : ''}
            .
          </DialogDescription>
        </DialogHeader>
        {stale ? (
          <div role="alert" className="flex flex-col items-start gap-2 text-sm">
            <p>
              The calendar or something that depends on it changed since this preview (or the
              preview expired). Preview the change again.
            </p>
            <Button onClick={onRerun}>Preview again</Button>
          </div>
        ) : (
          <>
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  bulk('keep_date')
                }}
              >
                Keep all dates
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  bulk('pin_moment')
                }}
              >
                Keep all moments
              </Button>
              {summary.problems > 0 && (
                <span className="self-center text-xs text-muted-foreground">
                  {undecided === 0
                    ? 'Every broken date has a choice.'
                    : `${undecided} broken ${undecided === 1 ? 'date needs' : 'dates need'} a choice.`}
                </span>
              )}
            </div>
            <table aria-label="Affected time points" className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground">
                  <th className="py-1 pr-2 font-normal">Record</th>
                  <th className="py-1 pr-2 font-normal">Now</th>
                  <th className="py-1 pr-2 font-normal">After</th>
                  <th className="py-1 font-normal">Choice</th>
                </tr>
              </thead>
              <tbody>
                {proposal.items.map((item) => {
                  const choice = strategies[item.key] ?? ''
                  const after =
                    choice === 'pin_moment'
                      ? item.pinned_display
                      : choice === 'constrain'
                        ? item.constrained_display
                        : item.new_display
                  return (
                    <tr
                      key={item.key}
                      aria-label={`${item.name ?? item.id} ${slotLabel(item)}`}
                      className="border-t align-top"
                    >
                      <td className="py-1 pr-2">
                        {item.entity_id !== null ? (
                          <Link
                            to="/v/$vault/e/$entity"
                            params={{ vault, entity: item.entity_id }}
                            className="underline-offset-2 hover:underline"
                          >
                            {item.name ?? item.id}
                          </Link>
                        ) : (
                          (item.name ?? item.id)
                        )}{' '}
                        <span className="text-xs text-muted-foreground">({slotLabel(item)})</span>
                      </td>
                      <td className="py-1 pr-2">{item.old_display ?? '—'}</td>
                      <td className="py-1 pr-2">
                        {item.problem !== null &&
                        choice !== 'pin_moment' &&
                        choice !== 'constrain' ? (
                          <span className="text-destructive">{item.problem.message}</span>
                        ) : (
                          (after ?? '—')
                        )}
                        {problems[item.key] !== undefined && (
                          <p role="alert" className="text-xs text-destructive">
                            {problems[item.key]}
                          </p>
                        )}
                      </td>
                      <td className="py-1">
                        <select
                          aria-label={`Choice for ${item.name ?? item.id} ${slotLabel(item)}`}
                          className={SELECT_CLASS}
                          value={choice}
                          onChange={(event) => {
                            const value = event.target.value as Strategy | ''
                            setStrategies((current) => ({ ...current, [item.key]: value }))
                          }}
                        >
                          {isProblem(item) && <option value="">Choose…</option>}
                          {item.strategies.map((strategy) => (
                            <option key={strategy} value={strategy}>
                              {strategy === 'keep_date' && isProblem(item)
                                ? 'Keep the date (accept the problem)'
                                : STRATEGY_LABEL[strategy]}
                            </option>
                          ))}
                        </select>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            {proposal.series.length > 0 && (
              <section aria-label="Recurring series" className="text-sm">
                <h3 className="font-medium">Recurring series</h3>
                <ul className="ml-4 list-disc">
                  {proposal.series.map((series) => (
                    <li key={series.entity_id}>{series.name ?? series.entity_id}</li>
                  ))}
                </ul>
              </section>
            )}
          </>
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
              disabled={applying || undecided > 0}
              onClick={() => {
                onApply(
                  Object.fromEntries(
                    Object.entries(strategies).filter(
                      (entry): entry is [string, Strategy] => entry[1] !== '',
                    ),
                  ),
                )
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
