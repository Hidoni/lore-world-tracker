import type { JSONContent } from '@tiptap/core'

/**
 * The rich-text node schema version (`body_schema_version`), shared with the backend's
 * `lore.core.richtext.SCHEMA_VERSION` (a test compares them).
 */
export const RICH_TEXT_SCHEMA_VERSION = 1

/** A TipTap/ProseMirror document as stored (`entities.body`, `rich_text` fields). */
export type RichTextDoc = JSONContent

/** The editor's empty document. */
export const EMPTY_DOC: RichTextDoc = { type: 'doc', content: [{ type: 'paragraph' }] }

/** Whether a value looks like a document (`{type: 'doc'}`). */
export function isDoc(value: unknown): value is RichTextDoc {
  return typeof value === 'object' && value !== null && (value as { type?: unknown }).type === 'doc'
}

/** `http(s)` and `mailto` links only: the server drops other links (frontend.md §6). */
export function isSafeHref(href: unknown): href is string {
  if (typeof href !== 'string' || href.length > 2048 || /\s/.test(href)) return false
  try {
    const url = new URL(href)
    if (url.protocol === 'mailto:') return true
    return (url.protocol === 'http:' || url.protocol === 'https:') && url.hostname !== ''
  } catch {
    return false
  }
}

/** The entity ids a document's `entityLink` marks point at, in order, without repeats. */
export function linkedEntityIds(doc: RichTextDoc | null | undefined): string[] {
  const found = new Set<string>()
  const walk = (node: RichTextDoc) => {
    for (const mark of node.marks ?? []) {
      const id = (mark.attrs as { entityId?: unknown } | undefined)?.entityId
      if (mark.type === 'entityLink' && typeof id === 'string') found.add(id)
    }
    for (const child of node.content ?? []) walk(child)
  }
  if (doc) walk(doc)
  return [...found]
}
