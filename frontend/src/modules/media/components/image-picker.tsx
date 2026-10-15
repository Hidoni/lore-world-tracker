import { useState } from 'react'

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { useMediaItems, type MediaItem } from '@/data'

import { MediaImage } from './media-image'
import { ANY_ACCEPT, IMAGE_ACCEPT, UploadButton } from './upload-button'

/**
 * The image picker (docs/modules/media.md, UI): the library's images (search by name, alt or
 * caption) and an upload; picking one, or uploading, closes it. Shared by the editor, covers,
 * galleries and `media` fields.
 */
export function ImagePickerDialog({
  vault,
  title = 'Choose an image',
  imagesOnly = true,
  onPick,
  onClose,
}: {
  vault: string
  title?: string
  /** Other files too (documents) when false. */
  imagesOnly?: boolean
  onPick: (item: MediaItem) => void
  onClose: () => void
}) {
  const [q, setQ] = useState('')
  const items = useMediaItems(vault, {
    ...(imagesOnly ? { mime: 'image/' } : {}),
    ...(q.trim() === '' ? {} : { q: q.trim() }),
    limit: 60,
  })
  const shown = (items.data?.items ?? []).filter(
    (item) => !imagesOnly || item.mime !== 'image/svg+xml',
  )
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>Pick one from the library, or upload a new one.</DialogDescription>
        </DialogHeader>
        <div className="flex items-center gap-2">
          <Input
            type="search"
            aria-label="Search the library"
            placeholder="Search by name, alt text or caption"
            value={q}
            onChange={(event) => {
              setQ(event.target.value)
            }}
          />
          <UploadButton
            vault={vault}
            accept={imagesOnly ? IMAGE_ACCEPT : ANY_ACCEPT}
            onUploaded={onPick}
          />
        </div>
        {items.isPending ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : shown.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {q.trim() === '' ? 'The library is empty: upload one.' : 'Nothing matches.'}
          </p>
        ) : (
          <ul
            aria-label="Library"
            className="grid max-h-[60vh] grid-cols-3 gap-2 overflow-y-auto sm:grid-cols-4"
          >
            {shown.map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  aria-label={`Pick ${item.filename}`}
                  className="flex w-full flex-col gap-1 rounded-md border p-1 text-left text-xs hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                  onClick={() => {
                    onPick(item)
                  }}
                >
                  <span className="flex aspect-square items-center justify-center overflow-hidden rounded-sm bg-muted">
                    <MediaImage
                      vault={vault}
                      item={item}
                      size="160"
                      className="max-h-full object-contain"
                      sizes="160px"
                    />
                  </span>
                  <span className="truncate">{item.filename}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </DialogContent>
    </Dialog>
  )
}
