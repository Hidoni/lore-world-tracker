import type { ELK, ElkExtendedEdge, ElkNode } from 'elkjs/lib/elk-api'

import type { CausalityGraph } from '@/data'

export const NODE_WIDTH = 184
export const NODE_HEIGHT = 52

type GraphNode = CausalityGraph['nodes'][number]

/** Earlier starts first; events without a start last. */
export function byStart(a: GraphNode, b: GraphNode): number {
  if (a.start_t === b.start_t) return 0
  if (a.start_t === null) return 1
  if (b.start_t === null) return -1
  return a.start_t < b.start_t ? -1 : 1
}

/**
 * The edges the layout layers by: from the earlier event to the later one (on equal starts, the
 * link's own direction), so the columns follow time left → right even where an effect is dated
 * before its cause or links form a cycle.
 */
export function layoutEdges(graph: CausalityGraph): ElkExtendedEdge[] {
  const nodes = new Map(graph.nodes.map((node) => [node.id, node]))
  return graph.edges.flatMap((edge) => {
    const source = nodes.get(edge.source_id)
    const target = nodes.get(edge.target_id)
    if (source === undefined || target === undefined) return []
    const backwards = byStart(source, target) > 0
    return [
      {
        id: edge.id,
        sources: [backwards ? edge.target_id : edge.source_id],
        targets: [backwards ? edge.source_id : edge.target_id],
      },
    ]
  })
}

let engine: Promise<ELK> | null = null

/**
 * ELK, in a worker where there are workers (a large graph's layout doesn't block the page), else
 * on the main thread. Loaded with the first layout.
 */
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

/** Node positions (top-left corners) from ELK's layered layout, left → right in time. */
export async function layoutCausality(
  graph: CausalityGraph,
): Promise<Map<string, { x: number; y: number }>> {
  const root: ElkNode = {
    id: 'root',
    layoutOptions: {
      'elk.algorithm': 'layered',
      'elk.direction': 'RIGHT',
      'elk.spacing.nodeNode': '20',
      'elk.layered.spacing.nodeNodeBetweenLayers': '56',
      // Within a column, keep the given order: by start.
      'elk.layered.considerModelOrder.strategy': 'NODES_AND_EDGES',
      'elk.layered.crossingMinimization.forceNodeModelOrder': 'true',
    },
    children: [...graph.nodes]
      .sort(byStart)
      .map((node) => ({ id: node.id, width: NODE_WIDTH, height: NODE_HEIGHT })),
    edges: layoutEdges(graph),
  }
  const laid = await (await elk()).layout(root)
  return new Map(
    (laid.children ?? []).map((child) => [child.id, { x: child.x ?? 0, y: child.y ?? 0 }]),
  )
}
