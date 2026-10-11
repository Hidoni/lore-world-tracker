import type { Editor } from '@tiptap/core'
import { PlusIcon } from 'lucide-react'
import { useEffect, useState, useSyncExternalStore } from 'react'

import { cn } from '@/lib/utils'
import { useKindRegistry } from '@/core/registry'
import { useQuickSearch } from '@/data'

import { insertEntityLink } from './entity-link'
import type { SuggestionBridge, SuggestionState } from './suggestion-state'

const MAX_HITS = 8

interface Option {
  key: string
  label: string
  detail: string
  run: () => void
}

/**
 * The `[[` / `@` menu (frontend.md §6): entities whose names or aliases start with what was typed
 * (`/search/quick`), then "Create …" (opens the create dialog, then inserts the link). Arrow keys
 * move, Enter or Tab picks, Escape closes.
 */
export function SuggestionMenu({
  vault,
  editor,
  bridge,
  onCreate,
}: {
  vault: string
  editor: Editor
  bridge: SuggestionBridge
  onCreate: (name: string, state: SuggestionState) => void
}) {
  const state = useSyncExternalStore(bridge.subscribe, bridge.snapshot)
  if (state === null) return null
  return (
    <Menu
      // A new suggestion starts at the top.
      key={`${state.trigger}${state.range.from}`}
      vault={vault}
      editor={editor}
      bridge={bridge}
      state={state}
      onCreate={onCreate}
    />
  )
}

function Menu({
  vault,
  editor,
  bridge,
  state,
  onCreate,
}: {
  vault: string
  editor: Editor
  bridge: SuggestionBridge
  state: SuggestionState
  onCreate: (name: string, state: SuggestionState) => void
}) {
  const search = useQuickSearch(vault, { q: state.query })
  const registry = useKindRegistry(vault)
  const [active, setActive] = useState(0)

  const options: Option[] = (search.data?.items ?? []).slice(0, MAX_HITS).map((hit) => ({
    key: hit.entity_id,
    label: hit.name,
    detail: [hit.alias, registry?.kinds.find((kind) => kind.key === hit.kind)?.label]
      .filter(Boolean)
      .join(' · '),
    run: () => {
      bridge.publish(null)
      insertEntityLink(editor, state.range, { id: hit.entity_id, name: hit.name })
    },
  }))
  if (state.query !== '') {
    options.push({
      key: 'create',
      label: `Create “${state.query}” as…`,
      detail: 'New entity',
      run: () => {
        bridge.publish(null)
        onCreate(state.query, state)
      },
    })
  }
  const selected = Math.min(active, Math.max(options.length - 1, 0))

  useEffect(() => {
    bridge.handleKeys((event) => {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        const step = event.key === 'ArrowDown' ? 1 : -1
        setActive((options.length + selected + step) % Math.max(options.length, 1))
        return true
      }
      if (event.key === 'Enter' || event.key === 'Tab') {
        const option = options[selected]
        if (option === undefined) return false
        option.run()
        return true
      }
      return false
    })
    return () => {
      bridge.handleKeys(null)
    }
  })

  const style = state.rect ? { left: state.rect.left, top: state.rect.bottom + 4 } : undefined
  return (
    <div
      role="listbox"
      tabIndex={-1}
      aria-label="Link to an entity"
      style={style}
      className={cn(
        'z-50 w-72 overflow-hidden rounded-md border bg-popover p-1 text-sm text-popover-foreground shadow-md',
        style ? 'fixed' : 'absolute',
      )}
      // Keep the editor's selection while clicking.
      onMouseDown={(event) => {
        event.preventDefault()
      }}
    >
      {state.query === '' && (
        <p className="px-2 py-1.5 text-muted-foreground">Type a name to link…</p>
      )}
      {state.query !== '' && search.isPending && (
        <p className="px-2 py-1.5 text-muted-foreground">Searching…</p>
      )}
      {options.map((option, index) => (
        <button
          key={option.key}
          type="button"
          role="option"
          aria-selected={index === selected}
          className={cn(
            'flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left',
            index === selected && 'bg-accent text-accent-foreground',
          )}
          onMouseEnter={() => {
            setActive(index)
          }}
          onClick={option.run}
        >
          {option.key === 'create' && <PlusIcon aria-hidden className="size-4" />}
          <span className="truncate">{option.label}</span>
          {option.detail !== '' && (
            <span className="ml-auto truncate text-xs text-muted-foreground">{option.detail}</span>
          )}
        </button>
      ))}
    </div>
  )
}
