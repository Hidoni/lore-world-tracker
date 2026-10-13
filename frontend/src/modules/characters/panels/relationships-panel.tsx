import { PlusIcon } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { LinkDialog } from '@/core/links'
import type { EntityViewProps } from '@/core/modules'
import { useEntityAsOf } from '@/core/time'
import { useCharacterRelationships, useEntity, useMutations } from '@/data'

import { LinkRows } from './link-rows'

const TITLES: Record<string, string> = { family: 'Family', social: 'Social', custom: 'Other' }

/** The character's relationships by category (family, social, other), and adding one. */
export function RelationshipsPanel({ vault, entityId }: EntityViewProps) {
  const entity = useEntity(vault, entityId)
  const asOf = useEntityAsOf(vault, entityId)
  const relationships = useCharacterRelationships(vault, entityId, asOf)
  const editable = useMutations() !== null && entity.data?.deleted_at === null
  const [adding, setAdding] = useState(false)
  const groups = (relationships.data?.groups ?? []).filter((group) => group.items.length > 0)
  return (
    <div className="flex flex-col gap-3">
      {relationships.isPending ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : groups.length === 0 ? (
        <p className="text-sm text-muted-foreground">No relationships yet.</p>
      ) : (
        groups.map((group) => {
          const title = TITLES[group.category] ?? group.category
          return (
            <section key={group.category} aria-label={title} className="flex flex-col gap-1">
              <h3 className="text-xs font-medium text-muted-foreground">{title}</h3>
              <LinkRows vault={vault} label={title} items={group.items} />
            </section>
          )
        })
      )}
      {editable && entity.data !== undefined && (
        <Button
          variant="outline"
          size="sm"
          className="self-start"
          onClick={() => {
            setAdding(true)
          }}
        >
          <PlusIcon aria-hidden /> Add relationship
        </Button>
      )}
      {adding && entity.data !== undefined && (
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
