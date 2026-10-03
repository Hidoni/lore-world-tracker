/**
 * Tile-based fetching (frontend.md §9.2): at zoom level `z = floor(log2(D / span))` the moments
 * `[0, D]` are split into `2^z` tiles of `size = ceil((D + 1) / 2^z)` base units (the last one is
 * shorter). A tile is at least as long as the span, so a viewport overlaps one to three tiles, and
 * panning reuses them.
 */
import type { Viewport } from './viewport'

export interface Tiles {
  readonly z: number
  /** Length of each tile but possibly the last, in base units. */
  readonly size: bigint
  /** Indices of the tiles overlapping the viewport, in order (empty outside `[0, D]`). */
  readonly indices: readonly bigint[]
}

/** `[start, end)` of tile `index` at zoom level `z`, clipped to `[0, D + 1)`. */
export interface TileBounds {
  readonly start: bigint
  readonly end: bigint
}

/** Bits of a positive `n`. */
function bitLength(n: bigint): number {
  return n.toString(2).length
}

function sizeOf(z: number, D: bigint): bigint {
  const count = 1n << BigInt(z)
  return (D + count) / count // ceil((D + 1) / 2^z)
}

/** The zoom level and the tiles a viewport needs in a dimension of duration `D`. */
export function tileFor(v: Viewport, D: bigint): Tiles {
  const z = v.span >= D ? 0 : bitLength(D / v.span) - 1
  const size = sizeOf(z, D)
  const first = v.start < 0n ? 0n : v.start
  const end = v.start + v.span // exclusive
  const last = end > D + 1n ? D : end - 1n
  const indices: bigint[] = []
  for (let i = first / size; first <= last && i <= last / size; i++) indices.push(i)
  return { z, size, indices }
}

/** The moments of tile `index` at zoom level `z`. */
export function tileBounds(z: number, index: bigint, D: bigint): TileBounds {
  const size = sizeOf(z, D)
  const start = index * size
  const end = start + size
  return { start, end: end > D + 1n ? D + 1n : end }
}
