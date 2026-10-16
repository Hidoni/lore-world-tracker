import { Link, useParams } from '@tanstack/react-router'
import { DownloadIcon, RotateCcwIcon, TrashIcon, UploadIcon, XIcon } from 'lucide-react'
import { useRef, useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { Textarea } from '@/components/ui/textarea'
import {
  mediaFileUrl,
  useEntity,
  useMediaItem,
  useMediaItems,
  useMutations,
  useQuickSearch,
  useReplaceMediaFile,
  useRestoreMedia,
  useTrashMedia,
  useUpdateMedia,
  type MediaItem,
  type MediaQuery,
} from '@/data'

import { MediaImage } from '../components/media-image'
import { ANY_ACCEPT, IMAGE_ACCEPT, UploadButton, uploadProblem } from '../components/upload-button'

const PAGE = 100
const TYPES: readonly { label: string; mime: string }[] = [
  { label: 'All types', mime: '' },
  { label: 'Images', mime: 'image/' },
  { label: 'PDFs', mime: 'application/pdf' },
  { label: 'Text', mime: 'text/' },
]
const CONTEXTS: Record<string, string> = {
  body: 'page',
  cover: 'cover',
  gallery: 'gallery',
  map: 'map',
  note: 'note',
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${String(bytes)} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`
}

function contextLabel(context: string): string {
  return CONTEXTS[context] ?? (context.startsWith('field:') ? `field ${context.slice(6)}` : context)
}

/**
 * The media library (`/m/media/library`, docs/modules/media.md, UI): every file of the vault as a
 * grid, filtered by text, type, use (unused, or used by an entity) or the trash. Authors upload,
 * edit alt text and captions, replace files, and move them to the trash one by one or in bulk.
 */
export default function LibraryPage() {
  const vault = useParams({ strict: false }).vault ?? ''
  const editable = useMutations() !== null
  const [q, setQ] = useState('')
  const [mime, setMime] = useState('')
  const [unused, setUnused] = useState(false)
  const [trashed, setTrashed] = useState(false)
  const [entity, setEntity] = useState<{ id: string; name: string } | null>(null)
  const [limit, setLimit] = useState(PAGE)
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set())
  const [open, setOpen] = useState<string | null>(null)
  const query: MediaQuery = {
    limit,
    ...(q.trim() === '' ? {} : { q: q.trim() }),
    ...(mime === '' ? {} : { mime }),
    ...(unused ? { unused: true } : {}),
    ...(trashed ? { trashed: true } : {}),
    ...(entity === null ? {} : { entity: entity.id }),
  }
  const items = useMediaItems(vault, query)
  const list = items.data?.items ?? []
  const trash = useTrashMedia(vault)
  const restore = useRestoreMedia(vault)
  const bulk = async () => {
    const ids = [...selected]
    const run = trashed ? restore : trash
    const results = await Promise.allSettled(ids.map((id) => run.mutateAsync(id)))
    const failures = results.filter((result) => result.status === 'rejected').length
    if (failures > 0) toast.error(`${String(failures)} of ${String(ids.length)} weren't changed.`)
    setSelected(new Set())
  }
  const toggle = (id: string, on: boolean) => {
    const next = new Set(selected)
    if (on) next.add(id)
    else next.delete(id)
    setSelected(next)
  }
  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-4 p-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold">Media library</h1>
        {editable && (
          <div className="ml-auto">
            <UploadButton
              vault={vault}
              accept={ANY_ACCEPT}
              multiple
              label="Upload files"
              variant="default"
              onUploaded={() => undefined}
            />
          </div>
        )}
      </div>
      <div role="search" aria-label="Filters" className="flex flex-wrap items-center gap-3 text-sm">
        <Input
          type="search"
          aria-label="Search"
          placeholder="Name, alt text or caption"
          className="w-64"
          value={q}
          onChange={(event) => {
            setQ(event.target.value)
          }}
        />
        <select
          aria-label="Type"
          className="h-9 rounded-md border bg-transparent px-2"
          value={mime}
          onChange={(event) => {
            setMime(event.target.value)
          }}
        >
          {TYPES.map((type) => (
            <option key={type.mime} value={type.mime}>
              {type.label}
            </option>
          ))}
        </select>
        <label className="flex items-center gap-1">
          <input
            type="checkbox"
            checked={unused}
            onChange={(event) => {
              setUnused(event.target.checked)
            }}
          />
          Unused only
        </label>
        <label className="flex items-center gap-1">
          <input
            type="checkbox"
            checked={trashed}
            onChange={(event) => {
              setTrashed(event.target.checked)
              setSelected(new Set())
            }}
          />
          Trash
        </label>
        <EntityFilter vault={vault} entity={entity} onChange={setEntity} />
      </div>
      {editable && selected.size > 0 && (
        <div className="flex items-center gap-3 rounded-md border bg-muted/50 px-3 py-2 text-sm">
          {String(selected.size)} selected
          <Button size="sm" variant="outline" onClick={() => void bulk()}>
            {trashed ? <RotateCcwIcon aria-hidden /> : <TrashIcon aria-hidden />}
            {trashed ? 'Restore' : 'Move to the trash'}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              setSelected(new Set())
            }}
          >
            Clear
          </Button>
        </div>
      )}
      {items.isPending ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : list.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {trashed ? 'The trash is empty.' : 'No files here yet.'}
        </p>
      ) : (
        <ul aria-label="Files" className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
          {list.map((item) => (
            <li
              key={item.id}
              className="relative flex flex-col gap-1 rounded-md border p-1 text-xs"
            >
              {editable && (
                <input
                  type="checkbox"
                  aria-label={`Select ${item.filename}`}
                  className="absolute top-2 left-2 z-10"
                  checked={selected.has(item.id)}
                  onChange={(event) => {
                    toggle(item.id, event.target.checked)
                  }}
                />
              )}
              <button
                type="button"
                aria-label={`Open ${item.filename}`}
                className="flex aspect-square items-center justify-center overflow-hidden rounded-sm bg-muted"
                onClick={() => {
                  setOpen(item.id)
                }}
              >
                <MediaImage
                  vault={vault}
                  item={item}
                  size="160"
                  sizes="10rem"
                  className="max-h-full object-contain"
                  inert
                />
              </button>
              <span className="truncate font-medium">{item.filename}</span>
              <span className="text-muted-foreground">
                {formatBytes(item.size)} ·{' '}
                {(item.refs ?? []).length === 0
                  ? 'unused'
                  : `used ${String((item.refs ?? []).length)}×`}
              </span>
            </li>
          ))}
        </ul>
      )}
      {items.data?.next_cursor != null && limit < 500 && (
        <Button
          variant="outline"
          className="self-center"
          onClick={() => {
            setLimit(Math.min(limit + PAGE, 500))
          }}
        >
          Show more
        </Button>
      )}
      {open !== null && (
        <ItemSheet
          vault={vault}
          mediaId={open}
          editable={editable}
          onClose={() => {
            setOpen(null)
          }}
        />
      )}
    </div>
  )
}

/** "Used by": an entity picked with the quick switcher, shown as a removable chip. */
function EntityFilter({
  vault,
  entity,
  onChange,
}: {
  vault: string
  entity: { id: string; name: string } | null
  onChange: (entity: { id: string; name: string } | null) => void
}) {
  const [text, setText] = useState('')
  const found = useQuickSearch(vault, { q: text })
  if (entity !== null) {
    return (
      <span className="flex items-center gap-1 rounded-full border px-2 py-0.5">
        Used by {entity.name}
        <button
          type="button"
          aria-label="Any entity"
          onClick={() => {
            onChange(null)
          }}
        >
          <XIcon aria-hidden className="size-3" />
        </button>
      </span>
    )
  }
  return (
    <div className="relative">
      <Input
        type="search"
        aria-label="Used by"
        placeholder="Used by…"
        className="w-48"
        value={text}
        onChange={(event) => {
          setText(event.target.value)
        }}
      />
      {text.trim() !== '' && (found.data?.items.length ?? 0) > 0 && (
        <ul
          aria-label="Entities"
          className="absolute z-20 mt-1 w-64 rounded-md border bg-popover p-1 shadow-md"
        >
          {(found.data?.items ?? []).map((hit) => (
            <li key={hit.doc_id}>
              <button
                type="button"
                className="w-full rounded-sm px-2 py-1 text-left hover:bg-accent"
                onClick={() => {
                  onChange({ id: hit.entity_id, name: hit.name })
                  setText('')
                }}
              >
                {hit.name}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function EntityName({ vault, id }: { vault: string; id: string }) {
  const entity = useEntity(vault, id)
  return <>{entity.data?.name ?? '…'}</>
}

/** One file: preview, details, where it is used; authors edit, replace and trash it. */
function ItemSheet({
  vault,
  mediaId,
  editable,
  onClose,
}: {
  vault: string
  mediaId: string
  editable: boolean
  onClose: () => void
}) {
  const item = useMediaItem(vault, mediaId)
  return (
    <Sheet
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <SheetContent className="overflow-y-auto sm:max-w-md">
        {item.data === undefined ? (
          <SheetHeader>
            <SheetTitle>Loading…</SheetTitle>
          </SheetHeader>
        ) : (
          <ItemDetails vault={vault} item={item.data} editable={editable} />
        )}
      </SheetContent>
    </Sheet>
  )
}

function ItemDetails({
  vault,
  item,
  editable,
}: {
  vault: string
  item: MediaItem
  editable: boolean
}) {
  const update = useUpdateMedia(vault)
  const trash = useTrashMedia(vault)
  const restore = useRestoreMedia(vault)
  const replace = useReplaceMediaFile(vault)
  const [alt, setAlt] = useState(item.alt)
  const [caption, setCaption] = useState(item.caption)
  const [progress, setProgress] = useState<number | null>(null)
  const input = useRef<HTMLInputElement>(null)
  const refs = item.refs ?? []
  const dirty = alt !== item.alt || caption !== item.caption
  return (
    <div className="flex flex-col gap-4 px-4 pb-4">
      <SheetHeader className="px-0">
        <SheetTitle>{item.filename}</SheetTitle>
        <SheetDescription>
          {item.mime} · {formatBytes(item.size)}
          {item.width !== null && item.height !== null
            ? ` · ${String(item.width)} × ${String(item.height)}`
            : ''}
          {item.deleted_at !== null ? ' · in the trash' : ''}
        </SheetDescription>
      </SheetHeader>
      <MediaImage vault={vault} item={item} size="1280" sizes="28rem" className="rounded-md" />
      <form
        className="flex flex-col gap-2 text-sm"
        onSubmit={(event) => {
          event.preventDefault()
          update.mutate(
            { media: item.id, body: { revision: item.revision, alt, caption } },
            {
              onError: (error) => {
                toast.error(`Not saved: ${error.message}`)
              },
            },
          )
        }}
      >
        <label htmlFor={`${item.id}-alt`}>Alt text</label>
        <Input
          id={`${item.id}-alt`}
          value={alt}
          readOnly={!editable}
          onChange={(event) => {
            setAlt(event.target.value)
          }}
        />
        <label htmlFor={`${item.id}-caption`}>Caption</label>
        <Textarea
          id={`${item.id}-caption`}
          value={caption}
          readOnly={!editable}
          onChange={(event) => {
            setCaption(event.target.value)
          }}
        />
        {editable && (
          <Button
            type="submit"
            size="sm"
            disabled={!dirty || update.isPending}
            className="self-start"
          >
            Save
          </Button>
        )}
      </form>
      <section aria-label="Used by" className="flex flex-col gap-1 text-sm">
        <h3 className="font-medium">Used by</h3>
        {refs.length === 0 ? (
          <p className="text-muted-foreground">
            Nothing uses it (unused files go to the trash after a while).
          </p>
        ) : (
          <ul className="flex flex-col gap-1">
            {refs.map((ref) => (
              <li key={`${ref.entity_id}:${ref.context}`}>
                <Link
                  to="/v/$vault/e/$entity"
                  params={{ vault, entity: ref.entity_id }}
                  className="underline-offset-2 hover:underline"
                >
                  <EntityName vault={vault} id={ref.entity_id} />
                </Link>{' '}
                <span className="text-muted-foreground">({contextLabel(ref.context)})</span>
              </li>
            ))}
          </ul>
        )}
      </section>
      <div className="flex flex-wrap gap-2">
        <Button asChild size="sm" variant="outline">
          <a href={mediaFileUrl(vault, item.id, 'original', item.sha256)} download={item.filename}>
            <DownloadIcon aria-hidden />
            Download
          </a>
        </Button>
        {editable && item.deleted_at === null && (
          <>
            <input
              ref={input}
              type="file"
              className="hidden"
              aria-label="Replacement file"
              accept={item.mime.startsWith('image/') ? IMAGE_ACCEPT : ANY_ACCEPT}
              onChange={(event) => {
                const file = event.target.files?.[0]
                event.target.value = ''
                if (file === undefined) return
                setProgress(0)
                replace.mutate(
                  { media: item.id, file, revision: item.revision, onProgress: setProgress },
                  {
                    onSettled: () => {
                      setProgress(null)
                    },
                    onSuccess: () => {
                      toast.success('Replaced: everything that uses it shows the new file.')
                    },
                    onError: (error) => {
                      toast.error(`Not replaced: ${uploadProblem(error)}`)
                    },
                  },
                )
              }}
            />
            <Button
              size="sm"
              variant="outline"
              disabled={progress !== null}
              onClick={() => input.current?.click()}
            >
              <UploadIcon aria-hidden />
              {progress === null
                ? 'Replace file'
                : `Replacing… ${String(Math.round(progress * 100))}%`}
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                trash.mutate(item.id)
              }}
            >
              <TrashIcon aria-hidden />
              Move to the trash
            </Button>
          </>
        )}
        {editable && item.deleted_at !== null && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              restore.mutate(item.id)
            }}
          >
            <RotateCcwIcon aria-hidden />
            Restore
          </Button>
        )}
      </div>
    </div>
  )
}
