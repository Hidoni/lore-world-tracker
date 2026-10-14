import {
  compose,
  parseRational,
  validateCorrespondence,
  type Correspondence,
  type Direction,
  type Step,
} from '@lore/chronology'
import { useMemo } from 'react'

import { useCorrespondences, useEntitiesById, type CorrespondenceOut } from '@/data'

import { dimensionTime } from './calendars'

/**
 * Correspondences in the browser (time-model.md §12): the stored correspondences compiled with
 * the TS engine, the graph of dimensions they connect and mapping along its shortest paths, the
 * same way the server maps (`lore.core.time.correspondences`: fewest correspondences, ties to the
 * smallest ids, flooring at every step). Timeline dimension lanes map every item, and the editor's
 * tester and chart map without a request per moment.
 */

/** A correspondence seen from one of its dimensions. */
export interface CorrespondenceEdge {
  correspondenceId: string
  correspondence: Correspondence
  target: string
  direction: Direction
}

export interface CorrespondenceGraph {
  compiled: ReadonlyMap<string, Correspondence>
  rows: ReadonlyMap<string, CorrespondenceOut>
  edges: ReadonlyMap<string, readonly CorrespondenceEdge[]>
  /** Each dimension's duration `D` (dimensions without one can't be mapped to). */
  durations: ReadonlyMap<string, bigint>
}

/** The engine's correspondence for stored rows; `null` while a sync point is unresolved or the
 * resolved points don't make one (the server refuses those, but an anchor may have moved). */
export function compileStored(row: CorrespondenceOut): Correspondence | null {
  const points: (readonly [bigint, bigint])[] = []
  for (const point of row.points) {
    if (point.a_t === null || point.b_t === null) return null
    points.push([point.a_t, point.b_t])
  }
  if (points.length === 0) return null
  const rate = (value: CorrespondenceOut['rate_before']) =>
    value === null ? null : parseRational(value.num, value.den)
  try {
    return validateCorrespondence(points, {
      extrapolation: row.extrapolation,
      rateBefore: rate(row.rate_before),
      rateAfter: rate(row.rate_after),
    })
  } catch {
    return null
  }
}

export function correspondenceGraph(
  rows: readonly CorrespondenceOut[],
  durations: ReadonlyMap<string, bigint>,
): CorrespondenceGraph {
  const compiled = new Map<string, Correspondence>()
  const kept = new Map<string, CorrespondenceOut>()
  const edges = new Map<string, CorrespondenceEdge[]>()
  const add = (from: string, edge: CorrespondenceEdge) => {
    const list = edges.get(from)
    if (list === undefined) edges.set(from, [edge])
    else list.push(edge)
  }
  const sorted = [...rows].sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))
  for (const row of sorted) {
    if (row.deleted_at !== null) continue
    if (!durations.has(row.dimension_a_id) || !durations.has(row.dimension_b_id)) continue
    const found = compileStored(row)
    if (found === null) continue
    compiled.set(row.id, found)
    kept.set(row.id, row)
    add(row.dimension_a_id, {
      correspondenceId: row.id,
      correspondence: found,
      target: row.dimension_b_id,
      direction: 'ab',
    })
    add(row.dimension_b_id, {
      correspondenceId: row.id,
      correspondence: found,
      target: row.dimension_a_id,
      direction: 'ba',
    })
  }
  return { compiled, rows: kept, edges, durations }
}

/**
 * The shortest path from `source` to `target` (breadth first over edges in id order, like the
 * server); `[]` from a dimension to itself, `null` when they aren't connected.
 */
export function shortestPath(
  graph: CorrespondenceGraph,
  source: string,
  target: string,
): CorrespondenceEdge[] | null {
  if (source === target) return []
  const previous = new Map<string, { from: string; edge: CorrespondenceEdge }>()
  const seen = new Set([source])
  const queue = [source]
  // A for-of over an array visits what is pushed while iterating: a queue.
  for (const current of queue) {
    for (const edge of graph.edges.get(current) ?? []) {
      if (seen.has(edge.target)) continue
      seen.add(edge.target)
      previous.set(edge.target, { from: current, edge })
      if (edge.target === target) {
        const path: CorrespondenceEdge[] = []
        let node = target
        while (node !== source) {
          const step = previous.get(node)
          if (step === undefined) return null
          path.push(step.edge)
          node = step.from
        }
        return path.reverse()
      }
      queue.push(edge.target)
    }
  }
  return null
}

/** The dimensions reachable from `source` (not itself), nearest first. */
export function reachableFrom(graph: CorrespondenceGraph, source: string): string[] {
  const seen = new Set([source])
  const queue = [source]
  for (const current of queue) {
    for (const edge of graph.edges.get(current) ?? []) {
      if (seen.has(edge.target)) continue
      seen.add(edge.target)
      queue.push(edge.target)
    }
  }
  return queue.slice(1)
}

function steps(graph: CorrespondenceGraph, path: readonly CorrespondenceEdge[]): Step[] {
  return path.map((edge) => ({
    correspondence: edge.correspondence,
    direction: edge.direction,
    targetDuration: graph.durations.get(edge.target) ?? 0n,
  }))
}

/**
 * A function mapping moments of `source` to `target` (`null` results: no corresponding moment,
 * or outside `source`'s `[0, D]`); `null` when the dimensions aren't connected.
 */
export function mapper(
  graph: CorrespondenceGraph,
  source: string,
  target: string,
): ((t: bigint) => bigint | null) | null {
  const path = shortestPath(graph, source, target)
  if (path === null) return null
  const duration = graph.durations.get(source)
  if (duration === undefined) return null
  const legs = steps(graph, path)
  return (t) => (t < 0n || t > duration ? null : compose(legs, t))
}

/**
 * The correspondences the request sees as a graph, with the durations of the dimensions they
 * connect (`null` while loading, or while the correspondences module is off).
 */
export function useCorrespondenceGraph(
  vault: string,
  { enabled = true }: { enabled?: boolean } = {},
): CorrespondenceGraph | null {
  const list = useCorrespondences(vault, null, { enabled })
  const rows = list.data?.items
  const ids = useMemo(
    () =>
      [...new Set((rows ?? []).flatMap((row) => [row.dimension_a_id, row.dimension_b_id]))].sort(),
    [rows],
  )
  const dimensions = useEntitiesById(vault, ids)
  return useMemo(() => {
    if (rows === undefined || dimensions.length < ids.length) return null
    const durations = new Map<string, bigint>()
    for (const entity of dimensions) {
      const time = dimensionTime(entity)
      if (time !== null && entity.deleted_at === null) durations.set(entity.id, time.duration)
    }
    return correspondenceGraph(rows, durations)
  }, [rows, dimensions, ids.length])
}
