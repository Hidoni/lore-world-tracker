import type { RichTextNodeProps } from '@/core/modules'

import { MediaById } from '../components/media-image'

/** The `image` node's attributes (`{mediaId, alt, caption, width}`). */
export interface ImageAttrs {
  mediaId: string | null
  alt: string
  caption: string
  /** Pixels; `null`: as wide as the page allows. */
  width: number | null
}

export function imageAttrs(attrs: Readonly<Record<string, unknown>>): ImageAttrs {
  const text = (value: unknown) => (typeof value === 'string' ? value : '')
  return {
    mediaId: typeof attrs.mediaId === 'string' ? attrs.mediaId : null,
    alt: text(attrs.alt),
    caption: text(attrs.caption),
    width: typeof attrs.width === 'number' ? attrs.width : null,
  }
}

/** An `image` node read: the image (loaded lazily, at most `width` wide) and its caption. */
export function ImageFigure({ vault, attrs }: RichTextNodeProps) {
  const { mediaId, alt, caption, width } = imageAttrs(attrs)
  return (
    <figure
      className="my-3 flex flex-col gap-1"
      style={width === null ? undefined : { maxWidth: width }}
    >
      {mediaId === null ? (
        <span className="text-sm text-muted-foreground">{alt || 'Missing image'}</span>
      ) : (
        <MediaById
          vault={vault}
          mediaId={mediaId}
          alt={alt}
          size={width !== null && width <= 480 ? '480' : '1280'}
          className="rounded-md"
          sizes={width === null ? '(min-width: 64rem) 48rem, 100vw' : `${String(width)}px`}
        />
      )}
      {caption !== '' && (
        <figcaption className="text-sm text-muted-foreground">{caption}</figcaption>
      )}
    </figure>
  )
}
