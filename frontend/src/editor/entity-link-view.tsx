import { Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'

import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useKind } from '@/core/registry'
import { useEntity } from '@/data'

/**
 * An `entityLink` (frontend.md §6): the text with the target's kind icon and a hover card with its
 * summary. Missing, trashed and hidden targets render as plain text. `navigate`: a link to the
 * entity (reader/renderer), otherwise just a chip (in the editor).
 */
export function EntityLinkView({
  vault,
  entityId,
  navigate,
  children,
}: {
  vault: string
  entityId: string
  navigate: boolean
  children: ReactNode
}) {
  const entity = useEntity(vault, entityId)
  const kind = useKind(entity.data?.kind ?? '', vault)
  const target = entity.data
  const trashed = (target?.deleted_at ?? null) !== null
  if (target === undefined || trashed) {
    return <span data-entity-link="missing">{children}</span>
  }
  const Icon = kind?.icon
  const chip = (
    <>
      {Icon && <Icon aria-hidden className="mr-0.5 inline size-3.5 align-[-0.125em]" />}
      {children}
    </>
  )
  const className =
    'text-primary underline decoration-primary/40 underline-offset-2 hover:decoration-primary'
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        {navigate ? (
          <Link
            to="/v/$vault/e/$entity"
            params={{ vault, entity: target.id }}
            className={className}
            data-entity-link={target.id}
          >
            {chip}
          </Link>
        ) : (
          <span className={className} data-entity-link={target.id}>
            {chip}
          </span>
        )}
      </TooltipTrigger>
      <TooltipContent className="max-w-xs">
        <p className="font-medium">
          {target.name}
          {kind && <span className="ml-1 font-normal opacity-70">({kind.label})</span>}
        </p>
        {target.summary !== '' && <p className="mt-1 opacity-90">{target.summary}</p>}
      </TooltipContent>
    </Tooltip>
  )
}
