import { describe, expect, it } from 'vitest'

import { linkOccurrences } from './unlinked'

const link = { type: 'entityLink', attrs: { entityId: 'v' } }
const bold = { type: 'bold' }

describe('linkOccurrences', () => {
  it('splits text nodes and keeps the structure and other marks', () => {
    const doc = {
      type: 'doc',
      content: [
        { type: 'heading', attrs: { level: 2 }, content: [{ type: 'text', text: 'Varn' }] },
        {
          type: 'paragraph',
          content: [
            { type: 'text', text: 'From Varn to varn.', marks: [bold] },
            { type: 'text', text: ' End' },
          ],
        },
      ],
    }
    const result = linkOccurrences(
      doc,
      [
        { path: [1, 0], offset: 5, length: 4, text: 'Varn' },
        { path: [0, 0], offset: 0, length: 4, text: 'Varn' },
        { path: [1, 0], offset: 13, length: 4, text: 'varn' },
      ],
      'v',
    )
    expect(result).toMatchObject({ linked: 3, skipped: 0 })
    expect(result.doc).toEqual({
      type: 'doc',
      content: [
        {
          type: 'heading',
          attrs: { level: 2 },
          content: [{ type: 'text', text: 'Varn', marks: [link] }],
        },
        {
          type: 'paragraph',
          content: [
            { type: 'text', text: 'From ', marks: [bold] },
            { type: 'text', text: 'Varn', marks: [bold, link] },
            { type: 'text', text: ' to ', marks: [bold] },
            { type: 'text', text: 'varn', marks: [bold, link] },
            { type: 'text', text: '.', marks: [bold] },
            { type: 'text', text: ' End' },
          ],
        },
      ],
    })
    // The input is left alone.
    expect(doc.content[0]?.content[0]).toEqual({ type: 'text', text: 'Varn' })
  })

  it('counts in UTF-16 and skips occurrences that moved', () => {
    const doc = {
      type: 'doc',
      content: [{ type: 'paragraph', content: [{ type: 'text', text: '🐉 Varn' }] }],
    }
    const result = linkOccurrences(
      doc,
      [
        { path: [0, 0], offset: 3, length: 4, text: 'Varn' },
        { path: [0, 0], offset: 0, length: 4, text: 'Varn' },
        { path: [0, 5], offset: 0, length: 4, text: 'Varn' },
      ],
      'v',
    )
    expect(result).toMatchObject({ linked: 1, skipped: 2 })
    expect(result.doc).toEqual({
      type: 'doc',
      content: [
        {
          type: 'paragraph',
          content: [
            { type: 'text', text: '🐉 ' },
            { type: 'text', text: 'Varn', marks: [link] },
          ],
        },
      ],
    })
  })
})
