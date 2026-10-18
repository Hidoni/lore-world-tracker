import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { readerUrl, type components } from '@/api'

import { useDataSource, useRequiredMutations } from './context'
import type { Domain } from './domain'
import { invalidateAffected } from './invalidate'
import { keys } from './keys'
import type { Query } from './source'
import { staticFileUrl } from './static-modules'

type Schemas = components['schemas']

export type FamilyTree = Domain<Schemas['FamilyTree']>
export type LexiconEntry = Domain<Schemas['LexiconEntryOut']>
export type LexiconImportReport = Schemas['ImportReport']
export type LexiconEntryUpdate = Schemas['LexiconEntryUpdate']
export type LexiconDefinition = Schemas['Definition']
export type EtymologySource = Schemas['EtymologySource']
/** A time point as request bodies take it. */
export type WireTimePoint = Schemas['TimePoint-Input']

/** The language family graph (of a dimension and the multiversal languages, or all). */
export function useLanguageFamilyTree(vault: string, dimension: string | null) {
  const source = useDataSource()
  const query = dimension === null ? {} : { dimension }
  return useQuery({
    queryKey: keys.languageFamilyTree(vault, query),
    queryFn: () => source.languageFamilyTree(vault, query),
  })
}

export type LexiconQuery = Omit<Query<'languages_lexicon_list'>, 'cursor'>

/** A language's lexicon, page by page (the table fetches the next page near its end). */
export function useLexicon(vault: string, language: string, query: LexiconQuery) {
  const source = useDataSource()
  return useInfiniteQuery({
    queryKey: keys.lexicon(vault, language, query),
    queryFn: ({ pageParam }) =>
      source.lexicon(vault, language, {
        ...query,
        ...(pageParam === null ? {} : { cursor: pageParam }),
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  })
}

/** One lexicon entry (`lexiconRef` nodes, the entry drawer); a 404 when it may not be seen. */
export function useLexiconEntry(vault: string, entry: string, options: { enabled?: boolean } = {}) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.lexiconEntry(vault, entry),
    queryFn: () => source.lexiconEntry(vault, entry),
    retry: false,
    enabled: options.enabled ?? true,
  })
}

export function useCreateLexiconEntry(vault: string, language: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['LexiconEntryCreate']) =>
      mutations.createLexiconEntry(vault, language, body),
    onSuccess: (result) => invalidateAffected(client, vault, result.affected),
  })
}

export function useUpdateLexiconEntry(vault: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Schemas['LexiconEntryUpdate'] }) =>
      mutations.updateLexiconEntry(vault, id, body),
    onSuccess: (result) => {
      client.setQueryData(keys.lexiconEntry(vault, result.entry.id), result.entry)
      return invalidateAffected(client, vault, result.affected)
    },
  })
}

export function useDeleteLexiconEntry(vault: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => mutations.deleteLexiconEntry(vault, id),
    onSuccess: (result) => invalidateAffected(client, vault, result.affected),
  })
}

/** CSV import: a dry run reports what would happen; a real one creates every row or none. */
export function useImportLexicon(vault: string, language: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ body, dryRun }: { body: Schemas['ImportIn']; dryRun: boolean }) =>
      mutations.importLexicon(vault, language, body, dryRun),
    onSuccess: async (report) => {
      if (report.affected) await invalidateAffected(client, vault, report.affected)
    },
  })
}

/** Where a language's lexicon downloads from as CSV (same origin; what the request may see). */
export function lexiconExportUrl(vault: string, language: string): string {
  return (
    staticFileUrl(`m/languages/${language}/lexicon/export`) ??
    readerUrl(
      `/api/v1/vaults/${encodeURIComponent(vault)}/m/languages/${encodeURIComponent(language)}/lexicon/export`,
    )
  )
}
