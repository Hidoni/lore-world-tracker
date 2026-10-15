import { Extension, type Editor } from '@tiptap/core'

import type { Mutations } from '@/data'

/** What module extensions may need from the editor's page: the vault and the writes. */
export interface EditorContext {
  vault: string
  /** `null` in reader contexts. */
  mutations: Mutations | null
}

/** Carries the `EditorContext` in the editor's storage (set by `RichTextEditor`). */
export const EditorContextExtension = Extension.create<object, EditorContext>({
  name: 'loreContext',
  addStorage: () => ({ vault: '', mutations: null }),
})

/** The editor's context (module extensions call this from their plugins and commands). */
export function editorContextOf(editor: Editor): EditorContext {
  const storage = editor.storage as unknown as { loreContext?: EditorContext }
  return storage.loreContext ?? { vault: '', mutations: null }
}
