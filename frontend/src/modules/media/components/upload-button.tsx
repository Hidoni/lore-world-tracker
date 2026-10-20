import { UploadIcon } from 'lucide-react'
import { useRef, useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { useUploadMedia, type MediaItem } from '@/data'

/** What the file input offers (the server judges the bytes anyway). */
export const RASTER_ACCEPT = 'image/png,image/jpeg,image/webp,image/gif,image/avif'
export const IMAGE_ACCEPT = `${RASTER_ACCEPT},image/svg+xml,.svg`
export const FONT_ACCEPT = 'font/woff2,font/woff,font/ttf,font/otf,.woff2,.woff,.ttf,.otf'
export const ANY_ACCEPT = `${IMAGE_ACCEPT},application/pdf,text/plain,text/markdown,.md,${FONT_ACCEPT}`

/** An upload's message for the author. */
export function uploadProblem(error: unknown): string {
  return error instanceof Error ? error.message : 'The upload failed.'
}

/**
 * "Upload": picks files and uploads them one after the other, with progress; `onUploaded` gets
 * each stored item (the same bytes again are the item already there).
 */
export function UploadButton({
  vault,
  accept = IMAGE_ACCEPT,
  multiple = false,
  label = 'Upload',
  onUploaded,
  variant = 'outline',
}: {
  vault: string
  accept?: string
  multiple?: boolean
  label?: string
  onUploaded: (item: MediaItem) => void
  variant?: 'outline' | 'default' | 'ghost'
}) {
  const input = useRef<HTMLInputElement>(null)
  const upload = useUploadMedia(vault)
  const [progress, setProgress] = useState<number | null>(null)
  const send = async (files: readonly File[]) => {
    for (const file of files) {
      setProgress(0)
      try {
        const result = await upload.mutateAsync({ file, onProgress: setProgress })
        onUploaded(result.item)
      } catch (error) {
        toast.error(`${file.name}: ${uploadProblem(error)}`)
      }
    }
    setProgress(null)
  }
  return (
    <>
      <input
        ref={input}
        type="file"
        className="hidden"
        accept={accept}
        multiple={multiple}
        aria-label={label}
        data-testid="media-file-input"
        onChange={(event) => {
          const files = [...(event.target.files ?? [])]
          event.target.value = ''
          void send(files)
        }}
      />
      <Button
        type="button"
        size="sm"
        variant={variant}
        disabled={progress !== null}
        onClick={() => input.current?.click()}
      >
        <UploadIcon aria-hidden />
        {progress === null ? label : `Uploading… ${String(Math.round(progress * 100))}%`}
      </Button>
      {progress !== null && (
        <progress className="sr-only" aria-label="Upload progress" value={progress} max={1} />
      )}
    </>
  )
}
