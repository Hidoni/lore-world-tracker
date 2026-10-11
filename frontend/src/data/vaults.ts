import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap, type components } from '@/api'

/** A vault as listed by `GET /api/v1/vaults` (api.md §2 "Vaults & settings"). */
export type Vault = components['schemas']['Vault']
export type VaultList = components['schemas']['VaultList']

// Calls the typed client directly until the DataSource/Mutations layer lands (#59).
const VAULTS_KEY = ['vaults'] as const

export function useVaults() {
  return useQuery({
    queryKey: VAULTS_KEY,
    queryFn: () => unwrap(api.GET('/api/v1/vaults')),
    meta: { toast: false }, // the picker shows the error itself
  })
}

export function useVault(vaultId: string) {
  return useQuery({
    queryKey: [...VAULTS_KEY, vaultId],
    queryFn: () =>
      unwrap(api.GET('/api/v1/vaults/{vault_id}', { params: { path: { vault_id: vaultId } } })),
  })
}

export function useCreateVault() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => unwrap(api.POST('/api/v1/vaults', { body: { name } })),
    onSuccess: () => client.invalidateQueries({ queryKey: VAULTS_KEY }),
  })
}

export function useRenameVault() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) =>
      unwrap(
        api.PATCH('/api/v1/vaults/{vault_id}', {
          params: { path: { vault_id: id } },
          body: { name },
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: VAULTS_KEY }),
  })
}

/** Moves the vault to the data directory's trash (`DELETE`; the folder is never deleted). */
export function useDeleteVault() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await api.DELETE('/api/v1/vaults/{vault_id}', { params: { path: { vault_id: id } } })
    },
    onSuccess: () => client.invalidateQueries({ queryKey: VAULTS_KEY }),
  })
}
