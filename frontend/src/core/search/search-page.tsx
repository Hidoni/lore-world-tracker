import { Link } from '@tanstack/react-router'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useExtensionRecord } from '@/core/modules'
import { useKindRegistry } from '@/core/registry'
import { useEntities, useSearchPages, type components } from '@/data'

type SearchHit = components['schemas']['SearchHit']
type Snippet = components['schemas']['Snippet']

export interface SearchParams {
  q?: string
  kind?: string
  dimension?: string
}

const PAGE_SIZE = 20
const SELECT_CLASS =
  'h-9 rounded-md border border-input bg-transparent px-2 text-sm shadow-xs focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none'
const SOURCE_LABEL: Record<Snippet['source'], string> = {
  aliases: 'in aliases',
  summary: 'in the summary',
  body: 'in the body',
  fields: 'in fields',
  extra: 'in details',
}

/** A snippet with its matches highlighted (module hit renderers use it too). */
export function SnippetText({ snippet }: { snippet: Snippet }) {
  return (
    <p className="text-sm text-muted-foreground">
      {snippet.parts.map((part, index) =>
        part.match ? (
          <mark
            key={index}
            className="rounded-sm bg-yellow-200/70 px-0.5 text-foreground dark:bg-yellow-500/30"
          >
            {part.text}
          </mark>
        ) : (
          <span key={index}>{part.text}</span>
        ),
      )}
      <span className="ml-2 text-xs">({SOURCE_LABEL[snippet.source]})</span>
    </p>
  )
}

/**
 * The search page (`/v/$vault/search`, frontend.md §4): a query (words, "phrases", OR, -word),
 * kind and dimension filters (kept in the URL), hits with highlighted snippets, module documents
 * through `searchResultRenderers`, and pages of results.
 */
export function SearchPage({
  vault,
  params,
  onChange,
}: {
  vault: string
  params: SearchParams
  onChange: (params: SearchParams) => void
}) {
  const registry = useKindRegistry(vault)
  const renderers = useExtensionRecord('searchResultRenderers', vault)
  const dimensions = useEntities(vault, { kind: ['dimension'], limit: 100 })
  const [draft, setDraft] = useState(params.q ?? '')
  const q = params.q?.trim() ?? ''
  const results = useSearchPages(vault, {
    q,
    limit: PAGE_SIZE,
    ...(params.kind ? { kind: [params.kind] } : {}),
    ...(params.dimension ? { dimension: params.dimension } : {}),
  })
  const hits = results.data?.pages.flatMap((page) => page.items) ?? []
  const set = (change: SearchParams) => {
    const next = { ...params, ...change }
    onChange(Object.fromEntries(Object.entries(next).filter(([, value]) => value)))
  }

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-4 p-6">
      <h1 className="text-2xl font-semibold">Search</h1>
      <form
        role="search"
        className="flex flex-wrap items-end gap-3"
        onSubmit={(event) => {
          event.preventDefault()
          set({ q: draft.trim() })
        }}
      >
        <div className="flex min-w-60 flex-1 flex-col gap-1.5">
          <Label htmlFor="search-query">Search for</Label>
          <Input
            id="search-query"
            type="search"
            placeholder='Words, "a phrase", a OR b, -word'
            value={draft}
            onChange={(event) => {
              setDraft(event.target.value)
            }}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="search-kind">Kind</Label>
          <select
            id="search-kind"
            className={SELECT_CLASS}
            value={params.kind ?? ''}
            onChange={(event) => {
              set({ kind: event.target.value })
            }}
          >
            <option value="">All kinds</option>
            {(registry?.kinds ?? []).map((kind) => (
              <option key={kind.key} value={kind.key}>
                {kind.plural}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="search-dimension">Dimension</Label>
          <select
            id="search-dimension"
            className={SELECT_CLASS}
            value={params.dimension ?? ''}
            onChange={(event) => {
              set({ dimension: event.target.value })
            }}
          >
            <option value="">All dimensions</option>
            {(dimensions.data?.items ?? []).map((dimension) => (
              <option key={dimension.id} value={dimension.id}>
                {dimension.name}
              </option>
            ))}
          </select>
        </div>
        <Button type="submit">Search</Button>
      </form>
      {q === '' && <p className="text-muted-foreground">Type something to search the vault.</p>}
      {q !== '' && results.isPending && <p className="text-muted-foreground">Searching…</p>}
      {q !== '' && !results.isPending && hits.length === 0 && (
        <p className="text-muted-foreground">Nothing matches “{q}”.</p>
      )}
      {hits.length > 0 && (
        <ol aria-label="Results" className="flex flex-col divide-y rounded-md border">
          {hits.map((hit) => {
            const Renderer = hit.doc_type === 'entity' ? undefined : renderers[hit.doc_type]
            return (
              <li key={`${hit.doc_type}:${hit.doc_id}`} className="p-3">
                {Renderer ? (
                  <Renderer vault={vault} hit={hit} />
                ) : (
                  <Hit vault={vault} hit={hit} kindLabel={registry?.kind(hit.kind)?.label} />
                )}
              </li>
            )
          })}
        </ol>
      )}
      {results.hasNextPage && (
        <Button
          variant="outline"
          className="self-center"
          disabled={results.isFetchingNextPage}
          onClick={() => {
            void results.fetchNextPage()
          }}
        >
          Show more results
        </Button>
      )}
    </div>
  )
}

function Hit({
  vault,
  hit,
  kindLabel,
}: {
  vault: string
  hit: SearchHit
  kindLabel: string | undefined
}) {
  const registry = useKindRegistry(vault)
  const kind = registry?.kind(hit.kind)
  const Icon = kind?.icon
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-2">
        {Icon && <Icon aria-hidden className="size-4" style={{ color: kind.color }} />}
        <Link
          to="/v/$vault/e/$entity"
          params={{ vault, entity: hit.entity_id }}
          className="font-medium hover:underline"
        >
          {hit.name}
        </Link>
        <span className="text-xs text-muted-foreground">
          {kindLabel ?? hit.kind}
          {hit.doc_type !== 'entity' && ` · ${hit.doc_type}`}
        </span>
      </div>
      {hit.snippet && <SnippetText snippet={hit.snippet} />}
    </div>
  )
}
