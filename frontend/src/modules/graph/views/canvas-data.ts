import { useMemo } from 'react'

import { useActiveModules } from '@/core/modules'
import { useKindRegistry } from '@/core/registry'
import type { GraphData } from '@/data'

import { edgeStyle, mergeStyles, nodeColor, nodeSize } from '../styles'
import type { CanvasEdge, CanvasNode } from './graph-canvas'

type Node = GraphData['nodes'][number]

/** What the renderer draws: nodes and edges styled by kind, link type and the modules' styles. */
export function useCanvasData(
  vault: string,
  nodes: readonly Node[],
  edges: GraphData['edges'] | undefined,
): { canvasNodes: CanvasNode[]; canvasEdges: CanvasEdge[] } {
  const registry = useKindRegistry(vault)
  const { modules } = useActiveModules(vault)
  const styles = useMemo(() => mergeStyles(modules.map((m) => m.graphStyles)), [modules])
  const canvasNodes = useMemo(
    () =>
      nodes.map((node) => ({
        id: node.id,
        label: node.name,
        color: nodeColor(node.kind, registry, styles),
        size: nodeSize(node.degree, node.kind, styles),
      })),
    [nodes, registry, styles],
  )
  const canvasEdges = useMemo(
    () =>
      (edges ?? []).map((edge) => {
        const style = edgeStyle(edge, registry, styles)
        return { source: edge.source, target: edge.target, color: style.color, size: style.size }
      }),
    [edges, registry, styles],
  )
  return { canvasNodes, canvasEdges }
}
