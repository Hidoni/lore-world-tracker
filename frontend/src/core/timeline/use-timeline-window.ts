import { tileBounds, tileFor, toPx, type Viewport } from '@lore/chronology/viewport'
import { useEffect, useState } from 'react'

import { useWindowTiles, type TimelineWindow, type WindowFilters, type WindowTile } from '@/data'

/** The most items a tile asks for: the server caps a window at 2,000 (api.md). */
const MAX_TILE_PX = 2000

export type WindowItem = TimelineWindow['items'][number]
export type WindowBucket = TimelineWindow['buckets'][number]
export type SeriesBand = TimelineWindow['series_bands'][number]

export interface MergedWindow {
  items: WindowItem[]
  buckets: WindowBucket[]
  bands: SeriesBand[]
  /** Events overlapping the tiles, and those left out of `items` (density). */
  total: number
  culled: number
}

const EMPTY: MergedWindow = { items: [], buckets: [], bands: [], total: 0, culled: 0 }

/** An item's identity across tiles: its row and, for occurrences, its key. */
export function itemKey(item: Pick<WindowItem, 'row_id' | 'occurrence_key'>): string {
  return item.occurrence_key === null ? item.row_id : `${item.row_id}#${item.occurrence_key}`
}

/** The tiles a viewport needs (frontend.md §9.2), each with a pixel budget for its width. */
export function windowTiles(
  v: Viewport,
  D: bigint,
): { tiles: WindowTile[]; neighbours: WindowTile[] } {
  const { z, size, indices } = tileFor(v, D)
  // A tile's width in pixels at this zoom (a tile is at least as long as the view).
  const px = Math.round(toPx(v, v.start + size) - toPx(v, v.start))
  const budget = Math.max(1, Math.min(MAX_TILE_PX, px))
  const tile = (index: bigint): WindowTile => {
    const bounds = tileBounds(z, index, D)
    return { key: `${z}:${index}`, from: bounds.start, to: bounds.end, px: budget }
  }
  const count = 1n << BigInt(z)
  const first = indices[0]
  const last = indices.at(-1)
  const neighbours =
    first === undefined || last === undefined
      ? []
      : [first - 1n, last + 1n].filter((index) => index >= 0n && index < count).map(tile)
  return { tiles: indices.map(tile), neighbours }
}

/** Tiles merged: items once each (an event spanning tiles comes in each), bands joined. */
export function mergeTiles(windows: readonly TimelineWindow[]): MergedWindow {
  const items = new Map<string, WindowItem>()
  const bands = new Map<string, SeriesBand>()
  const buckets: WindowBucket[] = []
  let total = 0
  let culled = 0
  for (const window of windows) {
    for (const item of window.items) items.set(itemKey(item), item)
    for (const band of window.series_bands) {
      const known = bands.get(band.row_id)
      bands.set(
        band.row_id,
        known === undefined
          ? band
          : {
              ...known,
              from: known.from < band.from ? known.from : band.from,
              to: known.to > band.to ? known.to : band.to,
              // Tiles don't overlap: their counts add up.
              estimated_count: known.estimated_count + band.estimated_count,
            },
      )
    }
    buckets.push(...window.buckets)
    total += window.total
    culled += window.culled
  }
  return { items: [...items.values()], buckets, bands: [...bands.values()], total, culled }
}

/**
 * The merged window, kept while its tiles' results stay the same objects (so views memoizing on
 * it don't redo their work every render) and shown while new tiles load.
 */
class LastComplete {
  private tiles: readonly TimelineWindow[] = []
  private value: MergedWindow = EMPTY

  merge(tiles: readonly TimelineWindow[]): MergedWindow {
    const same =
      tiles.length === this.tiles.length && tiles.every((tile, at) => tile === this.tiles[at])
    if (!same) {
      this.tiles = tiles
      this.value = mergeTiles(tiles)
    }
    return this.value
  }

  get(): MergedWindow {
    return this.value
  }
}

/**
 * The events of the timeline around the viewport (frontend.md §9.2): the tiles it overlaps at its
 * zoom level, fetched and cached per tile (the neighbours prefetched), merged. While new tiles
 * load, the last complete result stays on screen.
 */
export function useTimelineWindow(
  vault: string,
  timelineId: string | null,
  v: Viewport,
  D: bigint,
  filters: WindowFilters = {},
): { window: MergedWindow; loading: boolean } {
  const { tiles, neighbours } = windowTiles(v, D)
  const { results, prefetch } = useWindowTiles(vault, timelineId, tiles, filters)
  const [last] = useState(() => new LastComplete())
  const neighbourKey = neighbours.map((tile) => tile.key).join(',')
  useEffect(() => {
    for (const tile of neighbours) prefetch(tile)
    // The neighbours change with the tiles, which the key names.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [neighbourKey, timelineId])
  const loaded = results.flatMap((result) => (result.data === undefined ? [] : [result.data]))
  const complete = loaded.length === results.length
  const merged = complete ? last.merge(loaded) : last.get()
  return { window: merged, loading: !complete }
}
