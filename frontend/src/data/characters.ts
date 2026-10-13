import { useQuery } from '@tanstack/react-query'

import type { components } from '@/api'

import { useDataSource } from './context'
import type { Domain } from './domain'
import { keys } from './keys'
import type { Query } from './source'

type Schemas = components['schemas']

export type RelationshipGroup = Domain<Schemas['RelationshipGroup']>
export type LifeEvent = Domain<Schemas['LifeEvent']>
export type Genealogy = Domain<Schemas['Genealogy']>
export type FamilyTreeQuery = Omit<Query<'characters_family_tree'>, 'as_reader'>

/** A character's family (ancestors, descendants, siblings, spouses) for the genealogy view. */
export function useCharacterFamilyTree(vault: string, character: string, query: FamilyTreeQuery) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.characterFamilyTree(vault, character, query),
    queryFn: () => source.characterFamilyTree(vault, character, query),
    placeholderData: (previous) => previous,
  })
}

/** A character's relationships by category (family, social, custom). */
export function useCharacterRelationships(vault: string, character: string) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.characterRelationships(vault, character),
    queryFn: () => source.characterRelationships(vault, character),
  })
}

/** The events on a timeline a character takes part in, by start. */
export function useCharacterLife(vault: string, character: string, timeline: string | null) {
  const source = useDataSource()
  const query = { timeline: timeline ?? '' }
  return useQuery({
    queryKey: keys.characterLife(vault, character, query),
    queryFn: () => source.characterLife(vault, character, query),
    enabled: timeline !== null,
    placeholderData: (previous) => previous,
  })
}
