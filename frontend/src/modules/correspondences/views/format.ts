import { formatAbsolute } from '@lore/chronology'
import { useCallback } from 'react'

import { formatIn, useDisplayLens } from '@/core/time'

/** Moments of a dimension as text in its display calendar (base units until it has loaded). */
export function useMomentFormat(vault: string, dimensionId: string | null) {
  const { dimension, lenses, lens } = useDisplayLens(vault, dimensionId)
  return useCallback(
    (t: bigint): string => {
      if (dimension === null || lens === null)
        return formatAbsolute(t, { singular: 'unit', plural: 'units', abbr: '' })
      return (
        formatIn(lens, { t, precision: 'base' }, dimension, lenses) ??
        formatAbsolute(t, dimension.baseUnit)
      )
    },
    [dimension, lens, lenses],
  )
}

export const SELECT_CLASS =
  'h-9 w-full rounded-md border border-input bg-transparent px-2 text-sm shadow-xs focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none'
