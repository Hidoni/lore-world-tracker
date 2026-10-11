import { Link } from '@tanstack/react-router'
import { ChevronRightIcon } from 'lucide-react'
import { Fragment } from 'react'

import { useEntity } from '@/data'

const MAX_DEPTH = 20

/** One ancestor and, before it, its own ancestors (loaded one by one up the chain). */
function Ancestor({ vault, id, depth }: { vault: string; id: string; depth: number }) {
  const entity = useEntity(vault, id)
  const parent = entity.data?.parent_id ?? null
  return (
    <>
      {parent !== null && depth < MAX_DEPTH && (
        <Ancestor vault={vault} id={parent} depth={depth + 1} />
      )}
      <li className="flex items-center gap-1">
        <Link to="/v/$vault/e/$entity" params={{ vault, entity: id }} className="hover:underline">
          {entity.data?.name ?? '…'}
        </Link>
        <ChevronRightIcon className="size-3" aria-hidden />
      </li>
    </>
  )
}

/** The parent chain of an entity (frontend.md §7). */
export function Breadcrumbs({
  vault,
  parentId,
  name,
}: {
  vault: string
  parentId: string | null
  name: string
}) {
  return (
    <nav aria-label="Breadcrumbs">
      <ol className="flex flex-wrap items-center gap-1 text-sm text-muted-foreground">
        <Fragment>
          {parentId !== null && <Ancestor vault={vault} id={parentId} depth={0} />}
          <li aria-current="page" className="text-foreground">
            {name}
          </li>
        </Fragment>
      </ol>
    </nav>
  )
}
