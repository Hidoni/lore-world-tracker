import type { AnyExtension, Attributes } from '@tiptap/core'
import { Node } from '@tiptap/core'
import Link from '@tiptap/extension-link'
import { OrderedList } from '@tiptap/extension-list'
import { TableCell, TableHeader, TableKit } from '@tiptap/extension-table'
import { CharacterCount, Placeholder } from '@tiptap/extensions'
import StarterKit from '@tiptap/starter-kit'

import { EntityLinkMark, EntityLinkSuggestions } from './entity-link'
import { isSafeHref } from './schema'
import type { SuggestionBridge } from './suggestion-state'

/** Drops an attribute the server schema doesn't store (an unknown attribute fails the save). */
function without(attributes: Attributes | undefined, ...names: string[]): Attributes {
  return Object.fromEntries(
    Object.entries(attributes ?? {}).filter(([name]) => !names.includes(name)),
  )
}

// `type` (the list-style), `title` and cell `align` aren't in the server schema (frontend.md §6).
const ServerOrderedList = OrderedList.extend({
  addAttributes() {
    return without(this.parent?.(), 'type')
  },
})
const ServerTableCell = TableCell.extend({
  addAttributes() {
    return without(this.parent?.(), 'align')
  },
})
const ServerTableHeader = TableHeader.extend({
  addAttributes() {
    return without(this.parent?.(), 'align')
  },
})
const ServerLink = Link.extend({
  addAttributes() {
    return without(this.parent?.(), 'title')
  },
})

/**
 * Nodes later editor issues give a UI (`callout`, `visibilityBlock`: #64; `timeRef`: #86). Until
 * then they're kept as they are, so editing a body that has them doesn't lose them.
 */
const Callout = Node.create({
  name: 'callout',
  group: 'block',
  content: 'block+',
  defining: true,
  addAttributes: () => ({ tone: { default: 'note' } }),
  parseHTML: () => [{ tag: 'aside[data-callout]' }],
  renderHTML: ({ node }) => [
    'aside',
    { 'data-callout': node.attrs.tone as string, class: 'callout' },
    0,
  ],
})
const VisibilityBlock = Node.create({
  name: 'visibilityBlock',
  group: 'block',
  content: 'block+',
  defining: true,
  addAttributes: () => ({ level: { default: 'spoiler' }, label: { default: null } }),
  parseHTML: () => [{ tag: 'section[data-visibility]' }],
  renderHTML: ({ node }) => [
    'section',
    { 'data-visibility': node.attrs.level as string, class: 'visibility-block' },
    0,
  ],
})
const TimeRef = Node.create({
  name: 'timeRef',
  group: 'inline',
  inline: true,
  atom: true,
  addAttributes: () => ({ timePoint: { default: null }, ref: { default: null } }),
  parseHTML: () => [{ tag: 'span[data-time-ref]' }],
  renderHTML: () => ['span', { 'data-time-ref': '', class: 'time-ref' }, 'date'],
})

/** Editor extensions for the stored schema (frontend.md §6), plus the editing helpers. */
export function editorExtensions(
  options: {
    placeholder?: string
    bridge?: SuggestionBridge | null
    extra?: readonly AnyExtension[]
  } = {},
): AnyExtension[] {
  return [
    StarterKit.configure({
      heading: { levels: [1, 2, 3, 4] },
      underline: false,
      link: false,
      orderedList: false,
    }),
    ServerOrderedList,
    ServerLink.configure({
      openOnClick: false,
      autolink: true,
      protocols: ['mailto'],
      isAllowedUri: (url) => isSafeHref(url),
      shouldAutoLink: (url) => isSafeHref(url),
    }),
    TableKit.configure({ table: { resizable: false }, tableCell: false, tableHeader: false }),
    ServerTableCell,
    ServerTableHeader,
    Callout,
    VisibilityBlock,
    TimeRef,
    EntityLinkMark,
    EntityLinkSuggestions.configure({ bridge: options.bridge ?? null }),
    Placeholder.configure({ placeholder: options.placeholder ?? 'Write…' }),
    CharacterCount,
    ...(options.extra ?? []),
  ]
}
