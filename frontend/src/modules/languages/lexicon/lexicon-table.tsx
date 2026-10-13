import { useVirtualizer } from '@tanstack/react-virtual'
import { PencilIcon, PlusIcon, Trash2Icon } from 'lucide-react'
import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  useCreateLexiconEntry,
  useDeleteLexiconEntry,
  useLexicon,
  useMutations,
  useUpdateLexiconEntry,
  type LexiconEntry,
  type LexiconQuery,
} from '@/data'
import { cn } from '@/lib/utils'

import { cellText, columnChange, COLUMNS, PARTS_OF_SPEECH, type ColumnKey } from './fields'
import { IpaInput } from './ipa-palette'

const ROW_HEIGHT = 36
const PAGE_SIZE = 200
const GRID =
  'minmax(8rem,1.2fr) minmax(7rem,1fr) minmax(7rem,1fr) 7rem minmax(10rem,2fr) minmax(6rem,1fr) 4.5rem'
const SELECT_CLASS =
  'h-9 rounded-md border border-input bg-transparent px-2 text-sm shadow-xs focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none'
const SORTS = [
  { value: 'collation', label: 'Alphabet' },
  { value: 'headword', label: 'Headword' },
  { value: 'recent', label: 'Recently changed' },
] as const

function message(error: unknown): string {
  return error instanceof Error ? error.message : 'The change was not saved.'
}

/**
 * A language's lexicon (docs/modules/languages.md, UI): a virtualized table sorted by the
 * language's alphabet, filtered by a search, part of speech and tag. Authors type new words in the
 * entry row at the top (Enter adds and starts the next) and edit a cell in place (click or Enter
 * on it; Enter saves, Escape cancels); "Details" opens the full entry.
 */
export function LexiconTable({
  vault,
  language,
  onOpen,
  className,
}: {
  vault: string
  language: string
  onOpen: (entry: string) => void
  className?: string
}) {
  const editable = useMutations() !== null
  const [q, setQ] = useState('')
  const [pos, setPos] = useState('')
  const [tag, setTag] = useState('')
  const [sort, setSort] = useState<NonNullable<LexiconQuery['sort']>>('collation')
  const query: LexiconQuery = {
    sort,
    limit: PAGE_SIZE,
    ...(q.trim() ? { q: q.trim() } : {}),
    ...(pos ? { pos } : {}),
    ...(tag.trim() ? { tag: tag.trim() } : {}),
  }
  const lexicon = useLexicon(vault, language, query)
  const rows = lexicon.data?.pages.flatMap((page) => page.items) ?? []

  const scroller = useRef<HTMLDivElement>(null)
  // eslint-disable-next-line react-hooks/incompatible-library -- the virtualizer is read in render on purpose
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scroller.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 16,
    initialRect: { width: 960, height: 480 },
  })
  const items = virtualizer.getVirtualItems()
  const last = items.at(-1)?.index ?? -1
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = lexicon
  useEffect(() => {
    if (hasNextPage && !isFetchingNextPage && last >= rows.length - 40) void fetchNextPage()
  }, [last, rows.length, hasNextPage, isFetchingNextPage, fetchNextPage])

  const filtered = q.trim() !== '' || pos !== '' || tag.trim() !== ''
  return (
    <div className={cn('flex min-h-0 flex-col gap-3', className)}>
      <div role="search" className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`lexicon-q-${language}`}>Find</Label>
          <Input
            id={`lexicon-q-${language}`}
            type="search"
            placeholder="Word or gloss…"
            value={q}
            onChange={(event) => {
              setQ(event.target.value)
            }}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`lexicon-pos-${language}`}>Part of speech</Label>
          <select
            id={`lexicon-pos-${language}`}
            className={SELECT_CLASS}
            value={pos}
            onChange={(event) => {
              setPos(event.target.value)
            }}
          >
            <option value="">Any</option>
            {PARTS_OF_SPEECH.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`lexicon-tag-${language}`}>Tag</Label>
          <Input
            id={`lexicon-tag-${language}`}
            className="w-32"
            value={tag}
            onChange={(event) => {
              setTag(event.target.value)
            }}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`lexicon-sort-${language}`}>Sort</Label>
          <select
            id={`lexicon-sort-${language}`}
            className={SELECT_CLASS}
            value={sort}
            onChange={(event) => {
              setSort(event.target.value as typeof sort)
            }}
          >
            {SORTS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div
        role="table"
        aria-label="Lexicon"
        aria-rowcount={rows.length + 1}
        className="flex min-h-0 flex-1 flex-col rounded-md border text-sm"
      >
        <div
          role="row"
          className="grid border-b bg-muted/50 font-medium"
          style={{ gridTemplateColumns: GRID }}
        >
          {COLUMNS.map((column) => (
            <div key={column.key} role="columnheader" className="truncate px-2 py-2">
              {column.title}
            </div>
          ))}
          <div role="columnheader" className="px-2 py-2">
            <span className="sr-only">Actions</span>
          </div>
        </div>
        {editable && <EntryRow vault={vault} language={language} />}
        <div
          ref={scroller}
          className="min-h-40 flex-1 overflow-y-auto"
          data-testid="lexicon-scroller"
        >
          {lexicon.isPending ? (
            <p className="p-3 text-muted-foreground">Loading…</p>
          ) : rows.length === 0 ? (
            <p className="p-3 text-muted-foreground">
              {filtered ? 'No words match.' : 'No words yet.'}
            </p>
          ) : (
            <div
              role="rowgroup"
              style={{ height: virtualizer.getTotalSize(), position: 'relative' }}
            >
              {items.map((item) => {
                const entry = rows[item.index]
                if (entry === undefined) return null
                return (
                  <EntryRowView
                    key={entry.id}
                    vault={vault}
                    entry={entry}
                    index={item.index}
                    top={item.start}
                    editable={editable}
                    onOpen={onOpen}
                  />
                )
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function EntryRowView({
  vault,
  entry,
  index,
  top,
  editable,
  onOpen,
}: {
  vault: string
  entry: LexiconEntry
  index: number
  top: number
  editable: boolean
  onOpen: (entry: string) => void
}) {
  const remove = useOptionalDelete(vault, editable)
  return (
    <div
      role="row"
      aria-rowindex={index + 2}
      data-testid="lexicon-row"
      className="absolute inset-x-0 grid items-center border-b"
      style={{ gridTemplateColumns: GRID, height: ROW_HEIGHT, transform: `translateY(${top}px)` }}
    >
      {COLUMNS.map((column) => (
        <div key={column.key} role="cell" className="min-w-0 px-1">
          {editable ? (
            <EditableCell vault={vault} entry={entry} column={column.key} title={column.title} />
          ) : (
            <span className={cn('block truncate px-1', column.key === 'headword' && 'font-medium')}>
              {cellText(entry, column.key)}
            </span>
          )}
        </div>
      ))}
      <div role="cell" className="flex items-center justify-end gap-0.5 px-1">
        <Button
          variant="ghost"
          size="icon"
          className="size-7"
          aria-label={`Details of ${entry.headword}`}
          onClick={() => {
            onOpen(entry.id)
          }}
        >
          <PencilIcon className="size-3.5" />
        </Button>
        {remove && (
          <Button
            variant="ghost"
            size="icon"
            className="size-7"
            aria-label={`Delete ${entry.headword}`}
            onClick={() => {
              remove(entry)
            }}
          >
            <Trash2Icon className="size-3.5" />
          </Button>
        )}
      </div>
    </div>
  )
}

/** Deletes an entry (with a toast), or `null` for readers. */
function useOptionalDelete(vault: string, editable: boolean) {
  const mutation = useDeleteLexiconEntry(vault)
  if (!editable) return null
  return (entry: LexiconEntry) => {
    mutation.mutate(entry.id, {
      onSuccess: () => {
        toast(`Deleted “${entry.headword}” (Undo is in the history)`)
      },
      onError: (error) => {
        toast.error(message(error))
      },
    })
  }
}

/** A cell edited in place: click or Enter starts, Enter or leaving saves, Escape cancels. */
function EditableCell({
  vault,
  entry,
  column,
  title,
}: {
  vault: string
  entry: LexiconEntry
  column: ColumnKey
  title: string
}) {
  const update = useUpdateLexiconEntry(vault)
  const [draft, setDraft] = useState<string | null>(null)
  const text = cellText(entry, column)
  const save = () => {
    if (draft === null) return
    const body = columnChange(entry, column, draft)
    setDraft(null)
    if (body === null) return
    update.mutate(
      { id: entry.id, body },
      {
        onError: (error) => {
          toast.error(message(error))
        },
      },
    )
  }
  const keys = (event: KeyboardEvent) => {
    if (event.key === 'Enter') {
      event.preventDefault()
      save()
    } else if (event.key === 'Escape') {
      event.preventDefault()
      setDraft(null)
    }
  }
  if (draft !== null) {
    const label = `${title} of ${entry.headword}`
    return column === 'pronunciation' ? (
      <IpaInput
        aria-label={label}
        className="h-7"
        focusOnMount
        value={draft}
        onValue={setDraft}
        onKeyDown={keys}
        // The palette keeps the input's focus: leaving the input means done.
        onBlur={save}
      />
    ) : (
      <Input
        aria-label={label}
        className="h-7"
        ref={focusOnMount}
        value={draft}
        list={column === 'part_of_speech' ? 'lexicon-pos' : undefined}
        onChange={(event) => {
          setDraft(event.target.value)
        }}
        onKeyDown={keys}
        onBlur={save}
      />
    )
  }
  return (
    <button
      type="button"
      aria-label={`Edit ${title.toLowerCase()} of ${entry.headword}`}
      className={cn(
        'block h-7 w-full truncate rounded-sm px-1 text-left hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
        column === 'headword' && 'font-medium',
        update.isPending && 'opacity-60',
      )}
      onClick={() => {
        setDraft(text)
      }}
    >
      {text || <span className="text-muted-foreground">—</span>}
    </button>
  )
}

/** Focuses an input when it appears (a cell starting to edit). */
function focusOnMount(element: HTMLInputElement | null) {
  element?.focus()
}

const EMPTY = { headword: '', romanization: '', pronunciation: '', part_of_speech: '', gloss: '' }

/** The entry row: type a word, Tab through its columns, Enter adds it and starts the next. */
function EntryRow({ vault, language }: { vault: string; language: string }) {
  const create = useCreateLexiconEntry(vault, language)
  const [draft, setDraft] = useState(EMPTY)
  const firstId = useId()
  const set = (key: keyof typeof EMPTY) => (value: string) => {
    setDraft((current) => ({ ...current, [key]: value }))
  }
  const add = () => {
    const headword = draft.headword.trim()
    if (headword === '') return
    const optional = (value: string) => (value.trim() === '' ? null : value.trim())
    create.mutate(
      {
        headword,
        romanization: optional(draft.romanization),
        pronunciation: optional(draft.pronunciation),
        part_of_speech: optional(draft.part_of_speech),
        definitions: draft.gloss.trim() === '' ? [] : [{ gloss: draft.gloss.trim() }],
      },
      {
        onSuccess: () => {
          setDraft(EMPTY)
          document.getElementById(firstId)?.focus()
        },
        onError: (error) => {
          toast.error(message(error))
        },
      },
    )
  }
  const keys = (event: KeyboardEvent) => {
    if (event.key === 'Enter') {
      event.preventDefault()
      add()
    }
  }
  const input = (key: keyof typeof EMPTY, label: string) => ({
    'aria-label': `New entry: ${label}`,
    className: 'h-7',
    value: draft[key],
    onKeyDown: keys,
  })
  return (
    <div
      role="row"
      aria-label="New entry"
      className="grid items-center gap-0 border-b bg-muted/20 py-1"
      style={{ gridTemplateColumns: GRID }}
    >
      <div role="cell" className="px-1">
        <Input
          id={firstId}
          {...input('headword', 'headword')}
          placeholder="New word…"
          onChange={(event) => {
            set('headword')(event.target.value)
          }}
        />
      </div>
      <div role="cell" className="px-1">
        <Input
          {...input('romanization', 'romanization')}
          onChange={(event) => {
            set('romanization')(event.target.value)
          }}
        />
      </div>
      <div role="cell" className="px-1">
        <IpaInput {...input('pronunciation', 'pronunciation')} onValue={set('pronunciation')} />
      </div>
      <div role="cell" className="px-1">
        <Input
          {...input('part_of_speech', 'part of speech')}
          list="lexicon-pos"
          onChange={(event) => {
            set('part_of_speech')(event.target.value)
          }}
        />
        <datalist id="lexicon-pos">
          {PARTS_OF_SPEECH.map((value) => (
            <option key={value} value={value} />
          ))}
        </datalist>
      </div>
      <div role="cell" className="px-1">
        <Input
          {...input('gloss', 'gloss')}
          onChange={(event) => {
            set('gloss')(event.target.value)
          }}
        />
      </div>
      <div role="cell" />
      <div role="cell" className="flex justify-end px-1">
        <Button
          variant="ghost"
          size="icon"
          className="size-7"
          aria-label="Add the entry"
          disabled={draft.headword.trim() === '' || create.isPending}
          onClick={add}
        >
          <PlusIcon className="size-3.5" />
        </Button>
      </div>
    </div>
  )
}
