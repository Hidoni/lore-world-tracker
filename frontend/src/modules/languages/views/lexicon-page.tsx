import { Link, useParams } from '@tanstack/react-router'

import { useEntity } from '@/data'

import { Lexicon } from '../lexicon/lexicon'

/** The full-width lexicon of a language (`/m/languages/<language>/lexicon`). */
export default function LexiconPage() {
  // Module routes aren't in the router's generated types.
  const params: { vault?: string; language?: string } = useParams({ strict: false })
  const vault = params.vault ?? ''
  const language = params.language ?? ''
  const entity = useEntity(vault, language)
  return (
    <div className="mx-auto flex h-full max-w-7xl flex-col gap-4 p-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold">
          Lexicon{entity.data ? ` of ${entity.data.name}` : ''}
        </h1>
        {entity.data && (
          <Link
            to="/v/$vault/e/$entity"
            params={{ vault, entity: language }}
            className="text-sm text-primary underline-offset-2 hover:underline"
          >
            Back to {entity.data.name}
          </Link>
        )}
      </header>
      {entity.isError ? (
        <p className="text-muted-foreground">This language was not found.</p>
      ) : (
        <Lexicon vault={vault} language={language} full />
      )}
    </div>
  )
}
