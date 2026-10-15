import { ImageIcon, XIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import type { EntityViewProps } from '@/core/modules'
import { useEntity, useMutations, useUpdateEntity } from '@/data'

import { ImagePickerDialog } from '../components/image-picker'
import { MediaById } from '../components/media-image'

/**
 * The cover image in the entity header (docs/modules/media.md, UI): the entity's
 * `cover_media_id`, set by uploading or picking from the library, and removable.
 */
export function CoverImage({ vault, entityId }: EntityViewProps) {
  const entity = useEntity(vault, entityId)
  const editable = useMutations() !== null
  const update = useUpdateEntity(vault)
  const [picking, setPicking] = useState(false)
  const data = entity.data
  if (data === undefined) return null
  const cover = data.cover_media_id
  const canEdit = editable && data.deleted_at === null
  if (cover === null && !canEdit) return null
  const set = (media: string | null) => {
    update.mutate(
      { id: entityId, body: { revision: data.revision, cover_media_id: media } },
      {
        onError: (error) => {
          toast.error(`The cover wasn't saved: ${error.message}`)
        },
      },
    )
  }
  return (
    <div role="group" aria-label="Cover image" className="flex w-32 shrink-0 flex-col gap-1">
      {cover !== null && (
        <MediaById
          vault={vault}
          mediaId={cover}
          alt={`${data.name} (cover)`}
          size="480"
          sizes="8rem"
          className="aspect-square w-32 rounded-md object-cover"
        />
      )}
      {canEdit && (
        <div className="flex gap-1">
          <Button
            size="sm"
            variant="ghost"
            className="h-7 px-2 text-xs"
            onClick={() => {
              setPicking(true)
            }}
          >
            <ImageIcon aria-hidden />
            {cover === null ? 'Add cover' : 'Change'}
          </Button>
          {cover !== null && (
            <Button
              size="sm"
              variant="ghost"
              className="h-7 px-2 text-xs"
              aria-label="Remove the cover"
              onClick={() => {
                set(null)
              }}
            >
              <XIcon aria-hidden />
            </Button>
          )}
        </div>
      )}
      {picking && (
        <ImagePickerDialog
          vault={vault}
          title="Choose a cover image"
          onPick={(item) => {
            setPicking(false)
            set(item.id)
          }}
          onClose={() => {
            setPicking(false)
          }}
        />
      )}
    </div>
  )
}
