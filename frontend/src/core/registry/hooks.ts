import { useParams } from '@tanstack/react-router'
import { useMemo } from 'react'

import { useActiveModules } from '@/core/modules/context'
import { useRegistry } from '@/data'

import { buildKindRegistry, type Kind, type KindRegistry, type LinkType } from './kind-registry'

/** The KindRegistry of a vault (the current route's by default); `undefined` while loading. */
export function useKindRegistry(vault?: string): KindRegistry | undefined {
  const params = useParams({ strict: false })
  const id = vault ?? params.vault
  const registry = useRegistry(id ?? '', { enabled: id !== undefined })
  const { modules } = useActiveModules(id)
  const data = registry.data
  return useMemo(
    () => (data === undefined ? undefined : buildKindRegistry(data, modules)),
    [data, modules],
  )
}

export function useKind(kind: string, vault?: string): Kind | undefined {
  return useKindRegistry(vault)?.kind(kind)
}

export function useLinkType(key: string, vault?: string): LinkType | undefined {
  return useKindRegistry(vault)?.linkType(key)
}
