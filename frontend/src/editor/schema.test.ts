import { readFileSync } from 'node:fs'
import path from 'node:path'

import { Editor } from '@tiptap/core'
import { describe, expect, it } from 'vitest'

import { editorExtensions } from './extensions'
import { RICH_TEXT_SCHEMA_VERSION, isSafeHref, linkedEntityIds, type RichTextDoc } from './schema'

// The server schema (lore.core.richtext.schema): node and mark types and the attributes each may
// carry. An attribute the server doesn't know fails the save, so the editor must not produce one.
const SERVER_NODES: Record<string, readonly string[]> = {
  doc: [],
  paragraph: [],
  heading: ['level'],
  blockquote: [],
  bulletList: [],
  orderedList: ['start'],
  listItem: [],
  codeBlock: ['language'],
  horizontalRule: [],
  table: [],
  tableRow: [],
  tableCell: ['colspan', 'rowspan', 'colwidth'],
  tableHeader: ['colspan', 'rowspan', 'colwidth'],
  visibilityBlock: ['level', 'label'],
  callout: ['tone'],
  text: [],
  hardBreak: [],
  timeRef: ['timePoint', 'ref'],
}
// `target`, `rel` and `class` of links are editor defaults the server ignores.
const SERVER_MARKS: Record<string, readonly string[]> = {
  bold: [],
  italic: [],
  strike: [],
  code: [],
  link: ['href', 'target', 'rel', 'class'],
  entityLink: ['entityId'],
}

const ID = '0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b'
const HTML = `
  <h1>Title</h1><h4>Small</h4>
  <p><strong>b</strong> <em>i</em> <s>s</s> <code>c</code> <u>u</u>
    <a href="https://example.com" title="t">web</a> <a href="javascript:alert(1)">bad</a>
    <span data-entity-id="${ID}">Ana</span><br>next</p>
  <ul><li><p>one</p></li></ul><ol start="3" type="a"><li><p>three</p></li></ol>
  <blockquote><p>q</p></blockquote><pre><code class="language-py">x = 1</code></pre><hr>
  <table><tr><th><p>h</p></th></tr><tr><td colspan="2"><p>c</p></td></tr></table>
`

function makeEditor(content: RichTextDoc | string) {
  return new Editor({ extensions: editorExtensions(), content })
}

function check(node: RichTextDoc, path: string, problems: string[]) {
  const allowed = SERVER_NODES[node.type ?? '']
  if (allowed === undefined) problems.push(`${path}: node ${String(node.type)}`)
  for (const key of Object.keys(node.attrs ?? {})) {
    if (!allowed?.includes(key)) problems.push(`${path}: ${String(node.type)}.${key}`)
  }
  for (const mark of node.marks ?? []) {
    const marks = SERVER_MARKS[mark.type]
    if (marks === undefined) problems.push(`${path}: mark ${mark.type}`)
    for (const key of Object.keys(mark.attrs ?? {})) {
      if (!marks?.includes(key)) problems.push(`${path}: ${mark.type}.${key}`)
    }
  }
  ;(node.content ?? []).forEach((child, index) => {
    check(child, `${path}.${index}`, problems)
  })
}

describe('editor schema', () => {
  it('shares the schema version with the backend', () => {
    const backend = readFileSync(
      // vitest runs in frontend/.
      path.resolve(process.cwd(), '../backend/src/lore/core/richtext/__init__.py'),
      'utf8',
    )
    expect(backend).toContain(`SCHEMA_VERSION = ${RICH_TEXT_SCHEMA_VERSION}\n`)
  })

  it('produces only node types, marks and attributes the server accepts', () => {
    const editor = makeEditor(HTML)
    const doc = editor.getJSON()
    const problems: string[] = []
    check(doc, 'doc', problems)
    expect(problems).toEqual([])
    const json = JSON.stringify(doc)
    // Underline isn't in the schema; unsafe links lose the link, not the text.
    expect(json).not.toContain('underline')
    expect(json).not.toContain('javascript')
    expect(json).toContain(' bad ')
    expect(linkedEntityIds(doc)).toEqual([ID])
    editor.destroy()
  })

  it('keeps nodes later editor issues give a UI (callouts, visibility blocks, time refs)', () => {
    const doc: RichTextDoc = {
      type: 'doc',
      content: [
        {
          type: 'callout',
          attrs: { tone: 'warning' },
          content: [{ type: 'paragraph', content: [{ type: 'text', text: 'careful' }] }],
        },
        {
          type: 'visibilityBlock',
          attrs: { level: 'private', label: 'GM' },
          content: [
            {
              type: 'paragraph',
              content: [
                { type: 'text', text: 'on ' },
                {
                  type: 'timeRef',
                  attrs: { timePoint: null, ref: { type: 'event', id: ID, slot: 'start' } },
                },
              ],
            },
          ],
        },
      ],
    }
    const editor = makeEditor(doc)
    expect(editor.getJSON()).toEqual(doc)
    editor.destroy()
  })

  it('allows http(s) and mailto links only', () => {
    expect(isSafeHref('https://example.com/a')).toBe(true)
    expect(isSafeHref('mailto:a@b.c')).toBe(true)
    expect(isSafeHref('javascript:alert(1)')).toBe(false)
    expect(isSafeHref('https://exa mple.com')).toBe(false)
    expect(isSafeHref('/relative')).toBe(false)
  })
})
