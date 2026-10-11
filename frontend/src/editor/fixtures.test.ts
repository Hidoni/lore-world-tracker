import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'

import { Editor } from '@tiptap/core'
import { describe, expect, it } from 'vitest'

import { editorExtensions } from './extensions'
import { markdownToHtml } from './markdown-paste'
import type { RichTextDoc } from './schema'
import { CORE_SLASH_ITEMS } from './slash-items'

// Documents the editor produces, shared with the backend: `backend/tests/test_richtext.py` checks
// that the server accepts each one unchanged (contract). `UPDATE_FIXTURES=1` rewrites them.
const DIR = path.resolve(process.cwd(), '../spec/richtext/fixtures')
const CROWN = '0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b'

function matchesFixture(name: string, doc: RichTextDoc) {
  const file = path.join(DIR, `${name}.json`)
  if (process.env.UPDATE_FIXTURES === '1' || !existsSync(file)) {
    writeFileSync(file, `${JSON.stringify(doc, null, 2)}\n`)
  }
  expect(doc).toEqual(JSON.parse(readFileSync(file, 'utf8')))
}

function makeEditor(content = '') {
  return new Editor({ extensions: editorExtensions(), content })
}

/** Appends a paragraph at the top level and runs a slash item on it (as an author would). */
function block(editor: Editor, text: string, item?: string) {
  editor.commands.insertContentAt(editor.state.doc.content.size, `<p>${text}</p>`)
  editor.commands.focus('end')
  if (item) CORE_SLASH_ITEMS.find((candidate) => candidate.id === item)?.run(editor)
}

describe('editor fixtures (backend contract)', () => {
  it('blocks: every slash item', () => {
    const editor = makeEditor('<p>Intro</p>')
    for (const item of CORE_SLASH_ITEMS) {
      if (item.id === 'horizontalRule' || item.id === 'table') {
        editor.commands.focus('end')
        item.run(editor)
      } else {
        block(editor, item.title, item.id)
      }
    }
    // A labelled spoiler, and a callout inside a private block.
    block(editor, 'The twist', 'spoiler')
    editor.commands.updateAttributes('visibilityBlock', { label: 'Book 2' })
    block(editor, 'GM notes', 'private')
    CORE_SLASH_ITEMS.find((item) => item.id === 'calloutWarning')?.run(editor)
    matchesFixture('blocks', editor.getJSON())
    editor.destroy()
  })

  it('marks, links and tables', () => {
    const editor = makeEditor(`
      <h2>Lore</h2>
      <p><strong>b</strong> <em>i</em> <s>s</s> <code>c</code>
        <a href="https://example.com/x">web</a> <a href="mailto:a@b.c">mail</a>
        <span data-entity-id="${CROWN}">the Crown</span><br>next</p>
      <ol start="3"><li><p>three</p></li></ol>
      <pre><code class="language-py">x = 1</code></pre>
      <table><tr><th><p>h</p></th><th><p>h2</p></th></tr><tr><td colspan="2"><p>c</p></td></tr></table>
    `)
    matchesFixture('marks', editor.getJSON())
    editor.destroy()
  })

  it('pasted Markdown with [[Name]] links', async () => {
    const markdown = [
      '# The Crown',
      '',
      'Forged by **[[Smith]]**, worn by [[Crown|the crown]]’s heirs and [[Nobody]].',
      '',
      '- one',
      '- two with `code`',
      '',
      '1. first',
      '',
      '> A quote',
      '',
      '```py {linenos}',
      'x = 1',
      '```',
      '',
      '---',
      '',
      'See [the site](https://example.com) <b>raw</b> ![img](https://e.com/i.png)',
    ].join('\n')
    const { html, unresolved } = await markdownToHtml(markdown, (name) =>
      Promise.resolve(name === 'Crown' ? { id: CROWN, name: 'Crown' } : null),
    )
    expect(unresolved).toEqual(['Smith', 'Nobody'])
    const editor = makeEditor(html)
    matchesFixture('markdown-paste', editor.getJSON())
    editor.destroy()
  })
})
