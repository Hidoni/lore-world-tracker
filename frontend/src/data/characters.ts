import { useQuery } from '@tanstack/react-query'

import type { components } from '@/api'

import { useDataSource } from './context'
import type { Domain } from './domain'
import { keys } from './keys'

type Schemas = components['schemas']

export type RelationshipGroup = Domain<Schemas['RelationshipGroup']>
export type LifeEvent = Domain<Schemas['LifeEvent']>

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
