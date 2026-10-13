import { useQuery } from '@tanstack/react-query'

import type { components } from '@/api'

import { useDataSource } from './context'
import type { Domain } from './domain'
import { keys } from './keys'

export type DescentTree = Domain<components['schemas']['DescentTree']>

/** Everyone and everything of a species (`species.is_a`), at any time. */
export function useSpeciesMembers(vault: string, species: string) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.speciesMembers(vault, species),
    queryFn: () => source.speciesMembers(vault, species),
  })
}

/** The species descent graph (of a dimension and the multiversal species, or all). */
export function useSpeciesDescentTree(vault: string, dimension: string | null) {
  const source = useDataSource()
  const query = dimension === null ? {} : { dimension }
  return useQuery({
    queryKey: keys.speciesDescentTree(vault, query),
    queryFn: () => source.speciesDescentTree(vault, query),
  })
}
