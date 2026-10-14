// Links UI: relations panel, add/edit link dialog, backlinks (frontend.md §7, §3).
export { BacklinksPanel } from './backlinks-panel'
export { LinkDialog, type LinkDialogMode, type LinkTarget } from './link-dialog'
export { linkOptions, type LinkOption } from './link-options'
export { RelationsPanel, groupLinks } from './relations-panel'
export {
  carriesEntity,
  droppedEntity,
  ENTITY_MIME,
  setEntityDrag,
  type DraggedEntity,
} from './entity-drag'
