import { Editor } from '@tiptap/core'
import { describe, expect, it, vi } from 'vitest'

import type { Mutations } from '@/data'
import { editorContextOf } from '@/editor'
import { editorExtensions } from '@/editor/extensions'

import { ImageNode, uploadImages } from './editor/image-node'
import { keyBetween, keyForMove } from './sort-keys'

describe('gallery sort keys', () => {
  it('finds keys between any two (and before or after all)', () => {
    const cases: [string | null, string | null][] = [
      [null, null],
      [null, 'a'],
      ['a', null],
      ['a', 'aV'],
      ['a', 'a0V'],
      ['aV', 'aW'],
      ['az', 'b'],
      ['0', '1'],
      [null, '01'],
      ['zz', null],
    ]
    for (const [before, after] of cases) {
      const key = keyBetween(before, after)
      expect(key).toMatch(/^[0-9A-Za-z]+$/)
      if (before !== null) expect(key > before).toBe(true)
      if (after !== null) expect(key < after).toBe(true)
    }
    expect(() => keyBetween('b', 'a')).toThrow()
  })

  it('keeps finding keys between neighbours', () => {
    let low = 'a'
    const high = 'aV'
    for (let step = 0; step < 50; step += 1) {
      const key = keyBetween(low, high)
      expect(key > low && key < high).toBe(true)
      low = key
    }
  })

  it('moves an item between its new neighbours', () => {
    const keys = ['a', 'aV', 'aVV']
    expect(keyForMove(keys, 0, 2) > 'aVV').toBe(true)
    const between = keyForMove(keys, 2, 1)
    expect(between > 'a' && between < 'aV').toBe(true)
    expect(keyForMove(keys, 1, 0) < 'a').toBe(true)
  })
})

const image = (attrs: Record<string, unknown>) => ({ type: 'image', attrs })

function makeEditor(mutations: Partial<Mutations> | null = null) {
  const editor = new Editor({
    extensions: editorExtensions({ extra: [ImageNode] }),
    content: {
      type: 'doc',
      content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Hi' }] }],
    },
  })
  const context = editorContextOf(editor)
  context.vault = 'v1'
  context.mutations = mutations as Mutations | null
  return editor
}

describe('the image node', () => {
  it('keeps exactly the attributes the server accepts', () => {
    const doc = {
      type: 'doc',
      content: [image({ mediaId: 'm1', alt: 'A map', caption: 'Varn', width: 480 })],
    }
    const editor = new Editor({
      extensions: editorExtensions({ extra: [ImageNode] }),
      content: doc,
    })
    expect(editor.getJSON()).toEqual(doc)
    editor.destroy()
  })

  it('uploads pasted images, shows their progress, then puts them in the page', async () => {
    let finish: (() => void) | null = null
    const progress: number[] = []
    const uploadMedia = vi.fn(
      (_vault: string, file: Blob, _form: unknown, onProgress?: (fraction: number) => void) =>
        new Promise((resolve) => {
          onProgress?.(0.5)
          progress.push(0.5)
          finish = () => {
            resolve({
              item: { id: 'm9', alt: (file as File).name, mime: 'image/png' },
              created: true,
            })
          }
        }),
    )
    const editor = makeEditor({ uploadMedia } as unknown as Partial<Mutations>)
    uploadImages(editor, [new File(['x'], 'dragon.png', { type: 'image/png' })], 3)
    expect(uploadMedia).toHaveBeenCalledWith(
      'v1',
      expect.any(File),
      { filename: 'dragon.png' },
      expect.any(Function),
    )
    // Uploading: a placeholder (not in the document) says how far it is.
    expect(editor.view.dom.textContent).toContain('Uploading dragon.png… 50%')
    expect(JSON.stringify(editor.getJSON())).not.toContain('image')
    ;(finish as unknown as () => void)()
    await vi.waitFor(() => {
      expect(editor.getJSON().content).toContainEqual(
        image({ mediaId: 'm9', alt: 'dragon.png', caption: '', width: null }),
      )
    })
    expect(editor.view.dom.textContent).not.toContain('Uploading')
    editor.destroy()
  })

  it('drops the placeholder when an upload fails', async () => {
    const uploadMedia = vi.fn(() => Promise.reject(new Error('This file type isn’t supported.')))
    const editor = makeEditor({ uploadMedia })
    uploadImages(editor, [new File(['x'], 'bad.png', { type: 'image/png' })], 1)
    await vi.waitFor(() => {
      expect(editor.view.dom.textContent).not.toContain('Uploading')
    })
    expect(JSON.stringify(editor.getJSON())).not.toContain('"image"')
    editor.destroy()
  })
})
