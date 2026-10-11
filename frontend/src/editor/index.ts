// TipTap editor setup, custom nodes/marks and renderers (frontend.md §6).
import { lazy } from 'react'

export { EntityLinkView } from './entity-link-view'
export { RichTextView } from './rich-text-view'
export {
  EMPTY_DOC,
  RICH_TEXT_SCHEMA_VERSION,
  isDoc,
  isSafeHref,
  linkedEntityIds,
  type RichTextDoc,
} from './schema'
export type { RichTextEditorProps, SaveOutcome } from './rich-text-editor'

/** The editor, loaded on first use (TipTap is a large chunk). */
export const LazyRichTextEditor = lazy(() => import('./rich-text-editor'))
