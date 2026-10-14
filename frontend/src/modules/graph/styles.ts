import type { GraphStyles } from '@/core/modules'
import type { KindRegistry } from '@/core/registry'
import type { GraphData } from '@/data'

type Edge = GraphData['edges'][number]

/** Edge categories (docs/modules/graph.md, UI): each drawn in its own color. */
export type EdgeCategory =
  'family' | 'social' | 'spatial' | 'causal' | 'mention' | 'hierarchy' | 'other'

export const CATEGORY_COLORS: Record<EdgeCategory, string> = {
  family: '#e11d48',
  social: '#7c3aed',
  spatial: '#059669',
  causal: '#d97706',
  mention: '#94a3b8',
  hierarchy: '#64748b',
  other: '#0284c7',
}

const FAMILY = new Set(['characters.parent_of', 'characters.sibling_of', 'characters.spouse_of'])

export function edgeCategory(edge: Pick<Edge, 'kind' | 'link_type'>): EdgeCategory {
  if (edge.kind === 'mention') return 'mention'
  if (edge.kind === 'parent') return 'hierarchy'
  const type = edge.link_type ?? ''
  if (FAMILY.has(type)) return 'family'
  if (type === 'core.causes') return 'causal'
  if (type.startsWith('locations.')) return 'spatial'
  if (type.startsWith('characters.') || type.startsWith('groups.')) return 'social'
  return 'other'
}

/** Module styles merged (later modules win). */
export function mergeStyles(styles: readonly (GraphStyles | undefined)[]): Required<GraphStyles> {
  const merged = { nodes: {}, edges: {} } as Required<GraphStyles>
  for (const style of styles) {
    Object.assign(merged.nodes, style?.nodes ?? {})
    Object.assign(merged.edges, style?.edges ?? {})
  }
  return merged
}

/** A node's color: the module style of its kind, else the kind's registry color. */
export function nodeColor(
  kind: string,
  registry: KindRegistry | undefined,
  styles: Required<GraphStyles>,
) {
  return styles.nodes[kind]?.color ?? registry?.kind(kind)?.color ?? '#64748b'
}

/** A node's size by degree (and the module style's base size). */
export function nodeSize(degree: number, kind: string, styles: Required<GraphStyles>): number {
  const base = styles.nodes[kind]?.size ?? 3
  return base + Math.sqrt(degree) * 1.5
}

/** An edge's color and size: the module style of its link type, the link type's registry style,
 * else its category's color. */
export function edgeStyle(
  edge: Pick<Edge, 'kind' | 'link_type' | 'weight'>,
  registry: KindRegistry | undefined,
  styles: Required<GraphStyles>,
): { color: string; size: number; category: EdgeCategory } {
  const category = edgeCategory(edge)
  const own = edge.link_type === null ? undefined : styles.edges[edge.link_type]
  const typed = edge.link_type === null ? undefined : registry?.linkType(edge.link_type)?.graph
  return {
    category,
    color: own?.color ?? typed?.color ?? CATEGORY_COLORS[category],
    size: own?.size ?? Math.min(1 + Math.log2(Math.max(edge.weight, 1)), 4) * (typed?.weight ?? 1),
  }
}
