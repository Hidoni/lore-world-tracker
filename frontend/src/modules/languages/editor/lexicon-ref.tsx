import { Node, type Editor, type Range } from '@tiptap/core'
import { PluginKey } from '@tiptap/pm/state'
import {
  NodeViewWrapper,
  ReactNodeViewRenderer,
  ReactRenderer,
  type ReactNodeViewProps,
} from '@tiptap/react'
import Suggestion from '@tiptap/suggestion'
import { useParams } from '@tanstack/react-router'

import { LexiconRefView } from './lexicon-ref-view'
import { WordMenu, type WordMenuHandle, type WordMenuProps } from './word-menu'

/** What `@@` opens the word menu with. */
export const LEXICON_TRIGGER = '@@'

function LexiconRefNodeView({ node }: ReactNodeViewProps) {
  const vault = useParams({ strict: false }).vault
  const entryId = typeof node.attrs.entryId === 'string' ? node.attrs.entryId : null
  return (
    <NodeViewWrapper as="span" className="inline">
      {vault === undefined ? (
        <span className="lexicon-ref">a word</span>
      ) : (
        <LexiconRefView vault={vault} entryId={entryId} />
      )}
    </NodeViewWrapper>
  )
}

/** Replaces `range` with a reference to the word, followed by a space. */
export function insertLexiconRef(
  editor: Editor,
  range: Range,
  word: { entryId: string; languageId: string },
): void {
  editor
    .chain()
    .focus()
    .insertContentAt(range, [
      { type: 'lexiconRef', attrs: word },
      { type: 'text', text: ' ' },
    ])
    .run()
}

/**
 * `lexiconRef` (docs/modules/languages.md): an inline word of a lexicon, `{entryId, languageId}`,
 * shown as its headword with the glosses in a tooltip. Typing `@@` opens a menu of words (search
 * by headword, romanization or gloss); the slash menu's "Word" starts one.
 */
export const LexiconRef = Node.create({
  name: 'lexiconRef',
  group: 'inline',
  inline: true,
  atom: true,
  selectable: true,
  addOptions: () => ({
    slashItems: [
      {
        id: 'lexiconRef',
        title: 'Word',
        description: 'A word of a lexicon, with its gloss',
        keywords: ['lexicon', 'dictionary', 'language', 'gloss'],
        run: (editor: Editor) => {
          editor.chain().focus().insertContent(LEXICON_TRIGGER).run()
        },
      },
    ],
  }),
  addAttributes: () => ({
    entryId: {
      default: null,
      parseHTML: (element) => element.getAttribute('data-entry-id'),
      renderHTML: (attributes: { entryId?: string | null }) =>
        attributes.entryId ? { 'data-entry-id': attributes.entryId } : {},
    },
    languageId: {
      default: null,
      parseHTML: (element) => element.getAttribute('data-language-id'),
      renderHTML: (attributes: { languageId?: string | null }) =>
        attributes.languageId ? { 'data-language-id': attributes.languageId } : {},
    },
  }),
  parseHTML: () => [{ tag: 'span[data-lexicon-ref]' }],
  renderHTML: ({ HTMLAttributes }) => [
    'span',
    { 'data-lexicon-ref': '', class: 'lexicon-ref', ...HTMLAttributes },
    'word',
  ],
  renderText: () => 'word',
  addNodeView: () => ReactNodeViewRenderer(LexiconRefNodeView, { as: 'span' }),
  addProseMirrorPlugins() {
    const editor = this.editor
    return [
      Suggestion<unknown>({
        editor,
        pluginKey: new PluginKey('suggestionLexicon'),
        char: LEXICON_TRIGGER,
        items: () => [],
        render: () => {
          let menu: ReactRenderer<WordMenuHandle, WordMenuProps> | null = null
          const props = (query: string, range: Range, rect: DOMRect | null): WordMenuProps => ({
            query,
            rect: rect ? { left: rect.left, bottom: rect.bottom } : null,
            onPick: (word) => {
              insertLexiconRef(editor, range, word)
            },
          })
          return {
            onStart: (start) => {
              menu = new ReactRenderer(WordMenu, {
                editor,
                props: props(start.query, start.range, start.clientRect?.() ?? null),
              })
            },
            onUpdate: (update) => {
              menu?.updateProps(props(update.query, update.range, update.clientRect?.() ?? null))
            },
            onExit: () => {
              menu?.destroy()
              menu = null
            },
            onKeyDown: ({ event }) => {
              if (event.key === 'Escape') {
                menu?.destroy()
                menu = null
                return true
              }
              return menu?.ref?.onKeyDown(event) ?? false
            },
          }
        },
      }),
    ]
  },
})
