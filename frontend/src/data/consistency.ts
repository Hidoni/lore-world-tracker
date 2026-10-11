import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type { components } from '@/api'

import { useDataSource, useRequiredMutations } from './context'
import { keys } from './keys'
import type { Query } from './source'

type Schemas = components['schemas']

/** Consistency findings (author-only: readers get `404`); `enabled: false` skips the fetch. */
export function useFindings(
  vault: string,
  query: Query<'consistency_findings'> = {},
  options: { enabled?: boolean } = {},
) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.findings(vault, query),
    queryFn: () => source.findings(vault, query),
    enabled: options.enabled ?? true,
    meta: { toast: false },
  })
}

/** Findings page by page (the panel's "Show more"). */
export function useFindingPages(vault: string, query: Query<'consistency_findings'> = {}) {
  const source = useDataSource()
  return useInfiniteQuery({
    queryKey: [...keys.findings(vault, query), 'paged'],
    queryFn: ({ pageParam }) =>
      source.findings(vault, { ...query, ...(pageParam === null ? {} : { cursor: pageParam }) }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  })
}

export function useConsistencyRules(vault: string) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.consistencyRules(vault),
    queryFn: () => source.consistencyRules(vault),
  })
}

/** Findings and rule counts change together. */
function useRefreshConsistency(vault: string) {
  const queryClient = useQueryClient()
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: [vault, 'findings'] }),
      queryClient.invalidateQueries({ queryKey: keys.consistencyRules(vault) }),
    ])
}

/** Sets a rule's severity (`null`: back to its default). */
export function useUpdateConsistencyRule(vault: string) {
  const mutations = useRequiredMutations()
  const refresh = useRefreshConsistency(vault)
  return useMutation({
    mutationFn: ({
      rule,
      severity,
    }: {
      rule: string
      severity: Schemas['RuleUpdate']['severity']
    }) => mutations.updateConsistencyRule(vault, rule, { severity }),
    onSuccess: refresh,
  })
}

export function useSuppressFinding(vault: string) {
  const mutations = useRequiredMutations()
  const refresh = useRefreshConsistency(vault)
  return useMutation({
    mutationFn: (body: Schemas['SuppressionIn']) => mutations.suppressFinding(vault, body),
    onSuccess: refresh,
  })
}

export function useUnsuppressFinding(vault: string) {
  const mutations = useRequiredMutations()
  const refresh = useRefreshConsistency(vault)
  return useMutation({
    mutationFn: (fingerprint: string) => mutations.unsuppressFinding(vault, fingerprint),
    onSuccess: refresh,
  })
}

/** Re-checks the whole vault against every rule. */
export function useScanConsistency(vault: string) {
  const mutations = useRequiredMutations()
  const refresh = useRefreshConsistency(vault)
  return useMutation({
    mutationFn: () => mutations.scanConsistency(vault),
    onSuccess: refresh,
  })
}
