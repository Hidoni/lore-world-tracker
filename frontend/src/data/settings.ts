import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type { components } from '@/api'

import { useDataSource, useRequiredMutations } from './context'
import { keys } from './keys'

type Schemas = components['schemas']

export function useSettings(vault: string) {
  const source = useDataSource()
  return useQuery({ queryKey: keys.settings(vault), queryFn: () => source.settings(vault) })
}

/** Changes vault settings (PATCH merges the members sent). */
export function useUpdateSettings(vault: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['VaultSettingsUpdate']) => mutations.updateSettings(vault, body),
    onSuccess: (settings) => {
      client.setQueryData(keys.settings(vault), settings)
    },
  })
}

export function useBackups(vault: string) {
  const source = useDataSource()
  return useQuery({ queryKey: keys.backups(vault), queryFn: () => source.backups(vault) })
}

export function useCreateBackup(vault: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['BackupCreate']) => mutations.createBackup(vault, body),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.backups(vault) }),
  })
}

/** Where a backup's zip downloads from (same origin; author-only). */
export function backupDownloadUrl(vault: string, id: string): string {
  return `/api/v1/vaults/${encodeURIComponent(vault)}/backups/${encodeURIComponent(id)}/download`
}

/** Restores a backup into a new vault, reporting the upload's progress. */
export function useRestoreBackup() {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ file, onProgress }: { file: Blob; onProgress: (fraction: number) => void }) =>
      mutations.restoreBackup(file, onProgress),
    meta: { toast: false }, // the backups page shows the error itself
    onSuccess: () => client.invalidateQueries({ queryKey: keys.vaults() }),
  })
}

/**
 * Enables or disables a module (modules.md §4). Its kinds, fields, link types and data appear or
 * disappear everywhere: every query of the vault is refreshed. `409 module_has_dependents` isn't
 * toasted (the modules page asks to cascade).
 */
export function useSetModule(vault: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ module, ...body }: { module: string } & Schemas['ModuleUpdate']) =>
      mutations.setModule(vault, module, body),
    meta: { toast: false },
    onSuccess: () => client.invalidateQueries({ queryKey: [vault] }),
  })
}

function useLinkTypesChanged(vault: string) {
  const client = useQueryClient()
  // Link types show in the registry and in every links list.
  return () =>
    Promise.all([
      client.invalidateQueries({ queryKey: keys.linkTypes(vault) }),
      client.invalidateQueries({ queryKey: keys.registry(vault) }),
      client.invalidateQueries({ queryKey: [vault, 'links'] }),
    ])
}

/** Custom link types (data-model.md §6.2): create, edit (incl. archive), delete. */
export function useCreateLinkType(vault: string) {
  const mutations = useRequiredMutations()
  const changed = useLinkTypesChanged(vault)
  return useMutation({
    mutationFn: (body: Schemas['LinkTypeCreate']) => mutations.createLinkType(vault, body),
    meta: { toast: false },
    onSuccess: changed,
  })
}

export function useUpdateLinkType(vault: string) {
  const mutations = useRequiredMutations()
  const changed = useLinkTypesChanged(vault)
  return useMutation({
    mutationFn: ({ key, body }: { key: string; body: Schemas['LinkTypeUpdate'] }) =>
      mutations.updateLinkType(vault, key, body),
    meta: { toast: false },
    onSuccess: changed,
  })
}

export function useDeleteLinkType(vault: string) {
  const mutations = useRequiredMutations()
  const changed = useLinkTypesChanged(vault)
  return useMutation({
    mutationFn: (key: string) => mutations.deleteLinkType(vault, key),
    meta: { toast: false },
    onSuccess: changed,
  })
}
