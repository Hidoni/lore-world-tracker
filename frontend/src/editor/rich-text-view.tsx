import type { SlotRef, TimePoint } from '@lore/chronology'
import type { ReactNode } from 'react'

import { TimeRefView } from '@/core/time'

import { EntityLinkView } from './entity-link-view'
import { isSafeHref, type RichTextDoc } from './schema'

type Mark = NonNullable<RichTextDoc['marks']>[number]

const text = (value: unknown, fallback: string): string =>
  typeof value === 'string' ? value : fallback

const attr = (node: { attrs?: Record<string, unknown> }, name: string): unknown =>
  node.attrs?.[name]

function withMark(vault: string, mark: Mark, content: ReactNode, key: string): ReactNode {
  switch (mark.type) {
    case 'bold':
      return <strong key={key}>{content}</strong>
    case 'italic':
      return <em key={key}>{content}</em>
    case 'strike':
      return <s key={key}>{content}</s>
    case 'code':
      return (
        <code key={key} className="rounded bg-muted px-1 font-mono text-[0.9em]">
          {content}
        </code>
      )
    case 'link': {
      const href = attr(mark, 'href')
      if (!isSafeHref(href)) return content
      return (
        <a
          key={key}
          href={href}
          target="_blank"
          rel="noopener noreferrer nofollow"
          className="text-primary underline underline-offset-2"
        >
          {content}
        </a>
      )
    }
    case 'entityLink': {
      const id = attr(mark, 'entityId')
      if (typeof id !== 'string') return content
      return (
        <EntityLinkView key={key} vault={vault} entityId={id} navigate>
          {content}
        </EntityLinkView>
      )
    }
    default:
      return content
  }
}

function children(vault: string, node: RichTextDoc, path: string): ReactNode[] {
  return (node.content ?? []).map((child, index) => renderNode(vault, child, `${path}.${index}`))
}

function renderNode(vault: string, node: RichTextDoc, key: string): ReactNode {
  const inner = () => children(vault, node, key)
  switch (node.type) {
    case 'text': {
      // The innermost mark wraps the text first; entity links end up outermost.
      const marks = [...(node.marks ?? [])].sort(
        (a, b) => Number(a.type === 'entityLink') - Number(b.type === 'entityLink'),
      )
      return marks.reduce<ReactNode>(
        (content, mark, index) => withMark(vault, mark, content, `${key}m${index}`),
        node.text ?? '',
      )
    }
    case 'paragraph':
      return <p key={key}>{inner()}</p>
    case 'heading': {
      const level = Number(attr(node, 'level'))
      const Tag = (['h1', 'h2', 'h3', 'h4'] as const)[Math.min(Math.max(level, 1), 4) - 1] ?? 'h2'
      return <Tag key={key}>{inner()}</Tag>
    }
    case 'bulletList':
      return <ul key={key}>{inner()}</ul>
    case 'orderedList': {
      const start = attr(node, 'start')
      return (
        <ol key={key} start={typeof start === 'number' ? start : undefined}>
          {inner()}
        </ol>
      )
    }
    case 'listItem':
      return <li key={key}>{inner()}</li>
    case 'blockquote':
      return <blockquote key={key}>{inner()}</blockquote>
    case 'codeBlock':
      return (
        <pre key={key}>
          <code>{(node.content ?? []).map((child) => child.text ?? '').join('')}</code>
        </pre>
      )
    case 'horizontalRule':
      return <hr key={key} />
    case 'hardBreak':
      return <br key={key} />
    case 'table':
      return (
        <table key={key}>
          <tbody>{inner()}</tbody>
        </table>
      )
    case 'tableRow':
      return <tr key={key}>{inner()}</tr>
    case 'tableCell':
    case 'tableHeader': {
      const Tag = node.type === 'tableHeader' ? 'th' : 'td'
      const colspan = attr(node, 'colspan')
      const rowspan = attr(node, 'rowspan')
      return (
        <Tag
          key={key}
          colSpan={typeof colspan === 'number' ? colspan : undefined}
          rowSpan={typeof rowspan === 'number' ? rowspan : undefined}
        >
          {inner()}
        </Tag>
      )
    }
    case 'callout':
      return (
        <aside
          key={key}
          className="callout rounded-md border p-3"
          data-callout={text(attr(node, 'tone'), 'note')}
        >
          {inner()}
        </aside>
      )
    case 'visibilityBlock': {
      // Private blocks never reach readers (the server removes them): authors see them framed, as
      // in the trash. Spoilers fold until unfolded.
      const label = text(attr(node, 'label'), '')
      if (attr(node, 'level') === 'private') {
        return (
          <section key={key} className="visibility-block" data-visibility="private">
            <p className="text-xs font-medium text-muted-foreground">
              Private{label && `: ${label}`}
            </p>
            {inner()}
          </section>
        )
      }
      return (
        <details key={key} className="visibility-block" data-visibility="spoiler">
          <summary className="cursor-pointer text-sm font-medium">
            Spoiler{label && `: ${label}`}
          </summary>
          {inner()}
        </details>
      )
    }
    case 'timeRef':
      return (
        <TimeRefView
          key={key}
          vault={vault}
          timePoint={(attr(node, 'timePoint') as TimePoint | null | undefined) ?? null}
          slotRef={(attr(node, 'ref') as SlotRef | null | undefined) ?? null}
          hidden={attr(node, 'hidden_ref') === true}
        />
      )
    default:
      // Module nodes without a renderer yet: their content, if any.
      return <span key={key}>{inner()}</span>
  }
}

/** The read-only renderer (reader mode and previews), same schema as the editor. */
export function RichTextView({ vault, doc }: { vault: string; doc: RichTextDoc | null }) {
  if (!doc || (doc.content ?? []).length === 0) return null
  return <div className="rich-text">{children(vault, doc, 'n')}</div>
}
