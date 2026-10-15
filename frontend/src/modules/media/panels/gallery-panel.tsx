import { ArrowLeftIcon, ArrowRightIcon, PlusIcon, TrashIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import type { EntityViewProps } from '@/core/modules'
import {
  useAddToGallery,
  useGallery,
  useMutations,
  useRemoveFromGallery,
  useUpdateGalleryItem,
  type components,
  type GalleryItem,
} from '@/data'

type Visibility = components['schemas']['Visibility']

import { ImagePickerDialog } from '../components/image-picker'
import { MediaImage } from '../components/media-image'
import { keyForMove } from '../sort-keys'

/** Shown to authors (to add the first image), and to readers when there are images. */
export function useGalleryShown({ vault, entityId }: EntityViewProps): boolean {
  const editable = useMutations() !== null
  const gallery = useGallery(vault, entityId)
  return editable || (gallery.data?.items.length ?? 0) > 0
}

const failed = (error: Error) => {
  toast.error(`The gallery wasn't saved: ${error.message}`)
}

/**
 * The gallery (docs/modules/media.md, UI): the entity's images in order, with captions and a
 * visibility each. Authors add images (library or upload), drag them (or use the arrows) to
 * reorder, edit captions and remove them.
 */
export function GalleryPanel({ vault, entityId }: EntityViewProps) {
  const gallery = useGallery(vault, entityId)
  const editable = useMutations() !== null
  const add = useAddToGallery(vault, entityId)
  const update = useUpdateGalleryItem(vault)
  const remove = useRemoveFromGallery(vault)
  const [picking, setPicking] = useState(false)
  const [dragged, setDragged] = useState<number | null>(null)
  if (gallery.isPending) return <p className="text-sm text-muted-foreground">Loading…</p>
  const items = gallery.data?.items ?? []
  const move = (from: number, to: number) => {
    const item = items[from]
    if (item === undefined || from === to || to < 0 || to >= items.length) return
    const sortKey = keyForMove(
      items.map((entry) => entry.sort_key),
      from,
      to,
    )
    update.mutate(
      { item: item.id, body: { revision: item.revision, sort_key: sortKey } },
      { onError: failed },
    )
  }
  return (
    <div className="flex flex-col gap-2">
      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground">No images yet.</p>
      ) : (
        <ul aria-label="Gallery" className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {items.map((item, index) => (
            <li
              key={item.id}
              className="flex flex-col gap-1"
              draggable={editable}
              onDragStart={(event) => {
                setDragged(index)
                event.dataTransfer.effectAllowed = 'move'
              }}
              onDragOver={(event) => {
                if (dragged !== null) event.preventDefault()
              }}
              onDrop={(event) => {
                event.preventDefault()
                if (dragged !== null) move(dragged, index)
                setDragged(null)
              }}
              onDragEnd={() => {
                setDragged(null)
              }}
            >
              <figure className="flex flex-col gap-1">
                <span className="flex aspect-square items-center justify-center overflow-hidden rounded-md bg-muted">
                  <MediaImage
                    vault={vault}
                    item={item.media}
                    alt={item.caption || item.media.alt}
                    className="max-h-full object-contain"
                    sizes="16rem"
                  />
                </span>
                {editable ? (
                  <GalleryItemEditor
                    item={item}
                    index={index}
                    count={items.length}
                    onCaption={(caption) => {
                      update.mutate(
                        { item: item.id, body: { revision: item.revision, caption } },
                        { onError: failed },
                      )
                    }}
                    onVisibility={(visibility) => {
                      update.mutate(
                        { item: item.id, body: { revision: item.revision, visibility } },
                        { onError: failed },
                      )
                    }}
                    onMove={(to) => {
                      move(index, to)
                    }}
                    onRemove={() => {
                      remove.mutate(item.id, { onError: failed })
                    }}
                  />
                ) : (
                  item.caption !== '' && (
                    <figcaption className="text-sm text-muted-foreground">
                      {item.caption}
                    </figcaption>
                  )
                )}
              </figure>
            </li>
          ))}
        </ul>
      )}
      {editable && (
        <div>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              setPicking(true)
            }}
          >
            <PlusIcon aria-hidden />
            Add an image
          </Button>
        </div>
      )}
      {picking && (
        <ImagePickerDialog
          vault={vault}
          title="Add to the gallery"
          onPick={(media) => {
            setPicking(false)
            add.mutate({ media_id: media.id }, { onError: failed })
          }}
          onClose={() => {
            setPicking(false)
          }}
        />
      )}
    </div>
  )
}

function GalleryItemEditor({
  item,
  index,
  count,
  onCaption,
  onVisibility,
  onMove,
  onRemove,
}: {
  item: GalleryItem
  index: number
  count: number
  onCaption: (caption: string) => void
  onVisibility: (visibility: Visibility) => void
  onMove: (to: number) => void
  onRemove: () => void
}) {
  const [caption, setCaption] = useState(item.caption)
  const name = item.media.filename
  return (
    <div className="flex flex-col gap-1">
      <Input
        aria-label={`Caption of ${name}`}
        placeholder="Caption"
        className="h-8 text-xs"
        value={caption}
        onChange={(event) => {
          setCaption(event.target.value)
        }}
        onBlur={() => {
          if (caption !== item.caption) onCaption(caption)
        }}
        onKeyDown={(event) => {
          if (event.key === 'Enter') event.currentTarget.blur()
        }}
      />
      <div className="flex items-center gap-1">
        <select
          aria-label={`Visibility of ${name}`}
          className="h-7 flex-1 rounded-md border bg-transparent px-1 text-xs"
          value={item.visibility}
          onChange={(event) => {
            onVisibility(event.target.value as Visibility)
          }}
        >
          <option value="public">Public</option>
          <option value="spoiler">Spoiler</option>
          <option value="private">Private</option>
        </select>
        <Button
          size="icon"
          variant="ghost"
          className="size-7"
          aria-label={`Move ${name} earlier`}
          disabled={index === 0}
          onClick={() => {
            onMove(index - 1)
          }}
        >
          <ArrowLeftIcon aria-hidden />
        </Button>
        <Button
          size="icon"
          variant="ghost"
          className="size-7"
          aria-label={`Move ${name} later`}
          disabled={index === count - 1}
          onClick={() => {
            onMove(index + 1)
          }}
        >
          <ArrowRightIcon aria-hidden />
        </Button>
        <Button
          size="icon"
          variant="ghost"
          className="size-7"
          aria-label={`Remove ${name} from the gallery`}
          onClick={onRemove}
        >
          <TrashIcon aria-hidden />
        </Button>
      </div>
    </div>
  )
}
