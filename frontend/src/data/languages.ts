import { useQuery } from '@tanstack/react-query'

import type { components } from '@/api'

import { useDataSource } from './context'
import type { Domain } from './domain'
import { keys } from './keys'

export type FamilyTree = Domain<components['schemas']['FamilyTree']>

/** The language family graph (of a dimension and the multiversal languages, or all). */
export function useLanguageFamilyTree(vault: string, dimension: string | null) {
  const source = useDataSource()
  const query = dimension === null ? {} : { dimension }
  return useQuery({
    queryKey: keys.languageFamilyTree(vault, query),
    queryFn: () => source.languageFamilyTree(vault, query),
  })
}
