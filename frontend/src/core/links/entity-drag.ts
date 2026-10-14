/**
 * Dragging an entity onto something to link it (visual linking, docs/modules/graph.md;
 * frontend.md §9.4): sources set `ENTITY_MIME` with the entity's id, name and kind; any link to an
 * entity page (sidebar, search results, Recent) also works, through the URL the browser drags.
 */
export const ENTITY_MIME = 'application/x-lore-entity'

export interface DraggedEntity {
  id: string
  name?: string
  kind?: string
}

/** Marks a drag as carrying an entity (call from `onDragStart`). */
export function setEntityDrag(
  transfer: DataTransfer,
  entity: { id: string; name: string; kind: string },
): void {
  transfer.setData(ENTITY_MIME, JSON.stringify(entity))
  transfer.effectAllowed = 'copyLink'
}

/** Whether a drag may carry an entity (only the types are readable while dragging over). */
export function carriesEntity(transfer: DataTransfer): boolean {
  const types = Array.from(transfer.types)
  return types.includes(ENTITY_MIME) || types.includes('text/uri-list')
}

const ENTITY_PATH = /\/v\/([^/?#]+)\/e\/([^/?#]+)/

/** The entity a drop carries: its own data, else an entity page's URL in this vault. */
export function droppedEntity(transfer: DataTransfer, vault: string): DraggedEntity | null {
  const own = transfer.getData(ENTITY_MIME)
  if (own !== '') {
    try {
      const parsed = JSON.parse(own) as DraggedEntity
      if (typeof parsed.id === 'string') return parsed
    } catch {
      // fall back to the URL
    }
  }
  const url = (transfer.getData('text/uri-list') || transfer.getData('text/plain'))
    .split('\n')
    .find((line) => !line.startsWith('#'))
  const match = url === undefined ? null : ENTITY_PATH.exec(url)
  if (match === null || decodeURIComponent(match[1] ?? '') !== vault) return null
  return { id: decodeURIComponent(match[2] ?? '') }
}
