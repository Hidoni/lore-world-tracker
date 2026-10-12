/** An item to place: its pixel extent and a stable key (entity id, occurrence key). */
export interface LaneItem {
  key: string
  x0: number
  x1: number
}

export interface Packing {
  /** Lane per item key (0 = top). */
  lanes: Map<string, number>
  count: number
}

/** Room left for a label after short items, and between items in a lane. */
export const MIN_LABEL_PX = 96
export const GAP_PX = 4

/** One lane's occupied intervals `[x0, end)`, sorted by `x0`, never overlapping. */
type Lane = [number, number][]

/** The index of the first interval starting at or after `x`. */
function lowerBound(lane: Lane, x: number): number {
  let lo = 0
  let hi = lane.length
  while (lo < hi) {
    const mid = (lo + hi) >> 1
    const interval = lane[mid]
    if (interval !== undefined && interval[0] < x) lo = mid + 1
    else hi = mid
  }
  return lo
}

/** Whether `[x0, end)` fits in the lane (with the gap); inserts it if so. */
function take(lane: Lane, x0: number, end: number): boolean {
  const at = lowerBound(lane, x0)
  const before = lane[at - 1]
  const after = lane[at]
  if (before !== undefined && before[1] + GAP_PX > x0) return false
  if (after !== undefined && end + GAP_PX > after[0]) return false
  lane.splice(at, 0, [x0, end])
  return true
}

/**
 * Greedy interval partitioning (frontend.md §9.3): items by start, each in the first lane where
 * it fits, an item taking its lane until its end or its label's minimum width. **Sticky**: items
 * of the previous packing (`previous`) are placed first, in their old lanes where those are still
 * free, so panning and zooming keep items where they were and new items fill the gaps.
 */
export function packLanes(
  items: readonly LaneItem[],
  previous: ReadonlyMap<string, number> = new Map(),
): Packing {
  const sorted = [...items].sort((a, b) => a.x0 - b.x0 || a.key.localeCompare(b.key))
  const lanes: Lane[] = []
  /** Lane `index`, created (with any before it) if needed. */
  const laneAt = (index: number): Lane => {
    for (;;) {
      const lane = lanes[index]
      if (lane !== undefined) return lane
      lanes.push([])
    }
  }
  const placed = new Map<string, number>()
  const end = (item: LaneItem) => Math.max(item.x1, item.x0 + MIN_LABEL_PX)
  const rest: LaneItem[] = []
  for (const item of sorted) {
    const wanted = previous.get(item.key)
    if (wanted === undefined) {
      rest.push(item)
      continue
    }
    if (take(laneAt(wanted), item.x0, end(item))) placed.set(item.key, wanted)
    else rest.push(item)
  }
  for (const item of rest) {
    let lane = 0
    while (!take(laneAt(lane), item.x0, end(item))) lane++
    placed.set(item.key, lane)
  }
  // An old lane no item took again doesn't count at the bottom.
  let count = lanes.length
  while (count > 0 && lanes[count - 1]?.length === 0) count--
  return { lanes: placed, count }
}

/**
 * Packs lanes remembering the previous packing (one per view), so each call is sticky to the
 * last.
 */
export class StickyLanes {
  private previous: ReadonlyMap<string, number> = new Map()

  pack(items: readonly LaneItem[]): Packing {
    const result = packLanes(items, this.previous)
    this.previous = result.lanes
    return result
  }
}
