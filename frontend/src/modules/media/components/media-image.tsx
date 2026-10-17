import { FileIcon, ImageOffIcon } from 'lucide-react'

import {
  isImage,
  isRaster,
  mediaFileUrl,
  useMediaItem,
  type MediaItem,
  type MediaSize,
} from '@/data'
import { cn } from '@/lib/utils'

/** Thumbnail widths the server makes (`?size=`). */
const WIDTHS = [160, 480, 1280] as const

/**
 * A media item shown: an image (thumbnails by width, loaded lazily; an SVG as it is) or, for
 * other files, a download link with the file's name.
 */
export function MediaImage({
  vault,
  item,
  size = '480',
  alt,
  className,
  sizes,
  inert = false,
}: {
  vault: string
  item: MediaItem
  /** The default source (and the largest one used, `original` aside). */
  size?: MediaSize
  /** Instead of the item's alt text. */
  alt?: string
  className?: string
  /** The `sizes` attribute (how wide the image shows). */
  sizes?: string
  /** Inside another control (a tile's button): a file that isn't an image shows its name, not a
   * download link (no link inside a button). */
  inert?: boolean
}) {
  if (!isImage(item) && inert) {
    return (
      <span className={cn('flex items-center gap-2 text-sm', className)}>
        <FileIcon aria-hidden className="size-4 shrink-0" />
        {item.filename}
      </span>
    )
  }
  if (!isImage(item)) {
    return (
      <a
        href={mediaFileUrl(vault, item.id, 'original', item.sha256)}
        download={item.filename}
        className={cn(
          'flex items-center gap-2 text-sm underline-offset-2 hover:underline',
          className,
        )}
      >
        <FileIcon aria-hidden className="size-4 shrink-0" />
        {item.filename}
      </a>
    )
  }
  const url = (width: MediaSize) => mediaFileUrl(vault, item.id, width, item.sha256)
  if (!isRaster(item)) {
    // An SVG: one sanitized file that scales (no thumbnails, no dimensions).
    return (
      <img
        src={url('original')}
        alt={alt ?? item.alt}
        loading="lazy"
        decoding="async"
        className={cn('h-auto max-w-full', className)}
      />
    )
  }
  const widths = WIDTHS.filter((width) => item.width === null || width < item.width)
  const srcSet = [
    ...widths.map((width) => `${url(String(width) as MediaSize)} ${String(width)}w`),
    ...(item.width === null ? [] : [`${url('original')} ${String(item.width)}w`]),
  ].join(', ')
  return (
    <img
      src={url(size)}
      srcSet={srcSet}
      sizes={sizes}
      alt={alt ?? item.alt}
      loading="lazy"
      decoding="async"
      width={item.width ?? undefined}
      height={item.height ?? undefined}
      className={cn('h-auto max-w-full', className)}
    />
  )
}

/** A media item by id: loaded first (missing or hidden items show as their alt text). */
export function MediaById({
  vault,
  mediaId,
  alt,
  ...props
}: {
  vault: string
  mediaId: string
  alt?: string
  size?: MediaSize
  className?: string
  sizes?: string
}) {
  const item = useMediaItem(vault, mediaId)
  if (item.isPending) return <span className="block h-24 animate-pulse rounded-md bg-muted" />
  if (item.data?.deleted_at !== null) {
    return (
      <span className="flex items-center gap-2 rounded-md border border-dashed p-3 text-sm text-muted-foreground">
        <ImageOffIcon aria-hidden className="size-4" />
        {alt === undefined || alt === '' ? 'Missing image' : alt}
      </span>
    )
  }
  return <MediaImage vault={vault} item={item.data} {...(alt ? { alt } : {})} {...props} />
}
