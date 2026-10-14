import { useState } from 'react'

import { LinkDialog } from '@/core/links'
import { useMutations, type GraphData } from '@/data'

type Node = GraphData['nodes'][number]

/**
 * Visual linking (docs/modules/graph.md): `Alt`+drag from a node to another opens the add-link
 * dialog from the first to the second, with the link types that fit both kinds. Returns the
 * graph's `onLink` (absent where links can't be written: reader mode) and the dialog.
 */
export function useVisualLink(vault: string, nodes: readonly Node[]) {
  const editable = useMutations() !== null
  const [ends, setEnds] = useState<[Node, Node] | null>(null)
  const onLink = (source: string, target: string): void => {
    const from = nodes.find((node) => node.id === source)
    const to = nodes.find((node) => node.id === target)
    if (from !== undefined && to !== undefined) setEnds([from, to])
  }
  const dialog =
    ends === null ? null : (
      <LinkDialog
        vault={vault}
        entity={{ id: ends[0].id, name: ends[0].name, kind: ends[0].kind }}
        mode="add"
        target={{
          id: ends[1].id,
          name: ends[1].name,
          kind: ends[1].kind,
          dimension_id: ends[1].dimension_id,
        }}
        onClose={() => {
          setEnds(null)
        }}
      />
    )
  return { onLink: editable ? onLink : undefined, dialog }
}
