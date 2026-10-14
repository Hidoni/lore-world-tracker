import type { GraphQuery } from '@/data'
import { readStored, writeStored } from '@/lib/storage'

/** The graph page's filters (docs/modules/graph.md, UI): what the request asks for, and orphans. */
export interface GraphFilters {
  kinds: string[]
  linkTypes: string[]
  tags: string[]
  mentions: boolean
  hierarchy: boolean
  /** `context`: the time context's dimension (with multiversal entities); `all`: the vault. */
  scope: 'context' | 'all'
  /** Nodes without edges. */
  orphans: boolean
  /** Local mode: the graph around this entity. */
  center: string | null
  depth: number
}

export const DEFAULT_FILTERS: GraphFilters = {
  kinds: [],
  linkTypes: [],
  tags: [],
  mentions: true,
  hierarchy: true,
  scope: 'context',
  orphans: true,
  center: null,
  depth: 2,
}

/** The request for the filters, the time context's dimension and the time cursor. */
/** The most nodes the page asks for ("Show up to …"; the server's maximum). */
export const MAX_NODES = 20_000

export function graphQuery(
  filters: GraphFilters,
  dimension: string | null,
  asOf: { timeline: string; at: string } | undefined,
  /** Nodes at most; the server's default (5,000) without it. */
  limit?: number,
): GraphQuery {
  return {
    ...(filters.scope === 'context' && dimension !== null ? { dimension } : {}),
    ...(filters.center === null ? {} : { center: filters.center, depth: filters.depth }),
    ...(filters.kinds.length > 0 ? { kind: filters.kinds } : {}),
    ...(filters.linkTypes.length > 0 ? { link_type: filters.linkTypes } : {}),
    ...(filters.tags.length > 0 ? { tag: filters.tags } : {}),
    ...(filters.mentions ? {} : { include_mentions: false }),
    ...(filters.hierarchy ? {} : { include_hierarchy: false }),
    ...(asOf ?? {}),
    ...(limit === undefined ? {} : { limit }),
  }
}

/** A named set of filters, kept in `localStorage` per vault. */
export interface SavedView {
  name: string
  filters: GraphFilters
}

const viewsKey = (vault: string) => `lore.graph.views.${vault}`

export function readViews(vault: string): SavedView[] {
  try {
    const parsed: unknown = JSON.parse(readStored(viewsKey(vault)) ?? '[]')
    return Array.isArray(parsed)
      ? (parsed as SavedView[]).map((view) => ({
          name: view.name,
          filters: { ...DEFAULT_FILTERS, ...view.filters },
        }))
      : []
  } catch {
    return []
  }
}

export function writeViews(vault: string, views: readonly SavedView[]): void {
  writeStored(viewsKey(vault), JSON.stringify(views))
}

/** Node positions of a laid-out graph (best effort: a lost cache only means a new layout). */
export type Positions = Record<string, [number, number]>
const MAX_CACHED = 20_000

const positionsKey = (vault: string, view: string) => `lore.graph.layout.${vault}.${view}`

export function readPositions(vault: string, view: string): Positions {
  try {
    const parsed: unknown = JSON.parse(readStored(positionsKey(vault, view)) ?? '{}')
    return parsed !== null && typeof parsed === 'object' ? (parsed as Positions) : {}
  } catch {
    return {}
  }
}

export function writePositions(vault: string, view: string, positions: Positions): void {
  if (Object.keys(positions).length > MAX_CACHED) return
  writeStored(positionsKey(vault, view), JSON.stringify(positions))
}

/** The cache key of a view: its filters (the layout of one graph fits another poorly). */
export function viewKey(filters: GraphFilters): string {
  return JSON.stringify(filters)
}
