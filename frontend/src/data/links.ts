import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type { components } from '@/api'

import { useDataSource, useRequiredMutations } from './context'
import { invalidateAffected } from './invalidate'
import { keys } from './keys'
import type { Query } from './source'

type Schemas = components['schemas']

export function useLinks(vault: string, id: string, query: Query<'entities_links'> = {}) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.links(vault, id, query),
    queryFn: () => source.links(vault, id, query),
  })
}

export function useBacklinks(vault: string, id: string, query: Query<'entities_backlinks'> = {}) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.backlinks(vault, id, query),
    queryFn: () => source.backlinks(vault, id, query),
  })
}

export function useLinkTypes(vault: string) {
  const source = useDataSource()
  return useQuery({ queryKey: keys.linkTypes(vault), queryFn: () => source.linkTypes(vault) })
}

export function useCreateLink(vault: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['LinkCreate']) => mutations.createLink(vault, body),
    onSuccess: (result) => invalidateAffected(client, vault, result.affected),
  })
}

export function useUpdateLink(vault: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Schemas['LinkUpdate'] }) =>
      mutations.updateLink(vault, id, body),
    onSuccess: (result) => invalidateAffected(client, vault, result.affected),
  })
}

export function useDeleteLink(vault: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => mutations.deleteLink(vault, id),
    onSuccess: (result) => invalidateAffected(client, vault, result.affected),
  })
}
