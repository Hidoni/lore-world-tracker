import { Link } from '@tanstack/react-router'

import type { EntityViewProps } from '@/core/modules'
import { MomentDisplay } from '@/core/time'
import { useDimensions } from '@/data'

import { useConcurrently } from '../concurrently'

/**
 * "Concurrently in…" (docs/modules/correspondences.md, UI): the moment the event starts, mapped
 * to each dimension reachable through correspondences (the shortest path, like the server), in
 * that dimension's display calendar. Dimensions where nothing corresponds are left out.
 */
export function ConcurrentlyPanel({ vault, entityId }: EntityViewProps) {
  const mapped = useConcurrently(vault, entityId)
  const dimensions = useDimensions(vault)
  const names = new Map((dimensions.data?.items ?? []).map((item) => [item.id, item.name]))
  if (mapped.length === 0) return null
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm" data-testid="concurrently">
      {mapped.map(({ dimension, t }) => (
        <div key={dimension} className="contents">
          <dt>
            <Link
              to="/v/$vault/d/$dimension"
              params={{ vault, dimension }}
              className="text-muted-foreground underline-offset-2 hover:underline"
            >
              {names.get(dimension) ?? 'Dimension'}
            </Link>
          </dt>
          <dd>
            <MomentDisplay vault={vault} dimension={dimension} moment={{ t, precision: 'base' }} />
          </dd>
        </div>
      ))}
    </dl>
  )
}
