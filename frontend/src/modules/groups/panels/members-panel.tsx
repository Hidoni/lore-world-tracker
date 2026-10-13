import { useState } from 'react'

import type { EntityViewProps } from '@/core/modules'
import { useChildren, useGroupMembers } from '@/data'

import { LinkRows } from './link-rows'

/** Members with their ranks and titles, optionally with the members of sub-groups. */
export function MembersPanel({ vault, entityId }: EntityViewProps) {
  const [inside, setInside] = useState(false)
  const members = useGroupMembers(vault, entityId, inside)
  const children = useChildren(vault, entityId, { kind: ['group'], limit: 500 })
  const names = new Map((children.data?.items ?? []).map((child) => [child.id, child.name]))
  const items = members.data?.items ?? []
  const groupOf = new Map(items.map((membership) => [membership.item.link.id, membership.group_id]))
  return (
    <div className="flex flex-col gap-2">
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={inside}
          onChange={(event) => {
            setInside(event.target.checked)
          }}
        />
        Include sub-groups
      </label>
      {members.isPending ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-muted-foreground">No members.</p>
      ) : (
        <LinkRows
          vault={vault}
          label="Members"
          items={items.map((membership) => membership.item)}
          extra={(item) => {
            const group = groupOf.get(item.link.id)
            if (group === undefined || group === entityId) return null
            return `in ${names.get(group) ?? 'a sub-group'}`
          }}
        />
      )}
    </div>
  )
}
