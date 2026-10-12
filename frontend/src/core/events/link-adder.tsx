import { PlusIcon } from 'lucide-react'
import { useId, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useKindRegistry } from '@/core/registry'
import { useQuickSearch } from '@/data'

export interface Picked {
  id: string
  name: string
}

/**
 * Search for an entity to link (`/search/quick`, optionally limited to `kinds` and a dimension),
 * then a free-text detail (a role, a description) and Add. "Create “…”" offers a new entity
 * named after the search when `onCreate` is given.
 */
export function LinkAdder({
  vault,
  label,
  kinds,
  dimensionId,
  exclude,
  detail,
  pending,
  onAdd,
  onCreate,
}: {
  vault: string
  /** The search box's label ("Add a cause"). */
  label: string
  kinds?: readonly string[]
  dimensionId?: string | null
  /** Ids not offered (the entity itself, what is linked already). */
  exclude: ReadonlySet<string>
  detail: { label: string; placeholder?: string; suggestions?: readonly string[] }
  pending: boolean
  onAdd: (target: Picked, detail: string) => void
  onCreate?: (name: string) => void
}) {
  const id = useId()
  const registry = useKindRegistry(vault)
  const [query, setQuery] = useState('')
  const [target, setTarget] = useState<Picked | null>(null)
  const [text, setText] = useState('')
  const q = query.trim()
  const results = useQuickSearch(vault, {
    q,
    ...(kinds === undefined ? {} : { kind: [...kinds] }),
    ...(dimensionId == null ? {} : { dimension: dimensionId }),
  })
  const hits =
    q === '' ? [] : (results.data?.items ?? []).filter((hit) => !exclude.has(hit.entity_id))
  const reset = () => {
    setTarget(null)
    setQuery('')
    setText('')
  }

  if (target !== null) {
    return (
      <form
        className="flex flex-wrap items-center gap-2 text-sm"
        onSubmit={(event) => {
          event.preventDefault()
          onAdd(target, text.trim())
          reset()
        }}
      >
        <span className="font-medium">{target.name}</span>
        <Input
          aria-label={detail.label}
          placeholder={detail.placeholder}
          className="h-8 w-48"
          list={detail.suggestions === undefined ? undefined : `${id}-suggestions`}
          value={text}
          onChange={(event) => {
            setText(event.target.value)
          }}
        />
        {detail.suggestions !== undefined && (
          <datalist id={`${id}-suggestions`}>
            {detail.suggestions.map((suggestion) => (
              <option key={suggestion} value={suggestion} />
            ))}
          </datalist>
        )}
        <Button type="submit" size="sm" disabled={pending}>
          Add
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={reset}>
          Cancel
        </Button>
      </form>
    )
  }
  return (
    <div className="flex flex-col gap-1">
      <Input
        aria-label={label}
        placeholder={`${label}…`}
        className="h-8"
        value={query}
        onChange={(event) => {
          setQuery(event.target.value)
        }}
      />
      {q !== '' && (
        <ul aria-label={`${label}: results`} className="flex flex-col rounded-md border text-sm">
          {hits.map((hit) => (
            <li key={hit.entity_id}>
              <button
                type="button"
                className="flex w-full items-center gap-2 px-2 py-1 text-left hover:bg-accent"
                onClick={() => {
                  setTarget({ id: hit.entity_id, name: hit.name })
                }}
              >
                {hit.name}
                <span className="text-xs text-muted-foreground">
                  {registry?.kind(hit.kind)?.label ?? hit.kind}
                </span>
              </button>
            </li>
          ))}
          {onCreate !== undefined && (
            <li>
              <button
                type="button"
                className="flex w-full items-center gap-1 px-2 py-1 text-left hover:bg-accent"
                onClick={() => {
                  onCreate(q)
                  setQuery('')
                }}
              >
                <PlusIcon aria-hidden className="size-3.5" /> Create “{q}”
              </button>
            </li>
          )}
          {hits.length === 0 && onCreate === undefined && (
            <li className="px-2 py-1 text-muted-foreground">No matches.</li>
          )}
        </ul>
      )}
    </div>
  )
}
