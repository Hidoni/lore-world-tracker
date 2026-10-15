import { Node, type Editor } from '@tiptap/core'
import { Plugin, PluginKey, type EditorState } from '@tiptap/pm/state'
import { Decoration, DecorationSet, type EditorView } from '@tiptap/pm/view'
import {
  NodeViewWrapper,
  ReactNodeViewRenderer,
  ReactRenderer,
  type ReactNodeViewProps,
} from '@tiptap/react'
import { toast } from 'sonner'

import { Input } from '@/components/ui/input'
import { IMAGE_TYPES, type MediaItem } from '@/data'
import { editorContextOf } from '@/editor'
import { cn } from '@/lib/utils'

import { MediaById } from '../components/media-image'
import { ImagePickerDialog } from '../components/image-picker'
import { uploadProblem } from '../components/upload-button'
import { imageAttrs } from './image-figure'

/** The width presets (pixels; `null`: full width). */
export const WIDTHS: readonly { label: string; width: number | null }[] = [
  { label: 'Small', width: 240 },
  { label: 'Medium', width: 480 },
  { label: 'Large', width: 960 },
  { label: 'Full', width: null },
]

function ImageNodeView({ node, editor, updateAttributes, selected }: ReactNodeViewProps) {
  const { vault } = editorContextOf(editor)
  const { mediaId, alt, caption, width } = imageAttrs(node.attrs)
  const editable = editor.isEditable
  return (
    <NodeViewWrapper
      as="figure"
      className={cn('my-3 flex flex-col gap-1 rounded-md', selected && 'ring-2 ring-ring')}
      style={width === null ? undefined : { maxWidth: width }}
      data-drag-handle
    >
      {mediaId !== null && vault !== '' && (
        <MediaById vault={vault} mediaId={mediaId} alt={alt} size="1280" className="rounded-md" />
      )}
      {editable ? (
        <div className="flex flex-col gap-1" contentEditable={false}>
          <Input
            aria-label="Caption"
            placeholder="Caption"
            value={caption}
            onChange={(event) => {
              updateAttributes({ caption: event.target.value })
            }}
          />
          <div className="flex flex-wrap items-center gap-2">
            <Input
              aria-label="Alt text"
              placeholder="Alt text (what the image shows)"
              className="h-8 flex-1 text-xs"
              value={alt}
              onChange={(event) => {
                updateAttributes({ alt: event.target.value })
              }}
            />
            <div role="group" aria-label="Width" className="flex gap-1">
              {WIDTHS.map((preset) => (
                <button
                  key={preset.label}
                  type="button"
                  aria-pressed={preset.width === width}
                  className="rounded-md border px-2 py-1 text-xs aria-pressed:bg-accent"
                  onClick={() => {
                    updateAttributes({ width: preset.width })
                  }}
                >
                  {preset.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      ) : (
        caption !== '' && (
          <figcaption className="text-sm text-muted-foreground">{caption}</figcaption>
        )
      )}
    </NodeViewWrapper>
  )
}

/** The node for a stored item (alt text from the library, no caption, full width). */
export function imageContent(item: MediaItem) {
  return { type: 'image', attrs: { mediaId: item.id, alt: item.alt, caption: '', width: null } }
}

/** Opens the image picker; the picked (or uploaded) image goes where the cursor was. */
export function pickImage(editor: Editor): void {
  const { vault } = editorContextOf(editor)
  const at = editor.state.selection.from
  const picker = new ReactRenderer(ImagePickerDialog, {
    editor,
    props: {
      vault,
      onPick: (item: MediaItem) => {
        picker.destroy()
        editor.chain().focus().insertContentAt(at, imageContent(item)).run()
      },
      onClose: () => {
        picker.destroy()
        editor.commands.focus()
      },
    },
  })
}

// --- uploads by paste and drop -------------------------------------------------------------------

const uploads = new PluginKey<DecorationSet>('imageUploads')

type UploadMeta = { add: { id: string; pos: number; element: HTMLElement } } | { remove: string }

function placeholderAt(state: EditorState, id: string): number | null {
  const found = uploads
    .getState(state)
    ?.find(undefined, undefined, (spec: { id?: string }) => spec.id === id)
  return found?.[0]?.from ?? null
}

/** The image files of a paste or drop. */
export function imageFiles(files: FileList | null | undefined): File[] {
  return [...(files ?? [])].filter((file) => IMAGE_TYPES.has(file.type))
}

/**
 * Uploads `files`, each shown at `pos` as "Uploading…" with its progress (a decoration: the
 * document only ever holds stored images), then puts its image there.
 */
export function uploadImages(editor: Editor, files: readonly File[], pos: number): void {
  const { vault, mutations } = editorContextOf(editor)
  if (mutations === null) {
    toast.error('Images can only be added while editing.')
    return
  }
  for (const file of files) {
    const id = `upload-${String(Date.now())}-${Math.random().toString(36).slice(2)}`
    const element = document.createElement('span')
    element.className = 'block rounded-md border border-dashed p-2 text-sm text-muted-foreground'
    element.setAttribute('role', 'status')
    element.textContent = `Uploading ${file.name}…`
    editor.view.dispatch(
      editor.state.tr.setMeta(uploads, { add: { id, pos, element } } satisfies UploadMeta),
    )
    const done = () => {
      const at = placeholderAt(editor.state, id)
      editor.view.dispatch(editor.state.tr.setMeta(uploads, { remove: id } satisfies UploadMeta))
      return at
    }
    mutations
      .uploadMedia(vault, file, { filename: file.name }, (fraction) => {
        element.textContent = `Uploading ${file.name}… ${String(Math.round(fraction * 100))}%`
      })
      .then(
        (result) => {
          if (editor.isDestroyed) return
          const at = done()
          if (at !== null) editor.chain().insertContentAt(at, imageContent(result.item)).run()
        },
        (error: unknown) => {
          if (!editor.isDestroyed) done()
          toast.error(`${file.name}: ${uploadProblem(error)}`)
        },
      )
  }
}

function uploadPlugin(editor: Editor): Plugin<DecorationSet> {
  return new Plugin<DecorationSet>({
    key: uploads,
    state: {
      init: () => DecorationSet.empty,
      apply(tr, set) {
        let next = set.map(tr.mapping, tr.doc)
        const meta = tr.getMeta(uploads) as UploadMeta | undefined
        if (meta !== undefined && 'add' in meta) {
          const { id, pos, element } = meta.add
          next = next.add(tr.doc, [Decoration.widget(pos, element, { id })])
        } else if (meta !== undefined) {
          next = next.remove(
            next.find(undefined, undefined, (spec: { id?: string }) => spec.id === meta.remove),
          )
        }
        return next
      },
    },
    props: {
      decorations(state) {
        return uploads.getState(state)
      },
      handlePaste(view: EditorView, event: ClipboardEvent) {
        const files = imageFiles(event.clipboardData?.files)
        if (files.length === 0 || !editor.isEditable) return false
        uploadImages(editor, files, view.state.selection.from)
        return true
      },
      handleDrop(view: EditorView, event: DragEvent, _slice, moved: boolean) {
        const files = imageFiles(event.dataTransfer?.files)
        if (moved || files.length === 0 || !editor.isEditable) return false
        const at = view.posAtCoords({ left: event.clientX, top: event.clientY })?.pos
        uploadImages(editor, files, at ?? view.state.selection.from)
        event.preventDefault()
        return true
      },
    },
  })
}

/**
 * `image` (docs/modules/media.md): a block image of a media item, `{mediaId, alt, caption,
 * width}`. Pasting or dropping image files uploads them (with progress) and puts them there; the
 * slash menu's "Image" picks one from the library or uploads one. The node view edits the caption,
 * the alt text and the width (presets).
 */
export const ImageNode = Node.create({
  name: 'image',
  group: 'block',
  atom: true,
  draggable: true,
  selectable: true,
  addOptions: () => ({
    slashItems: [
      {
        id: 'image',
        title: 'Image',
        description: 'Upload an image, or pick one from the library',
        keywords: ['picture', 'photo', 'media', 'upload', 'img'],
        run: (editor: Editor) => {
          pickImage(editor)
        },
      },
    ],
  }),
  addAttributes: () => ({
    mediaId: {
      default: null,
      parseHTML: (element) => element.getAttribute('data-media-id'),
      renderHTML: (attributes: { mediaId?: string | null }) =>
        attributes.mediaId ? { 'data-media-id': attributes.mediaId } : {},
    },
    alt: {
      default: '',
      parseHTML: (element) => element.getAttribute('data-alt') ?? '',
      renderHTML: () => ({}),
    },
    caption: { default: '', parseHTML: () => '', renderHTML: () => ({}) },
    width: { default: null, parseHTML: () => null, renderHTML: () => ({}) },
  }),
  parseHTML: () => [{ tag: 'figure[data-media-id]' }],
  renderHTML: ({ HTMLAttributes, node }) => [
    'figure',
    { ...HTMLAttributes, 'data-alt': imageAttrs(node.attrs).alt },
    imageAttrs(node.attrs).alt || 'image',
  ],
  renderText: ({ node }) => imageAttrs(node.attrs).alt,
  addNodeView: () => ReactNodeViewRenderer(ImageNodeView),
  addProseMirrorPlugins() {
    return [uploadPlugin(this.editor)]
  },
})
