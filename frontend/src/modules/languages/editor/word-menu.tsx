import { useParams } from '@tanstack/react-router'
import { useImperativeHandle, useState, type Ref } from 'react'
import { createPortal } from 'react-dom'

import { useSearch } from '@/data'
import { cn } from '@/lib/utils'

const MAX_HITS = 8
const DOC_TYPE = 'languages.lexicon_entry'

export interface WordMenuHandle {
  onKeyDown: (event: KeyboardEvent) => boolean
}

export interface WordMenuProps {
  query: string
  rect: { left: number; bottom: number } | null
  onPick: (word: { entryId: string; languageId: string }) => void
  ref?: Ref<WordMenuHandle>
}

/**
 * The `@@` menu: lexicon entries whose headword, romanization or gloss starts with what was
 * typed (full-text search of `languages.lexicon_entry`). Arrow keys move, Enter or Tab picks.
 */
export function WordMenu({ query, rect, onPick, ref }: WordMenuProps) {
  const vault = useParams({ strict: false }).vault ?? ''
  const q = query.trim()
  const search = useSearch(vault, { q, kind: [DOC_TYPE], limit: MAX_HITS })
  const hits = q === '' ? [] : (search.data?.items ?? [])
  const [active, setActive] = useState(0)
  const selected = Math.min(active, Math.max(hits.length - 1, 0))
  const pick = (index: number) => {
    const hit = hits[index]
    if (hit === undefined) return false
    onPick({ entryId: hit.doc_id, languageId: hit.entity_id })
    return true
  }
  useImperativeHandle(ref, () => ({
    onKeyDown: (event) => {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        const step = event.key === 'ArrowDown' ? 1 : -1
        setActive((hits.length + selected + step) % Math.max(hits.length, 1))
        return true
      }
      if (event.key === 'Enter' || event.key === 'Tab') return pick(selected)
      return false
    },
  }))
  const style = rect ? { left: rect.left, top: rect.bottom + 4 } : undefined
  return createPortal(
    <div
      role="listbox"
      tabIndex={-1}
      aria-label="Insert a word"
      style={style}
      className="fixed z-50 w-72 overflow-hidden rounded-md border bg-popover p-1 text-sm text-popover-foreground shadow-md"
      onMouseDown={(event) => {
        event.preventDefault()
      }}
    >
      {q === '' && <p className="px-2 py-1.5 text-muted-foreground">Type a word or a gloss…</p>}
      {q !== '' && search.isPending && (
        <p className="px-2 py-1.5 text-muted-foreground">Searching…</p>
      )}
      {q !== '' && !search.isPending && hits.length === 0 && (
        <p className="px-2 py-1.5 text-muted-foreground">No word matches.</p>
      )}
      {hits.map((hit, index) => (
        <button
          key={hit.doc_id}
          type="button"
          role="option"
          aria-selected={index === selected}
          className={cn(
            'flex w-full flex-col rounded-sm px-2 py-1.5 text-left',
            index === selected && 'bg-accent text-accent-foreground',
          )}
          onMouseEnter={() => {
            setActive(index)
          }}
          onClick={() => {
            pick(index)
          }}
        >
          <span className="font-medium italic">{hit.name}</span>
          {hit.snippet && (
            <span className="truncate text-xs text-muted-foreground">
              {hit.snippet.parts.map((part) => part.text).join('')}
            </span>
          )}
        </button>
      ))}
    </div>,
    document.body,
  )
}
