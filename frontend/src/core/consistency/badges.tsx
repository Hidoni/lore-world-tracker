import { Link } from '@tanstack/react-router'
import { AlertTriangleIcon } from 'lucide-react'

import { cn } from '@/lib/utils'
import { useFindings, useMutations, type components } from '@/data'

type Severity = components['schemas']['ShownSeverity']

/** Findings counted for badges: one query shared by every badge (the open findings, worst first). */
const BADGE_QUERY = { limit: 500 }
/**
 * How long the badges' counts are kept before a page reads them again: writes invalidate them, so
 * this only delays changes made elsewhere (a scan from the CLI). Reading 500 findings of a large
 * vault on every page took longer than the rest of the page (#144).
 */
const BADGE_STALE_MS = 60_000
const RANK: Record<Severity, number> = { error: 0, warning: 1, info: 2 }

export interface FindingCount {
  count: number
  /** The worst severity among them. */
  severity: Severity
}

/**
 * Open findings per subject entity (authors only: readers can't see findings). Counts cover the
 * first 500 open findings, the errors first.
 */
export function useFindingCounts(vault: string): ReadonlyMap<string, FindingCount> {
  const author = useMutations() !== null
  const findings = useFindings(vault, BADGE_QUERY, { enabled: author, staleTime: BADGE_STALE_MS })
  const counts = new Map<string, FindingCount>()
  for (const finding of findings.data?.items ?? []) {
    for (const subject of finding.subjects) {
      const current = counts.get(subject.id)
      counts.set(subject.id, {
        count: (current?.count ?? 0) + 1,
        severity:
          current === undefined || RANK[finding.severity] < RANK[current.severity]
            ? finding.severity
            : current.severity,
      })
    }
  }
  return counts
}

const TONE: Record<Severity, string> = {
  error: 'border-destructive/40 bg-destructive/10 text-destructive',
  warning: 'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-400',
  info: 'border-border bg-muted text-muted-foreground',
}

/**
 * An entity's open findings (consistency.md §5): count and worst severity, linking to the panel
 * filtered to the entity. Nothing when it has none.
 */
export function FindingsBadge({
  vault,
  entityId,
  compact = false,
}: {
  vault: string
  entityId: string
  compact?: boolean
}) {
  const found = useFindingCounts(vault).get(entityId)
  if (found === undefined) return null
  const label = found.count === 1 ? '1 consistency finding' : `${found.count} consistency findings`
  return (
    <Link
      to="/v/$vault/consistency"
      params={{ vault }}
      search={{ entity: entityId }}
      aria-label={label}
      title={label}
      data-severity={found.severity}
      className={cn(
        'inline-flex shrink-0 items-center gap-1 rounded-md border px-1.5 text-xs font-medium',
        compact ? 'h-5' : 'h-6',
        TONE[found.severity],
      )}
    >
      <AlertTriangleIcon className="size-3" aria-hidden />
      {found.count}
    </Link>
  )
}
