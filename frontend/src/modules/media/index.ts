import { createRoute, lazyRouteComponent } from '@tanstack/react-router'
import { createElement, lazy, Suspense, type ComponentType } from 'react'

import { defineModule, type EntityViewProps } from '@/core/modules'

import { ImageFigure } from './editor/image-figure'
import { MediaFieldEditor, MediaFieldValue } from './panels/media-field'
import { useGalleryShown } from './panels/gallery-panel'

/** A panel loaded with the first page that shows it. */
function lazyPanel(
  load: () => Promise<ComponentType<EntityViewProps>>,
): ComponentType<EntityViewProps> {
  const Lazy = lazy(async () => ({ default: await load() }))
  return function Panel(props: EntityViewProps) {
    return createElement(Suspense, { fallback: null }, createElement(Lazy, props))
  }
}

const GalleryPanel = lazyPanel(async () => (await import('./panels/gallery-panel')).GalleryPanel)
const CoverImage = lazyPanel(async () => (await import('./panels/cover')).CoverImage)

/**
 * The media module (docs/modules/media.md): images in pages (the `image` node: paste, drop or
 * pick), cover images in entity headers, galleries, the media library and the `media` field type.
 */
export default defineModule({
  id: 'media',
  routes: (parent) => [
    createRoute({
      getParentRoute: () => parent,
      path: 'library',
      component: lazyRouteComponent(() => import('./views/library-page')),
    }),
  ],
  entityHeaderMedia: { '*': CoverImage },
  entityPanels: [
    {
      id: 'media.gallery',
      kinds: '*',
      title: 'Gallery',
      component: GalleryPanel,
      placement: 'main',
      order: 50,
      useShown: useGalleryShown,
    },
  ],
  editorExtensions: [() => import('./editor/image-node').then((loaded) => loaded.ImageNode)],
  richTextNodeRenderers: { image: ImageFigure },
  fieldTypeRenderers: { media: MediaFieldValue },
  fieldTypeEditors: { media: MediaFieldEditor },
  commands: [
    {
      id: 'media.library',
      title: 'Open the media library',
      keywords: ['images', 'files', 'uploads', 'pictures'],
      run: ({ vault, navigate }) => {
        if (vault !== undefined) navigate(`/v/${vault}/m/media/library`)
      },
    },
  ],
})
