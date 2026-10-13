import type { ELK, ElkExtendedEdge, ElkNode } from 'elkjs/lib/elk-api'

import type { FamilyTree } from '@/data'

export const NODE_WIDTH = 168
export const NODE_HEIGHT = 40

/**
 * The edges the layout layers by: ancestor → descendant and parent → dialect (top to bottom).
 * Borrowings don't shape the tree: they are drawn, not laid out.
 */
export function layoutEdges(tree: FamilyTree): ElkExtendedEdge[] {
  return tree.edges
    .filter((edge) => edge.kind !== 'borrowed_from')
    .map((edge) => ({ id: edge.id, sources: [edge.target_id], targets: [edge.source_id] }))
}

let engine: Promise<ELK> | null = null

/** ELK, in a worker where there are workers, else on the main thread; loaded when first used. */
function elk(): Promise<ELK> {
  engine ??=
    typeof Worker === 'undefined'
      ? import('elkjs/lib/elk.bundled.js').then((module) => new module.default())
      : Promise.all([
          import('elkjs/lib/elk-api.js'),
          import('elkjs/lib/elk-worker.min.js?url'),
        ]).then(([api, worker]) => new api.default({ workerUrl: worker.default }))
  return engine
}

/** Node positions (top-left corners): ancestors above their descendants. */
export async function layoutFamily(
  tree: FamilyTree,
): Promise<Map<string, { x: number; y: number }>> {
  const root: ElkNode = {
    id: 'root',
    layoutOptions: {
      'elk.algorithm': 'layered',
      'elk.direction': 'DOWN',
      'elk.spacing.nodeNode': '24',
      'elk.layered.spacing.nodeNodeBetweenLayers': '48',
    },
    children: tree.nodes.map((node) => ({ id: node.id, width: NODE_WIDTH, height: NODE_HEIGHT })),
    edges: layoutEdges(tree),
  }
  const laid = await (await elk()).layout(root)
  return new Map(
    (laid.children ?? []).map((child) => [child.id, { x: child.x ?? 0, y: child.y ?? 0 }]),
  )
}
