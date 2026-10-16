import { Link } from '@tanstack/react-router'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { LinkDialog } from '@/core/links'
import type { EntityViewProps } from '@/core/modules'
import { certaintyProps } from '@/core/time'
import { useEntityAsOf } from '@/core/time'
import { useEntity, useLinks, useLinkTypes, useMutations } from '@/data'
import { cn } from '@/lib/utils'

import { relationTypesOf } from '../relations'

/** Whether the kind has relation fields (the panel shows only then). */
export function useRelationFieldsShown({ vault, kind }: EntityViewProps): boolean {
  const types = useLinkTypes(vault)
  return relationTypesOf(types.data?.items ?? [], kind).some((type) => !type.archived)
}

/**
 * Relation fields (custom_fields.md, Concepts): the kind's custom link types as label/value rows,
 * the linked entities as values (as of the time cursor), with a way to add one.
 */
export function RelationFieldsPanel({ vault, entityId, kind }: EntityViewProps) {
  const editable = useMutations() !== null
  const types = useLinkTypes(vault)
  const relations = relationTypesOf(types.data?.items ?? [], kind).filter((type) => !type.archived)
  const asOf = useEntityAsOf(vault, entityId)
  const links = useLinks(vault, entityId, {
    type: relations.map((type) => type.key),
    direction: 'out',
    ...asOf,
  })
  const entity = useEntity(vault, entityId)
  const [adding, setAdding] = useState(false)
  const items = links.data?.items ?? []
  return (
    <div className="flex flex-col gap-2">
      <dl className="grid grid-cols-[minmax(8rem,auto)_1fr] gap-x-4 gap-y-1 text-sm">
        {relations.map((type) => {
          const linked = items.filter((item) => item.link.link_type === type.key)
          return (
            <div key={type.key} className="contents">
              <dt className="text-muted-foreground">{type.label}</dt>
              <dd>
                {linked.length === 0 ? (
                  <span className="text-muted-foreground">—</span>
                ) : (
                  <ul aria-label={type.label} className="flex flex-wrap gap-x-3">
                    {linked.map((item) => (
                      <li
                        key={item.link.id}
                        {...certaintyProps(item.certainty)}
                        className={cn(certaintyProps(item.certainty).className)}
                      >
                        <Link
                          to="/v/$vault/e/$entity"
                          params={{ vault, entity: item.other.id }}
                          className="text-primary underline-offset-2 hover:underline"
                        >
                          {item.other.name}
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </dd>
            </div>
          )
        })}
      </dl>
      {editable && entity.data && (
        <Button
          size="sm"
          variant="outline"
          className="self-start"
          onClick={() => {
            setAdding(true)
          }}
        >
          Link…
        </Button>
      )}
      {adding && entity.data && (
        <LinkDialog
          vault={vault}
          entity={{ id: entity.data.id, name: entity.data.name, kind: entity.data.kind }}
          mode="add"
          onClose={() => {
            setAdding(false)
          }}
        />
      )}
    </div>
  )
}
