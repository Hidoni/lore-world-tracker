import { Extension } from '@tiptap/core'

import type { EditorContext } from './context'

/** Carries the `EditorContext` in the editor's storage (set by `RichTextEditor`). */
export const EditorContextExtension = Extension.create<object, EditorContext>({
  name: 'loreContext',
  addStorage: () => ({ vault: '', mutations: null }),
})
