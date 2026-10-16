import { Node, type Editor } from '@tiptap/core'
import {
  NodeViewContent,
  NodeViewWrapper,
  ReactNodeViewRenderer,
  type ReactNodeViewProps,
} from '@tiptap/react'
import { EyeOffIcon, InfoIcon, LockIcon, QuoteIcon, TriangleAlertIcon, XIcon } from 'lucide-react'

import { cn } from '@/lib/utils'

import { CALLOUT_TONES, type BlockLevel, type CalloutTone } from './block-kinds'

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    callout: { setCallout: (tone?: CalloutTone) => ReturnType }
    visibilityBlock: { setVisibilityBlock: (level: BlockLevel, label?: string) => ReturnType }
  }
}

const SELECT =
  'h-7 rounded border border-input bg-background px-1 text-xs focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none'

/** Replaces a wrapper node by its content (the "remove" of a callout or a visibility block). */
function unwrap(editor: Editor, getPos: () => number | undefined) {
  const pos = getPos()
  if (pos === undefined) return
  const node = editor.state.doc.nodeAt(pos)
  if (node === null) return
  editor.view.dispatch(editor.state.tr.replaceWith(pos, pos + node.nodeSize, node.content))
  editor.commands.focus()
}

const TONE_ICON = { note: InfoIcon, warning: TriangleAlertIcon, quote: QuoteIcon }
const TONE_LABEL: Record<CalloutTone, string> = { note: 'Note', warning: 'Warning', quote: 'Quote' }

function CalloutView({ node, editor, getPos, updateAttributes }: ReactNodeViewProps) {
  const tone = (node.attrs.tone as CalloutTone | undefined) ?? 'note'
  const Icon = TONE_ICON[tone]
  return (
    <NodeViewWrapper
      as="aside"
      data-callout={tone}
      className="callout flex gap-2 rounded-md border p-3"
    >
      <Icon aria-hidden className="mt-1 size-4 shrink-0 text-muted-foreground" />
      <NodeViewContent className="min-w-0 flex-1" />
      {editor.isEditable && (
        <div contentEditable={false} className="flex shrink-0 items-start gap-1">
          <select
            aria-label="Callout tone"
            className={SELECT}
            value={tone}
            onChange={(event) => {
              updateAttributes({ tone: event.target.value })
            }}
          >
            {CALLOUT_TONES.map((value) => (
              <option key={value} value={value}>
                {TONE_LABEL[value]}
              </option>
            ))}
          </select>
          <button
            type="button"
            aria-label="Remove callout"
            title="Remove callout (keep its text)"
            className="rounded p-1 text-muted-foreground hover:bg-accent"
            onClick={() => {
              unwrap(editor, getPos)
            }}
          >
            <XIcon className="size-3.5" />
          </button>
        </div>
      )}
    </NodeViewWrapper>
  )
}

/** `callout` (frontend.md §6): notes, warnings and quotes around blocks. */
export const Callout = Node.create({
  name: 'callout',
  group: 'block',
  content: 'block+',
  defining: true,
  addAttributes: () => ({
    tone: {
      default: 'note',
      parseHTML: (element) => element.getAttribute('data-callout') ?? 'note',
      renderHTML: (attributes: { tone?: string }) => ({ 'data-callout': attributes.tone }),
    },
  }),
  parseHTML: () => [{ tag: 'aside[data-callout]' }],
  renderHTML: ({ HTMLAttributes }) => ['aside', { ...HTMLAttributes, class: 'callout' }, 0],
  addNodeView: () => ReactNodeViewRenderer(CalloutView),
  addCommands() {
    return {
      setCallout:
        (tone = 'note') =>
        ({ commands }) =>
          commands.wrapIn(this.name, { tone }),
    }
  },
})

function VisibilityBlockView({ node, editor, getPos, updateAttributes }: ReactNodeViewProps) {
  const level = (node.attrs.level as BlockLevel | undefined) ?? 'spoiler'
  const label = (node.attrs.label as string | null) ?? ''
  const Icon = level === 'private' ? LockIcon : EyeOffIcon
  return (
    <NodeViewWrapper
      as="section"
      data-visibility={level}
      className={cn(
        'visibility-block rounded-md border-2 border-dashed p-3',
        level === 'private' ? 'border-destructive/50' : 'border-amber-500/60',
      )}
    >
      <div contentEditable={false} className="mb-2 flex flex-wrap items-center gap-2 text-xs">
        <Icon aria-hidden className="size-3.5" />
        <span className="font-medium">{level === 'private' ? 'Private' : 'Spoiler'}</span>
        {editor.isEditable ? (
          <>
            <select
              aria-label="Who sees this block"
              className={SELECT}
              value={level}
              onChange={(event) => {
                updateAttributes({ level: event.target.value })
              }}
            >
              <option value="spoiler">Spoiler: readers unfold it</option>
              <option value="private">Private: authors only</option>
            </select>
            <input
              aria-label="Block label"
              placeholder="Label (optional)"
              maxLength={200}
              className="h-7 min-w-0 flex-1 rounded border border-input bg-background px-2"
              value={label}
              onChange={(event) => {
                updateAttributes({ label: event.target.value === '' ? null : event.target.value })
              }}
            />
            <button
              type="button"
              aria-label="Remove visibility block"
              title="Remove the frame (keep its text)"
              className="rounded p-1 text-muted-foreground hover:bg-accent"
              onClick={() => {
                unwrap(editor, getPos)
              }}
            >
              <XIcon className="size-3.5" />
            </button>
          </>
        ) : (
          label && <span className="text-muted-foreground">{label}</span>
        )}
      </div>
      <NodeViewContent />
    </NodeViewWrapper>
  )
}

/**
 * `visibilityBlock` (D12, frontend.md §6): blocks only authors see (private) or readers unfold
 * (spoiler). Authors see a labeled frame; the server removes private blocks for readers.
 */
export const VisibilityBlock = Node.create({
  name: 'visibilityBlock',
  group: 'block',
  content: 'block+',
  defining: true,
  addAttributes: () => ({
    level: {
      default: 'spoiler',
      parseHTML: (element) => element.getAttribute('data-visibility') ?? 'spoiler',
      renderHTML: (attributes: { level?: string }) => ({ 'data-visibility': attributes.level }),
    },
    label: {
      default: null,
      parseHTML: (element) => element.getAttribute('data-label'),
      renderHTML: (attributes: { label?: string | null }) =>
        attributes.label ? { 'data-label': attributes.label } : {},
    },
  }),
  parseHTML: () => [{ tag: 'section[data-visibility]' }],
  renderHTML: ({ HTMLAttributes }) => [
    'section',
    { ...HTMLAttributes, class: 'visibility-block' },
    0,
  ],
  addNodeView: () => ReactNodeViewRenderer(VisibilityBlockView),
  addCommands() {
    return {
      setVisibilityBlock:
        (level, label) =>
        ({ commands }) =>
          commands.wrapIn(this.name, { level, label: label ?? null }),
    }
  },
})
