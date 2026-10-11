import type { Editor } from '@tiptap/core'

/** An entry of the slash menu (`/`): it runs after the typed `/query` is removed. */
export interface SlashItem {
  id: string
  title: string
  description?: string
  /** Extra words it's found by. */
  keywords?: readonly string[]
  run: (editor: Editor) => void
}

/** The core block types (frontend.md §6). */
export const CORE_SLASH_ITEMS: readonly SlashItem[] = [
  {
    id: 'paragraph',
    title: 'Text',
    keywords: ['paragraph'],
    run: (e) => e.chain().focus().setParagraph().run(),
  },
  ...([1, 2, 3, 4] as const).map((level): SlashItem => ({
    id: `heading${level}`,
    title: `Heading ${level}`,
    keywords: ['title', `h${level}`],
    run: (e) => e.chain().focus().setHeading({ level }).run(),
  })),
  {
    id: 'bulletList',
    title: 'Bullet list',
    keywords: ['ul', 'unordered'],
    run: (e) => e.chain().focus().toggleBulletList().run(),
  },
  {
    id: 'orderedList',
    title: 'Numbered list',
    keywords: ['ol', 'ordered'],
    run: (e) => e.chain().focus().toggleOrderedList().run(),
  },
  {
    id: 'blockquote',
    title: 'Quote',
    keywords: ['blockquote'],
    run: (e) => e.chain().focus().toggleBlockquote().run(),
  },
  {
    id: 'codeBlock',
    title: 'Code block',
    keywords: ['pre'],
    run: (e) => e.chain().focus().toggleCodeBlock().run(),
  },
  {
    id: 'horizontalRule',
    title: 'Divider',
    keywords: ['hr', 'rule', 'line'],
    run: (e) => e.chain().focus().setHorizontalRule().run(),
  },
  {
    id: 'table',
    title: 'Table',
    keywords: ['grid'],
    run: (e) => e.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run(),
  },
  {
    id: 'callout',
    title: 'Callout',
    description: 'A note around blocks',
    keywords: ['note', 'info', 'aside'],
    run: (e) => e.chain().focus().setCallout('note').run(),
  },
  {
    id: 'calloutWarning',
    title: 'Warning callout',
    keywords: ['caution', 'alert'],
    run: (e) => e.chain().focus().setCallout('warning').run(),
  },
  {
    id: 'calloutQuote',
    title: 'Quote callout',
    keywords: ['citation', 'epigraph'],
    run: (e) => e.chain().focus().setCallout('quote').run(),
  },
  {
    id: 'spoiler',
    title: 'Spoiler block',
    description: 'Readers unfold it',
    keywords: ['secret', 'hidden', 'visibility'],
    run: (e) => e.chain().focus().setVisibilityBlock('spoiler').run(),
  },
  {
    id: 'private',
    title: 'Private block',
    description: 'Only authors see it',
    keywords: ['secret', 'gm', 'notes', 'visibility'],
    run: (e) => e.chain().focus().setVisibilityBlock('private').run(),
  },
]

/**
 * The slash menu's items: the core ones, then those of module extensions (`editorExtensions`),
 * which list theirs in the option `slashItems` (`SlashItem[]`).
 */
export function slashItems(editor: Editor): SlashItem[] {
  const contributed = editor.extensionManager.extensions.flatMap((extension) => {
    const items = (extension.options as { slashItems?: unknown } | undefined)?.slashItems
    return Array.isArray(items) ? (items as SlashItem[]) : []
  })
  return [...CORE_SLASH_ITEMS, ...contributed]
}

/** The items matching what was typed after `/` (title words or keywords start with it). */
export function filterSlashItems(items: readonly SlashItem[], query: string): SlashItem[] {
  const q = query.trim().toLowerCase()
  if (q === '') return [...items]
  return items.filter((item) =>
    [
      ...item.title.toLowerCase().split(/\s+/),
      item.title.toLowerCase(),
      ...(item.keywords ?? []),
    ].some((word) => word.startsWith(q)),
  )
}
