import { Extension } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Marked } from 'marked'

/** An entity a `[[Name]]` resolved to. */
export interface ResolvedName {
  id: string
  name: string
}

/** Resolves a name to the one entity it names, or `null` (none, or several). */
export type NameResolver = (name: string) => Promise<ResolvedName | null>

/** `[[Name]]` or `[[Name|label]]`. */
const WIKI_LINK = /\[\[([^\]|\n]+?)(?:\|([^\]\n]+?))?\]\]/g
/** Block or inline Markdown worth converting (headings, lists, quotes, code, emphasis, links). */
const MARKDOWN =
  /(^|\n) {0,3}(#{1,6} |[-*+] |\d+[.)] |> ?|```|-{3,}\s*(\n|$)|\|.*\|)|\*\*[^*\n]+\*\*|__[^_\n]+__|`[^`\n]+`|\[[^\]\n]+\]\([^)\n]+\)/

const escapeHtml = (text: string) => text.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`)
/** Text that Markdown leaves as written. */
const escapeMarkdown = (text: string) => text.replace(/[\\[\]()*_`<>#]/g, '\\$&')

export function looksLikeMarkdown(text: string): boolean {
  return MARKDOWN.test(text) || new RegExp(WIKI_LINK.source).test(text)
}

const ENTITY = 'entity:'

// Raw HTML stays text, code blocks keep valid language names only, images become their alt text (neither is in the schema); `entity:` links
// become entity links.
const marked = new Marked({
  gfm: true,
  renderer: {
    html: ({ text }) => escapeHtml(text),
    // The server takes a plain language name (`codeBlock.language`); anything else is dropped.
    code: ({ text, lang }) => {
      const language = lang?.split(/\s/)[0] ?? ''
      const attr = /^[A-Za-z0-9_+#.-]{1,40}$/.test(language)
        ? ` class="language-${escapeHtml(language)}"`
        : ''
      return `<pre><code${attr}>${escapeHtml(text)}</code></pre>`
    },
    image: ({ text }) => escapeHtml(text),
    link({ href, tokens }) {
      const text = this.parser.parseInline(tokens)
      if (href.startsWith(ENTITY)) {
        return `<span data-entity-id="${escapeHtml(href.slice(ENTITY.length))}">${text}</span>`
      }
      return `<a href="${escapeHtml(href)}">${text}</a>`
    },
  },
})

/**
 * Markdown as HTML for the editor, with `[[Name]]` and `[[Name|label]]` as entity links where the
 * name resolves to exactly one entity; the others stay plain text and are returned. One line of
 * text stays inline (it joins the paragraph it's pasted into).
 */
export async function markdownToHtml(
  text: string,
  resolve: NameResolver,
): Promise<{ html: string; unresolved: string[] }> {
  const names = [...new Set([...text.matchAll(WIKI_LINK)].map((match) => (match[1] ?? '').trim()))]
  const resolved = new Map(
    await Promise.all(names.map(async (name) => [name, await resolve(name)] as const)),
  )
  const unresolved = names.filter((name) => resolved.get(name) === null)
  const markdown = text.replace(WIKI_LINK, (_whole, rawName: string, label: string | undefined) => {
    const name = rawName.trim()
    const shown = escapeMarkdown((label ?? name).trim())
    const entity = resolved.get(name)
    return entity ? `[${shown}](${ENTITY}${entity.id})` : shown
  })
  const html = text.includes('\n')
    ? marked.parse(markdown, { async: false })
    : marked.parseInline(markdown, { async: false })
  return { html, unresolved }
}

/**
 * Pasting plain text that looks like Markdown (or holds `[[Name]]`s) converts it (frontend.md §6).
 * Rich pastes (with HTML) are left to the editor.
 */
export const MarkdownPaste = Extension.create<{
  resolve: NameResolver | null
  onUnresolved: (names: string[]) => void
}>({
  name: 'markdownPaste',
  addOptions() {
    return { resolve: null, onUnresolved: () => undefined }
  },
  addProseMirrorPlugins() {
    const { editor } = this
    const { resolve, onUnresolved } = this.options
    if (resolve === null) return []
    return [
      new Plugin({
        key: new PluginKey('markdownPaste'),
        props: {
          handlePaste: (view, event) => {
            const text = event.clipboardData?.getData('text/plain') ?? ''
            const html = event.clipboardData?.getData('text/html') ?? ''
            if (html !== '' || !looksLikeMarkdown(text)) {
              return false
            }
            const { from, to } = view.state.selection
            const before = view.state.doc
            void markdownToHtml(text, resolve).then(({ html, unresolved }) => {
              // Where the paste happened, unless the document changed meanwhile.
              const range = view.state.doc.eq(before) ? { from, to } : view.state.selection
              editor.chain().focus().insertContentAt({ from: range.from, to: range.to }, html).run()
              if (unresolved.length > 0) onUnresolved(unresolved)
            })
            return true
          },
        },
      }),
    ]
  },
})
