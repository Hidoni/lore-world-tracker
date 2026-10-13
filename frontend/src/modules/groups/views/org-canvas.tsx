import '@xyflow/react/dist/style.css'

import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react'
import { useEffect, useMemo, useState } from 'react'

import type { OrgChart } from '@/data'
import { cn } from '@/lib/utils'

import { layoutOrgChart, NODE_HEIGHT, NODE_WIDTH } from './layout'

type Unit = OrgChart['units'][number]
// React Flow's node data is a record (an interface has no index signature).
// eslint-disable-next-line @typescript-eslint/consistent-type-definitions
type UnitData = { unit: Unit }
type UnitNode = Node<UnitData, 'unit'>

/** "Led by Ilsa (Empress), Oren". */
export function leadersText(unit: Unit): string {
  return unit.leaders
    .map((leader) => (leader.title ? `${leader.name} (${leader.title})` : leader.name))
    .join(', ')
}

export function membersText(count: number): string {
  return count === 1 ? '1 member' : `${count} members`
}

function UnitBox({ data }: NodeProps<UnitNode>) {
  const { unit } = data
  const leaders = leadersText(unit)
  return (
    <div
      data-testid="org-unit"
      title={unit.name}
      className={cn(
        'flex flex-col justify-center gap-0.5 overflow-hidden rounded-md border bg-card px-3 shadow-sm',
        unit.via === 'root' && 'border-primary ring-2 ring-primary/40',
      )}
      style={{ width: NODE_WIDTH, height: NODE_HEIGHT }}
    >
      <Handle type="target" position={Position.Top} isConnectable={false} />
      <span className="truncate text-sm font-medium">{unit.name}</span>
      <span className="truncate text-xs text-muted-foreground">
        {leaders === '' ? 'No leader' : `Led by ${leaders}`}
      </span>
      <span className="text-xs text-muted-foreground">{membersText(unit.member_count)}</span>
      <Handle type="source" position={Position.Bottom} isConnectable={false} />
    </div>
  )
}

const NODE_TYPES = { unit: UnitBox }

function FitOnLayout({ layout }: { layout: unknown }) {
  const flow = useReactFlow()
  useEffect(() => {
    void flow.fitView({ padding: 0.15, maxZoom: 1.25 })
  }, [flow, layout])
  return null
}

/**
 * The org chart drawn with React Flow and laid out by ELK (a tree, top down): sub-groups under
 * their group, parts (`part_of`) dashed. Loaded lazily with its libraries.
 */
export default function OrgCanvas({
  chart,
  onOpen,
}: {
  chart: OrgChart
  onOpen: (id: string) => void
}) {
  const [layout, setLayout] = useState<{
    chart: OrgChart
    positions: Map<string, { x: number; y: number }>
  } | null>(null)
  useEffect(() => {
    let current = true
    void layoutOrgChart(chart).then((positions) => {
      if (current) setLayout({ chart, positions })
    })
    return () => {
      current = false
    }
  }, [chart])
  const nodes = useMemo<UnitNode[]>(
    () =>
      (layout?.chart.units ?? []).map((unit) => ({
        id: unit.id,
        type: 'unit',
        position: layout?.positions.get(unit.id) ?? { x: 0, y: 0 },
        data: { unit },
        draggable: false,
        connectable: false,
        ariaLabel: unit.name,
      })),
    [layout],
  )
  const edges = useMemo<Edge[]>(
    () =>
      (layout?.chart.units ?? []).flatMap((unit) =>
        unit.parent_id === null
          ? []
          : [
              {
                id: `${unit.parent_id}>${unit.id}`,
                source: unit.parent_id,
                target: unit.id,
                type: 'smoothstep',
                ...(unit.via === 'part_of' ? { style: { strokeDasharray: '4 4' } } : {}),
              },
            ],
      ),
    [layout],
  )
  if (layout === null) return <p className="p-3 text-sm text-muted-foreground">Laying out…</p>
  return (
    <ReactFlowProvider>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        nodesDraggable={false}
        nodesConnectable={false}
        minZoom={0.1}
        proOptions={{ hideAttribution: true }}
        onNodeClick={(_, node) => {
          onOpen(node.id)
        }}
      >
        <FitOnLayout layout={layout} />
        <Background gap={24} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </ReactFlowProvider>
  )
}
