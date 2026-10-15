import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'

import type { components } from '@/api'

import { useDataSource, useRequiredMutations } from './context'
import type { Domain } from './domain'
import { keys } from './keys'
import type { Query } from './source'

type Schemas = components['schemas']

export type MediaItem = Domain<Schemas['MediaItemOut']>
export type GalleryItem = Domain<Schemas['GalleryItemOut']>
export type MediaQuery = Omit<Query<'media_list'>, 'as_reader'>
export type MediaSize = '160' | '480' | '1280' | 'original'

/** Raster images (thumbnails exist for these only); other items are files to download. */
export const IMAGE_TYPES = new Set([
  'image/png',
  'image/jpeg',
  'image/webp',
  'image/gif',
  'image/avif',
])

export function isImage(item: Pick<MediaItem, 'mime'>): boolean {
  return IMAGE_TYPES.has(item.mime)
}

/**
 * Where a media item's file downloads from (same origin; what the request may see). Files are
 * cached for good: pass the item's `sha256` (`version`) so a replaced file gets a new URL.
 */
export function mediaFileUrl(
  vault: string,
  media: string,
  size: MediaSize = 'original',
  version?: string,
): string {
  const v = version === undefined ? '' : `&v=${encodeURIComponent(version.slice(0, 16))}`
  return `/api/v1/vaults/${encodeURIComponent(vault)}/m/media/items/${encodeURIComponent(media)}/file?size=${size}${v}`
}

/** The library (one page: `limit` items, newest first). */
export function useMediaItems(
  vault: string,
  query: MediaQuery = {},
  options: { enabled?: boolean } = {},
) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.mediaItems(vault, query),
    queryFn: () => source.mediaItems(vault, query),
    enabled: options.enabled ?? true,
  })
}

export function useMediaItem(vault: string, media: string | null) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.mediaItem(vault, media ?? ''),
    queryFn: () => source.mediaItem(vault, media ?? ''),
    enabled: media !== null && media !== '',
    retry: false,
  })
}

export function useGallery(vault: string, entity: string) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.gallery(vault, entity),
    queryFn: () => source.gallery(vault, entity),
  })
}

/** Media writes return no `affected`: the media reads refresh, and the change feed. */
function refresh(client: QueryClient, vault: string) {
  return Promise.all([
    client.invalidateQueries({ queryKey: keys.media(vault) }),
    client.invalidateQueries({ queryKey: [vault, 'changes'] }),
  ])
}

export interface UploadInput {
  file: File
  alt?: string
  caption?: string
  onProgress?: (fraction: number) => void
}

/** Uploads a file (the same bytes are the same item: `created: false`). */
export function useUploadMedia(vault: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ file, alt, caption, onProgress }: UploadInput) =>
      mutations.uploadMedia(
        vault,
        file,
        { filename: file.name, ...(alt ? { alt } : {}), ...(caption ? { caption } : {}) },
        onProgress,
      ),
    onSuccess: () => refresh(client, vault),
  })
}

export function useUpdateMedia(vault: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ media, body }: { media: string; body: Schemas['MediaItemUpdate'] }) =>
      mutations.updateMedia(vault, media, body),
    onSuccess: () => refresh(client, vault),
  })
}

export function useTrashMedia(vault: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (media: string) => mutations.trashMedia(vault, media),
    onSuccess: () => refresh(client, vault),
  })
}

export function useRestoreMedia(vault: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (media: string) => mutations.restoreMedia(vault, media),
    onSuccess: () => refresh(client, vault),
  })
}

export function useReplaceMediaFile(vault: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({
      media,
      file,
      revision,
      onProgress,
    }: {
      media: string
      file: File
      revision: number
      onProgress?: (fraction: number) => void
    }) => mutations.replaceMediaFile(vault, media, file, revision, onProgress),
    // Pages, galleries and maps show the new file under the same id: refresh everything.
    onSuccess: () => client.invalidateQueries({ queryKey: [vault] }),
  })
}

export function useAddToGallery(vault: string, entity: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['GalleryItemCreate']) => mutations.addToGallery(vault, entity, body),
    onSuccess: () => refresh(client, vault),
  })
}

export function useUpdateGalleryItem(vault: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ item, body }: { item: string; body: Schemas['GalleryItemUpdate'] }) =>
      mutations.updateGalleryItem(vault, item, body),
    onSuccess: () => refresh(client, vault),
  })
}

export function useRemoveFromGallery(vault: string) {
  const mutations = useRequiredMutations()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (item: string) => mutations.removeFromGallery(vault, item),
    onSuccess: () => refresh(client, vault),
  })
}
