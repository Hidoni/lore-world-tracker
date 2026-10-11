import { Extension, Mark, mergeAttributes, type Editor, type Range } from '@tiptap/core'
import { PluginKey } from '@tiptap/pm/state'
import Suggestion, { type SuggestionProps } from '@tiptap/suggestion'

import type { SuggestionBridge, SuggestionState } from './suggestion-state'

/** The internal link mark (`entityLink`, attrs `{entityId}`; frontend.md §6). */
export const EntityLinkMark = Mark.create({
  name: 'entityLink',
  // Typing after a link doesn't extend it.
  inclusive: false,
  // Before the `link` mark, so an `<a data-entity-id>` is an entity link.
  priority: 1100,
  addAttributes() {
    return {
      entityId: {
        default: null,
        parseHTML: (element) => element.getAttribute('data-entity-id'),
        renderHTML: (attributes: { entityId?: string | null }) =>
          attributes.entityId ? { 'data-entity-id': attributes.entityId } : {},
      },
    }
  },
  parseHTML() {
    return [{ tag: 'a[data-entity-id]' }, { tag: 'span[data-entity-id]' }]
  },
  renderHTML({ HTMLAttributes }) {
    return ['span', mergeAttributes({ class: 'entity-link' }, HTMLAttributes), 0]
  },
})

/** Replaces `range` with a link to the entity, followed by a space. */
export function insertEntityLink(
  editor: Editor,
  range: Range,
  entity: { id: string; name: string },
): void {
  editor
    .chain()
    .focus()
    .insertContentAt(range, [
      {
        type: 'text',
        text: entity.name,
        marks: [{ type: 'entityLink', attrs: { entityId: entity.id } }],
      },
      { type: 'text', text: ' ' },
    ])
    .run()
}

/** `[[Name` may be closed by the author: `]]` isn't part of the query. */
export function cleanQuery(trigger: SuggestionState['trigger'], query: string): string {
  return (trigger === '[[' ? query.replace(/\]{1,2}$/, '') : query).trim()
}

function suggestion(editor: Editor, bridge: SuggestionBridge, trigger: SuggestionState['trigger']) {
  const publish = (props: SuggestionProps) => {
    const rect = props.clientRect?.() ?? null
    bridge.publish({
      trigger,
      query: cleanQuery(trigger, props.query),
      range: props.range,
      rect: rect ? { left: rect.left, bottom: rect.bottom } : null,
    })
  }
  return Suggestion({
    editor,
    pluginKey: new PluginKey(`entityLink${trigger}`),
    char: trigger,
    // `[[Crown of Ages`: names have spaces. `@` stops at a space, like mentions elsewhere.
    allowSpaces: trigger === '[[',
    items: () => [],
    render: () => ({
      onStart: publish,
      onUpdate: publish,
      onExit: () => {
        bridge.publish(null)
      },
      onKeyDown: ({ event }) => {
        if (event.key === 'Escape') {
          bridge.publish(null)
          return true
        }
        return bridge.keyHandler?.(event) ?? false
      },
    }),
  })
}

/** The `[[` and `@` suggestions: they publish to the bridge; the menu searches and inserts. */
export const EntityLinkSuggestions = Extension.create<{ bridge: SuggestionBridge | null }>({
  name: 'entityLinkSuggestions',
  addOptions() {
    return { bridge: null }
  },
  addProseMirrorPlugins() {
    const { bridge } = this.options
    if (bridge === null) return []
    return [suggestion(this.editor, bridge, '[['), suggestion(this.editor, bridge, '@')]
  },
})
