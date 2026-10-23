import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useRequiredMutations } from './context'
import { keys } from './keys'

/**
 * The server's token for AI assistants (docs/modules/mcp.md): author-only, so it is read through
 * the mutations (absent for readers and static exports).
 */
export function useMcpToken(vault: string) {
  const mutations = useRequiredMutations()
  return useQuery({
    queryKey: keys.mcpToken(vault),
    queryFn: () => mutations.mcpToken(vault),
    staleTime: Infinity,
  })
}

/** Regenerates the token (the old one stops working at once). */
export function useRegenerateMcpToken(vault: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => mutations.regenerateMcpToken(vault),
    onSuccess: (token) => {
      client.setQueryData(keys.mcpToken(vault), token)
    },
  })
}
