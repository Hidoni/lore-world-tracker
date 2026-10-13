import { useState } from 'react'

import type { EntityViewProps } from '@/core/modules'
import { useEntityAsOf } from '@/core/time'
import { useChildren, useEntity, useGroupMembers } from '@/data'

import { LinkRows } from './link-rows'
import { MembershipGantt } from './membership-gantt'

/**
 * Members with their ranks and titles, optionally with the members of sub-groups; "History"
 * shows the memberships as a Gantt chart.
 */
export function MembersPanel({ vault, entityId }: EntityViewProps) {
  const [inside, setInside] = useState(false)
  const [history, setHistory] = useState(false)
  const group = useEntity(vault, entityId)
  const asOf = useEntityAsOf(vault, entityId)
  const members = useGroupMembers(vault, entityId, inside, asOf)
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
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={history}
          onChange={(event) => {
            setHistory(event.target.checked)
          }}
        />
        History
      </label>
      {members.isPending ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-muted-foreground">No members.</p>
      ) : history ? (
        <MembershipGantt
          vault={vault}
          dimensionId={group.data?.dimension_id ?? null}
          items={items}
        />
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
