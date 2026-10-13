import type { ELK, ElkNode } from 'elkjs/lib/elk-api'

import type { OrgChart } from '@/data'

export const NODE_WIDTH = 200
export const NODE_HEIGHT = 76

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

/** Node positions (top-left corners): each unit below the unit it belongs to. */
export async function layoutOrgChart(
  chart: OrgChart,
): Promise<Map<string, { x: number; y: number }>> {
  const root: ElkNode = {
    id: 'root',
    layoutOptions: {
      'elk.algorithm': 'mrtree',
      'elk.direction': 'DOWN',
      'elk.spacing.nodeNode': '32',
    },
    children: chart.units.map((unit) => ({ id: unit.id, width: NODE_WIDTH, height: NODE_HEIGHT })),
    edges: chart.units.flatMap((unit) =>
      unit.parent_id === null
        ? []
        : [{ id: `${unit.parent_id}>${unit.id}`, sources: [unit.parent_id], targets: [unit.id] }],
    ),
  }
  const laid = await (await elk()).layout(root)
  return new Map(
    (laid.children ?? []).map((child) => [child.id, { x: child.x ?? 0, y: child.y ?? 0 }]),
  )
}
