import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useDataSource, useRequiredMutations } from './context'
import { keys } from './keys'

export type { Vault, VaultList } from './source'

export function useVaults() {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.vaults(),
    queryFn: () => source.vaults(),
    meta: { toast: false }, // the picker shows the error itself
  })
}

export function useVault(vault: string) {
  const source = useDataSource()
  return useQuery({ queryKey: keys.vault(vault), queryFn: () => source.vault(vault) })
}

function useVaultListChange() {
  const client = useQueryClient()
  return () => client.invalidateQueries({ queryKey: keys.vaults() })
}

export function useCreateVault() {
  const mutations = useRequiredMutations()
  const changed = useVaultListChange()
  return useMutation({
    mutationFn: (name: string) => mutations.createVault(name),
    onSuccess: changed,
  })
}

export function useRenameVault() {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  const changed = useVaultListChange()
  return useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => mutations.renameVault(id, name),
    onSuccess: async (_vault, { id }) => {
      await Promise.all([changed(), client.invalidateQueries({ queryKey: keys.vault(id) })])
    },
  })
}

/**
 * Upgrades a vault's database to this app's schema (persistence-and-migrations.md: with
 * `LORE_AUTO_MIGRATE=false`, a vault needing it waits for this). A backup is taken first.
 */
export function useMigrateVault() {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  const changed = useVaultListChange()
  return useMutation({
    mutationFn: (id: string) => mutations.migrateVault(id),
    onSuccess: async (_result, id) => {
      await Promise.all([changed(), client.invalidateQueries({ queryKey: keys.vault(id) })])
    },
  })
}

/** Moves the vault to the data directory's trash (the folder is never deleted). */
export function useDeleteVault() {
  const mutations = useRequiredMutations()
  const changed = useVaultListChange()
  return useMutation({ mutationFn: (id: string) => mutations.deleteVault(id), onSuccess: changed })
}
