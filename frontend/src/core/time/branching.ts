import { useMemo } from 'react'

import { useActiveModules } from '@/core/modules'
import { useTimelines, type TimelineNode } from '@/data'

import { useTimeContext } from './time-context'

/**
 * One entry of a timeline's lineage (time-model.md §4.2): the timeline itself (depth 0, cut-off
 * `null`: +∞), then each ancestor with the moment its records stop being inherited.
 */
export interface LineageEntry {
  timeline: TimelineNode
  /** `null`: +∞ (the viewed timeline). */
  cutoff: bigint | null
  depth: number
}

/** Every timeline of a dimension's tree, parents before their branches (depth-first, by name). */
export function flattenTimelines(
  nodes: readonly TimelineNode[],
  depth = 0,
): { node: TimelineNode; depth: number }[] {
  return nodes.flatMap((node) => [{ node, depth }, ...flattenTimelines(node.children, depth + 1)])
}

/**
 * The lineage of `timelineId` in a dimension's tree: `cutoff_1 = b(T)`, then
 * `cutoff_{i+1} = min(cutoff_i, b(L_i))`. A branch point never resolved inherits nothing (0).
 * Empty when the timeline isn't in the tree.
 */
export function lineageOf(nodes: readonly TimelineNode[], timelineId: string): LineageEntry[] {
  const byId = new Map(flattenTimelines(nodes).map(({ node }) => [node.id, node]))
  const entries: LineageEntry[] = []
  let node = byId.get(timelineId)
  let cutoff: bigint | null = null
  while (node !== undefined) {
    entries.push({ timeline: node, cutoff, depth: entries.length })
    if (node.parent_timeline_id === null) break
    const branchT = node.branch_t ?? 0n
    cutoff = cutoff === null || branchT < cutoff ? branchT : cutoff
    node = byId.get(node.parent_timeline_id)
  }
  return entries
}

/**
 * Where a time-bound record stands in the viewed timeline (time-model.md §4.3, §4.4):
 * - `own`: the timeline's own record (in a branch: created there);
 * - `override`: the branch's version of an inherited record;
 * - `past`: inherited and over by the cut-off, the shared past (read-only in the branch);
 * - `spanning`: inherited and still going at the cut-off ("edit in this timeline" overrides it).
 */
export type RecordPlace =
  { kind: 'own' | 'override' } | { kind: 'past' | 'spanning'; from: TimelineNode; cutoff: bigint }

export interface TimeBoundRecord {
  timelineId: string | null
  /** `null`: open start (−∞). */
  start: bigint | null
  /** `null`: open end (+∞). */
  end: bigint | null
  overridesId?: string | null
}

/** `null` when the record isn't in the lineage, or the lineage is a prime timeline's (no badge). */
export function recordPlace(
  lineage: readonly LineageEntry[],
  record: TimeBoundRecord,
): RecordPlace | null {
  if (lineage.length < 2) return null
  const entry = lineage.find((candidate) => candidate.timeline.id === record.timelineId)
  if (entry === undefined) return null
  if (entry.cutoff === null) {
    return { kind: record.overridesId == null ? 'own' : 'override' }
  }
  const ended = record.end !== null && record.end <= entry.cutoff
  return { kind: ended ? 'past' : 'spanning', from: entry.timeline, cutoff: entry.cutoff }
}

export interface Branching {
  /** The branches module is on: branches can be created and edited. */
  enabled: boolean
  timelineId: string | null
  /** The viewed timeline (`null` while loading). */
  current: TimelineNode | null
  lineage: LineageEntry[]
  /** The viewed timeline is a branch. */
  inBranch: boolean
  /** Every timeline of the dimension, parents first. */
  timelines: { node: TimelineNode; depth: number }[]
  name: (timelineId: string | null | undefined) => string | null
}

/** The current dimension's timelines and the viewed timeline's lineage. */
export function useBranching(vault: string): Branching {
  const time = useTimeContext(vault)
  const { modules } = useActiveModules(vault)
  const enabled = modules.some((module) => module.id === 'branches')
  const tree = useTimelines(vault, time.dimensionId)
  const items = tree.data?.items
  const timelineId = time.timelineId
  return useMemo(() => {
    const nodes = items ?? []
    const timelines = flattenTimelines(nodes)
    const lineage = timelineId === null ? [] : lineageOf(nodes, timelineId)
    const names = new Map(timelines.map(({ node }) => [node.id, node.name]))
    return {
      enabled,
      timelineId,
      current: lineage[0]?.timeline ?? null,
      lineage,
      inBranch: lineage.length > 1,
      timelines,
      name: (id) => (id == null ? null : (names.get(id) ?? null)),
    }
  }, [enabled, items, timelineId])
}
