import { Link } from '@tanstack/react-router'
import { BookIcon } from 'lucide-react'

import type { SearchHitProps } from '@/core/modules'
import { SnippetText } from '@/core/search'
import { useEntity, type components } from '@/data'

type SearchHit = components['schemas']['SearchHit']

/** A lexicon entry in search results: the headword, its language, and the matching text. */
export function LexiconHit({ vault, hit: raw }: SearchHitProps) {
  const hit = raw as SearchHit
  const language = useEntity(vault, hit.entity_id)
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-2">
        <BookIcon aria-hidden className="size-4" />
        <Link
          to="/v/$vault/m/$module/$"
          params={{ vault, module: 'languages', _splat: `${hit.entity_id}/lexicon` }}
          className="font-medium italic hover:underline"
        >
          {hit.name}
        </Link>
        <span className="text-xs text-muted-foreground">
          Word{language.data ? ` · ${language.data.name}` : ''}
        </span>
      </div>
      {hit.snippet && <SnippetText snippet={hit.snippet} />}
    </div>
  )
}
