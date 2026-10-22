// The workspace: tabs and panes side by side in the main area (frontend.md §3).
export { PaneRouterContext, useInPane, type PaneRouterFactory } from './context'
export { routeOf } from './links'
export {
  MAX_PANES,
  useWorkspace,
  type Pane,
  type Tab,
  type Workspace as WorkspaceState,
} from './store'
export { TabTitle } from './tab-title'
export { useOpenIn, Workspace } from './workspace'
