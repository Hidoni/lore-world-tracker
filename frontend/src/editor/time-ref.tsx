import type { SlotRef, TimePoint } from '@lore/chronology'
import { Node, type Editor } from '@tiptap/core'
import { NodeViewWrapper, ReactNodeViewRenderer, type ReactNodeViewProps } from '@tiptap/react'
import { useParams } from '@tanstack/react-router'

import { TimeRefView } from '@/core/time'

import type { SlashItem } from './slash-items'

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    timeRef: { insertTimeRef: (timePoint: TimePoint) => ReturnType }
  }
}

/** Asks the editor's host for a date to insert (it opens a dialog, then `insertTimeRef`). */
export type DateRequest = (editor: Editor) => void

function json(value: string | null): unknown {
  if (value === null) return null
  try {
    return JSON.parse(value) as unknown
  } catch {
    return null
  }
}

function TimeRefNodeView({ node }: ReactNodeViewProps) {
  const params = useParams({ strict: false })
  const timePoint = (node.attrs.timePoint as TimePoint | null) ?? null
  const ref = (node.attrs.ref as SlotRef | null) ?? null
  return (
    <NodeViewWrapper as="span" className="inline">
      {params.vault === undefined ? (
        <span className="time-ref">date</span>
      ) : (
        <TimeRefView vault={params.vault} timePoint={timePoint} slotRef={ref} />
      )}
    </NodeViewWrapper>
  )
}

/**
 * `timeRef` (frontend.md §6): an inline date, rendered in the reader's display calendar. Inserted
 * from the slash menu ("Date") or `@date`, through the host's date dialog (`request`).
 */
export const TimeRef = Node.create<{ request: DateRequest | null; slashItems: SlashItem[] }>({
  name: 'timeRef',
  group: 'inline',
  inline: true,
  atom: true,
  selectable: true,
  addOptions: () => ({ request: null, slashItems: [] }),
  addAttributes: () => ({
    timePoint: {
      default: null,
      parseHTML: (element) => json(element.getAttribute('data-time-point')),
    },
    ref: {
      default: null,
      parseHTML: (element) => json(element.getAttribute('data-slot-ref')),
    },
  }),
  parseHTML: () => [{ tag: 'span[data-time-ref]' }],
  renderHTML: ({ node }) => [
    'span',
    {
      'data-time-ref': '',
      class: 'time-ref',
      ...(node.attrs.timePoint === null
        ? {}
        : { 'data-time-point': JSON.stringify(node.attrs.timePoint) }),
      ...(node.attrs.ref === null ? {} : { 'data-slot-ref': JSON.stringify(node.attrs.ref) }),
    },
    'date',
  ],
  renderText: () => 'date',
  addNodeView: () => ReactNodeViewRenderer(TimeRefNodeView, { as: 'span' }),
  addCommands() {
    return {
      insertTimeRef:
        (timePoint) =>
        ({ commands }) =>
          commands.insertContent([
            { type: this.name, attrs: { timePoint, ref: null } },
            { type: 'text', text: ' ' },
          ]),
    }
  },
})

/** The slash menu's "Date" entry, when the host can ask for a date. */
export function dateSlashItem(request: DateRequest): SlashItem {
  return {
    id: 'timeRef',
    title: 'Date',
    description: 'A date shown in each reader’s calendar',
    keywords: ['time', 'when', 'calendar', 'day', 'year'],
    run: (editor) => {
      request(editor)
    },
  }
}
