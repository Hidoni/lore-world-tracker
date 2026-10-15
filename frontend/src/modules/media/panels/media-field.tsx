import { ImageIcon, XIcon } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import type { FieldEditorExtensionProps, FieldRendererProps } from '@/core/modules'

import { ImagePickerDialog } from '../components/image-picker'
import { MediaById } from '../components/media-image'

/** A `media` field's ids: one id, or a list (`multiple`). */
export function mediaIds(value: unknown): string[] {
  if (typeof value === 'string') return [value]
  if (Array.isArray(value)) return value.filter((id): id is string => typeof id === 'string')
  return []
}

/** A `media` field value read: its images as thumbnails (other files as download links). */
export function MediaFieldValue({ vault, value }: FieldRendererProps) {
  const ids = mediaIds(value)
  if (ids.length === 0) return <span className="text-muted-foreground">—</span>
  return (
    <ul className="flex flex-wrap gap-2">
      {ids.map((id) => (
        <li key={id}>
          <MediaById
            vault={vault}
            mediaId={id}
            size="160"
            sizes="5rem"
            className="h-20 w-auto rounded-sm"
          />
        </li>
      ))}
    </ul>
  )
}

/**
 * A `media` field edited: its images, each removable, and "Choose" (the image picker: library
 * or upload). Every change saves at once.
 */
export function MediaFieldEditor({
  vault,
  field,
  id,
  value,
  onCommit,
  onCancel,
}: FieldEditorExtensionProps) {
  const ids = mediaIds(value)
  const [picking, setPicking] = useState(false)
  const save = (next: string[]) => {
    onCommit(field.multiple ? next : (next[0] ?? null))
  }
  return (
    <div id={id} className="flex flex-col gap-2">
      {ids.length > 0 && (
        <ul className="flex flex-wrap gap-2" aria-label={field.label}>
          {ids.map((media) => (
            <li key={media} className="relative">
              <MediaById
                vault={vault}
                mediaId={media}
                size="160"
                sizes="5rem"
                className="h-20 w-auto rounded-sm"
              />
              <Button
                size="icon"
                variant="secondary"
                className="absolute top-1 right-1 size-6"
                aria-label="Remove the image"
                onClick={() => {
                  save(ids.filter((other) => other !== media))
                }}
              >
                <XIcon aria-hidden />
              </Button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex gap-2">
        <Button
          size="sm"
          variant="outline"
          onClick={() => {
            setPicking(true)
          }}
        >
          <ImageIcon aria-hidden />
          {field.multiple || ids.length === 0 ? 'Choose an image' : 'Replace the image'}
        </Button>
        <Button size="sm" variant="ghost" onClick={onCancel}>
          Done
        </Button>
      </div>
      {picking && (
        <ImagePickerDialog
          vault={vault}
          title={field.label}
          onPick={(item) => {
            setPicking(false)
            save(
              field.multiple ? [...ids.filter((other) => other !== item.id), item.id] : [item.id],
            )
          }}
          onClose={() => {
            setPicking(false)
          }}
        />
      )}
    </div>
  )
}
