import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type { components } from '@/api'

import { useDataSource, useRequiredMutations } from './context'
import type { Domain } from './domain'
import { invalidateAffected } from './invalidate'
import { keys } from './keys'

type Schemas = components['schemas']

export type CustomField = Domain<Schemas['CustomFieldOut']>
export type CustomKind = Domain<Schemas['CustomKindOut']>
type Affected = Domain<Schemas['Affected']>

/** The custom fields (of a kind: its own and those of every kind), by kind then order. */
export function useCustomFields(vault: string, kind?: string) {
  const source = useDataSource()
  const query = kind === undefined ? {} : { kind }
  return useQuery({
    queryKey: keys.customFields(vault, query),
    queryFn: () => source.customFields(vault, query),
  })
}

/** The custom kinds (archived ones too). */
export function useCustomKinds(vault: string) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.customKinds(vault),
    queryFn: () => source.customKinds(vault),
  })
}

/**
 * Custom fields and kinds are part of the registry (kinds, their fields): a change refreshes it,
 * both lists, and whatever the write touched (values moved by a type change, entities of an
 * archived kind).
 */
function useChanged(vault: string) {
  const client = useQueryClient()
  return (affected?: Affected) =>
    Promise.all([
      client.invalidateQueries({ queryKey: keys.registry(vault) }),
      client.invalidateQueries({ queryKey: [vault, 'customFields'] }),
      client.invalidateQueries({ queryKey: keys.customKinds(vault) }),
      affected === undefined ? null : invalidateAffected(client, vault, affected),
    ])
}

// Errors (`422` paths, `409` conflicts) show in the dialogs: no toasts.
const META = { toast: false }

export function useCreateCustomField(vault: string) {
  const mutations = useRequiredMutations()
  const changed = useChanged(vault)
  return useMutation({
    mutationFn: (body: Schemas['CustomFieldCreate']) => mutations.createCustomField(vault, body),
    meta: META,
    onSuccess: (result) => changed(result.affected),
  })
}

export function useUpdateCustomField(vault: string) {
  const mutations = useRequiredMutations()
  const changed = useChanged(vault)
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Schemas['CustomFieldUpdate'] }) =>
      mutations.updateCustomField(vault, id, body),
    meta: META,
    onSuccess: (result) => changed(result.affected),
  })
}

/** Deletes a field; one with values needs `deleteValues` (`409 conflict` otherwise). */
export function useDeleteCustomField(vault: string) {
  const mutations = useRequiredMutations()
  const changed = useChanged(vault)
  return useMutation({
    mutationFn: ({ id, deleteValues = false }: { id: string; deleteValues?: boolean }) =>
      mutations.deleteCustomField(vault, id, deleteValues),
    meta: META,
    onSuccess: (result) => changed(result.affected),
  })
}

export function useReorderCustomFields(vault: string) {
  const mutations = useRequiredMutations()
  const changed = useChanged(vault)
  return useMutation({
    mutationFn: (body: Schemas['FieldReorder']) => mutations.reorderCustomFields(vault, body),
    onSuccess: () => changed(),
  })
}

export function useCreateCustomKind(vault: string) {
  const mutations = useRequiredMutations()
  const changed = useChanged(vault)
  return useMutation({
    mutationFn: (body: Schemas['CustomKindCreate']) => mutations.createCustomKind(vault, body),
    meta: META,
    onSuccess: (result) => changed(result.affected),
  })
}

export function useUpdateCustomKind(vault: string) {
  const mutations = useRequiredMutations()
  const changed = useChanged(vault)
  return useMutation({
    mutationFn: ({ key, body }: { key: string; body: Schemas['CustomKindUpdate'] }) =>
      mutations.updateCustomKind(vault, key, body),
    meta: META,
    onSuccess: (result) => changed(result.affected),
  })
}

/** Deletes an unused kind (`409 conflict` while entities have it). */
export function useDeleteCustomKind(vault: string) {
  const mutations = useRequiredMutations()
  const changed = useChanged(vault)
  return useMutation({
    mutationFn: (key: string) => mutations.deleteCustomKind(vault, key),
    meta: META,
    onSuccess: (result) => changed(result.affected),
  })
}
