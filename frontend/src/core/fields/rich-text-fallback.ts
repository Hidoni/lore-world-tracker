/** Rich-text documents (TipTap JSON) as plain text, until fields use the editor (#259). */
interface RichNode {
  type?: string
  text?: string
  content?: RichNode[]
}

export function docToText(value: unknown): string {
  if (value === null || typeof value !== 'object') return ''
  const doc = value as RichNode
  const blocks = doc.content ?? []
  return blocks.map((block) => inlineText(block)).join('\n')
}

function inlineText(node: RichNode): string {
  if (typeof node.text === 'string') return node.text
  return (node.content ?? []).map(inlineText).join('')
}

export function textToDoc(text: string): Record<string, unknown> {
  return {
    type: 'doc',
    content: text
      .split('\n')
      .map((line) =>
        line === ''
          ? { type: 'paragraph' }
          : { type: 'paragraph', content: [{ type: 'text', text: line }] },
      ),
  }
}
