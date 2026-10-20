import { TypeIcon, XIcon } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import type { FieldEditorExtensionProps, FieldRendererProps } from '@/core/modules'
import { useMediaItem } from '@/data'
import { ImagePickerDialog } from '@/modules/media/public'

import { fontStyle, useFontFamily } from './fonts'

/** What a font shows when it has no sample: Latin letters and digits. */
export const SPECIMEN = 'Aa Bb Cc 0123'

/** A font file: a specimen in it, and its file name (or why it can't be used). */
function FontFile({ vault, media }: { vault: string; media: string }) {
  const item = useMediaItem(vault, media)
  const family = useFontFamily(vault, media)
  if (item.isError) return <span className="text-destructive">The font file is missing.</span>
  const font = item.data?.mime.startsWith('font/') ?? true
  return (
    <span className="flex min-w-0 flex-wrap items-baseline gap-x-3">
      {font ? (
        <span className="text-lg" style={fontStyle({ family, scale: 100 })}>
          {SPECIMEN}
        </span>
      ) : (
        <span className="text-destructive">Not a font file.</span>
      )}
      <span className="truncate text-xs text-muted-foreground">{item.data?.filename ?? '…'}</span>
    </span>
  )
}

/** `scripts.font` read: a specimen in the font. */
export function FontFieldValue({ vault, value }: FieldRendererProps) {
  if (typeof value !== 'string' || value === '') {
    return <span className="text-muted-foreground">—</span>
  }
  return <FontFile vault={vault} media={value} />
}

/** `scripts.font` edited: the font, "Choose a font" (the library's fonts, or an upload), remove. */
export function FontFieldEditor({
  vault,
  field,
  id,
  value,
  onCommit,
  onCancel,
}: FieldEditorExtensionProps) {
  const [picking, setPicking] = useState(false)
  const media = typeof value === 'string' && value !== '' ? value : null
  return (
    <div id={id} className="flex flex-col gap-2">
      {media !== null && (
        <div className="flex items-center gap-2">
          <FontFile vault={vault} media={media} />
          <Button
            size="icon"
            variant="ghost"
            className="size-6"
            aria-label="Remove the font"
            onClick={() => {
              onCommit(null)
            }}
          >
            <XIcon aria-hidden />
          </Button>
        </div>
      )}
      <div className="flex gap-2">
        <Button
          size="sm"
          variant="outline"
          onClick={() => {
            setPicking(true)
          }}
        >
          <TypeIcon aria-hidden />
          {media === null ? 'Choose a font' : 'Replace the font'}
        </Button>
        <Button size="sm" variant="ghost" onClick={onCancel}>
          Done
        </Button>
      </div>
      {picking && (
        <ImagePickerDialog
          vault={vault}
          title={field.label}
          fontsOnly
          onPick={(item) => {
            setPicking(false)
            onCommit(item.id)
          }}
          onClose={() => {
            setPicking(false)
          }}
        />
      )}
    </div>
  )
}
