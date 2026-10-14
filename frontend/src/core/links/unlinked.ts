/** Where a name occurs unlinked in a document (the backend's `UnlinkedOccurrence`). */
export interface Occurrence {
  /** Child indices from the root (`content` arrays) to the text node. */
  path: readonly number[]
  /** UTF-16 offset and length in the node's text. */
  offset: number
  length: number
  /** The text expected there. */
  text: string
}

interface Node {
  type?: string
  text?: string
  marks?: { type: string; attrs?: Record<string, unknown> }[]
  content?: Node[]
  [key: string]: unknown
}

const at = (doc: Node, path: readonly number[]): Node | undefined =>
  path.reduce<Node | undefined>((node, index) => node?.content?.[index], doc)

/**
 * `doc` with an `entityLink` mark to `entityId` on each occurrence (R-LNK-3, the backlinks
 * panel's "Link"). Text nodes are split around a match and keep their other marks. Occurrences
 * whose text is no longer where they were found (the document changed since) are skipped and
 * counted. The input isn't modified.
 */
export function linkOccurrences(
  doc: unknown,
  occurrences: readonly Occurrence[],
  entityId: string,
): { doc: unknown; linked: number; skipped: number } {
  const copy = structuredClone(doc) as Node
  // Last first: splitting a node shifts the indices and offsets after it, never before.
  const ordered = [...occurrences].sort((a, b) => compare(b, a))
  let linked = 0
  for (const occurrence of ordered) {
    const parent = at(copy, occurrence.path.slice(0, -1))
    const index = occurrence.path[occurrence.path.length - 1]
    const node = index === undefined ? undefined : parent?.content?.[index]
    const value = node?.type === 'text' ? node.text : undefined
    const end = occurrence.offset + occurrence.length
    if (
      parent?.content === undefined ||
      index === undefined ||
      node === undefined ||
      value?.slice(occurrence.offset, end) !== occurrence.text ||
      node.marks?.some((mark) => mark.type === 'entityLink')
    ) {
      continue
    }
    const { marks = [], ...rest } = node
    const piece = (text: string, link: boolean): Node => {
      const all = link ? [...marks, { type: 'entityLink', attrs: { entityId } }] : marks
      return all.length > 0 ? { ...rest, text, marks: all } : { ...rest, text }
    }
    const pieces = [
      ...(occurrence.offset > 0 ? [piece(value.slice(0, occurrence.offset), false)] : []),
      piece(occurrence.text, true),
      ...(end < value.length ? [piece(value.slice(end), false)] : []),
    ]
    parent.content.splice(index, 1, ...pieces)
    linked += 1
  }
  return { doc: copy, linked, skipped: occurrences.length - linked }
}

/** Document order: by path, then offset. */
function compare(a: Occurrence, b: Occurrence): number {
  for (let i = 0; i < Math.min(a.path.length, b.path.length); i += 1) {
    const step = (a.path[i] ?? 0) - (b.path[i] ?? 0)
    if (step !== 0) return step
  }
  return a.path.length - b.path.length || a.offset - b.offset
}
