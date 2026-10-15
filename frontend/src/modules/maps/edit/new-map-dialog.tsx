import { ImageIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { mediaFileUrl, useCreateMap, type MediaItem } from '@/data'
import { ImagePickerDialog } from '@/modules/media/public'

/** A new map of `location`: a name and its image (picked from the library or uploaded). */
export function NewMapDialog({
  vault,
  location,
  defaultName,
  onCreated,
  onClose,
}: {
  vault: string
  location: string
  defaultName: string
  onCreated: (map: string) => void
  onClose: () => void
}) {
  const create = useCreateMap(vault)
  const [name, setName] = useState(defaultName)
  const [image, setImage] = useState<MediaItem | null>(null)
  const [picking, setPicking] = useState(false)
  if (picking) {
    return (
      <ImagePickerDialog
        vault={vault}
        title="The map's image"
        onPick={(item) => {
          setImage(item)
          setPicking(false)
        }}
        onClose={() => {
          setPicking(false)
        }}
      />
    )
  }
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New map</DialogTitle>
          <DialogDescription>An image of this place to pin things on.</DialogDescription>
        </DialogHeader>
        <form
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault()
            if (image === null || name.trim() === '') return
            create.mutate(
              { location_id: location, media_id: image.id, name: name.trim() },
              {
                onSuccess: (result) => {
                  onCreated(result.map.id)
                },
                onError: (error) => {
                  toast.error(`The map wasn't created: ${error.message}`)
                },
              },
            )
          }}
        >
          <label htmlFor="new-map-name" className="text-sm">
            Name
          </label>
          <Input
            id="new-map-name"
            value={name}
            onChange={(event) => {
              setName(event.target.value)
            }}
          />
          <div className="flex items-center gap-3">
            {image !== null && (
              <img
                src={mediaFileUrl(vault, image.id, '160', image.sha256)}
                alt={image.alt || image.filename}
                className="h-16 w-auto rounded-sm"
              />
            )}
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                setPicking(true)
              }}
            >
              <ImageIcon aria-hidden />
              {image === null ? 'Choose the image' : 'Another image'}
            </Button>
          </div>
          <Button type="submit" disabled={image === null || name.trim() === '' || create.isPending}>
            Create the map
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  )
}
