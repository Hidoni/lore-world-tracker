import { LockIcon } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

import type { RecordPlace } from './branching'

/**
 * Where a record stands in the viewed branch, as badges (docs/modules/branches.md, UI): changed
 * here, inherited from a parent timeline, and the read-only shared past (explained on hover).
 * Nothing for the branch's own records or outside branches.
 */
export function RecordBranchBadge({
  place,
  branchName,
}: {
  place: RecordPlace | null
  branchName: string | null
}) {
  if (place === null || place.kind === 'own') return null
  if (!('from' in place)) {
    return <Badge className="text-xs">Changed in {branchName ?? 'this timeline'}</Badge>
  }
  return (
    <>
      <Badge variant="outline" className="text-xs">
        Inherited from {place.from.name}
      </Badge>
      {place.kind === 'past' && (
        <Tooltip>
          <TooltipTrigger asChild>
            <Badge variant="secondary" className="text-xs" tabIndex={0}>
              <LockIcon aria-hidden /> Shared past
            </Badge>
          </TooltipTrigger>
          <TooltipContent>
            Over before {branchName ?? 'this branch'} branched off: the timelines share it, so it
            can’t change here.
          </TooltipContent>
        </Tooltip>
      )}
    </>
  )
}
