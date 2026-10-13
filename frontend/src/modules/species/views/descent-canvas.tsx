import '@xyflow/react/dist/style.css'

import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react'
import { useEffect, useMemo, useState } from 'react'

import type { DescentTree } from '@/data'

import { layoutDescent, NODE_HEIGHT, NODE_WIDTH } from './layout'

type FamilyNode = DescentTree['nodes'][number]
// React Flow's node data is a record (an interface has no index signature).
// eslint-disable-next-line @typescript-eslint/consistent-type-definitions
type SpeciesNodeData = { node: FamilyNode }
type SpeciesFlowNode = Node<SpeciesNodeData, 'species'>

function SpeciesNode({ data }: NodeProps<SpeciesFlowNode>) {
  return (
    <div
      data-testid="descent-node"
      title={data.node.name}
      className="flex items-center justify-center overflow-hidden rounded-md border bg-card px-2 text-xs font-medium shadow-sm"
      style={{ width: NODE_WIDTH, height: NODE_HEIGHT }}
    >
      <Handle type="target" position={Position.Top} isConnectable={false} />
      <span className="truncate">{data.node.name}</span>
      <Handle type="source" position={Position.Bottom} isConnectable={false} />
    </div>
  )
}

const NODE_TYPES = { species: SpeciesNode }

function FitOnLayout({ layout }: { layout: unknown }) {
  const flow = useReactFlow()
  useEffect(() => {
    void flow.fitView({ padding: 0.15, maxZoom: 1.25 })
  }, [flow, layout])
  return null
}

/**
 * The descent tree drawn with React Flow and laid out by ELK: ancestors above descendants,
 * subspecies below their species (dotted). Loaded lazily with its libraries.
 */
export default function DescentCanvas({
  tree,
  onOpen,
}: {
  tree: DescentTree
  onOpen: (id: string) => void
}) {
  const [layout, setLayout] = useState<{
    tree: DescentTree
    positions: Map<string, { x: number; y: number }>
  } | null>(null)
  useEffect(() => {
    let current = true
    void layoutDescent(tree).then((positions) => {
      if (current) setLayout({ tree, positions })
    })
    return () => {
      current = false
    }
  }, [tree])
  const nodes = useMemo<SpeciesFlowNode[]>(
    () =>
      (layout?.tree.nodes ?? []).map((node) => ({
        id: node.id,
        type: 'species',
        position: layout?.positions.get(node.id) ?? { x: 0, y: 0 },
        data: { node },
        draggable: false,
        connectable: false,
      })),
    [layout],
  )
  const edges = useMemo<Edge[]>(
    () =>
      (layout?.tree.edges ?? []).map((edge) => ({
        id: edge.id,
        // Drawn from the ancestor (above) down to the descendant.
        source: edge.target_id,
        target: edge.source_id,
        markerEnd: { type: MarkerType.ArrowClosed },
        ...(edge.kind === 'subspecies' ? { style: { strokeDasharray: '1 3' } } : {}),
      })),
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
