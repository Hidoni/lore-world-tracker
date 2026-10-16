// defineModule, module activation and extension-point registries (modules.md §3).
export { activeModules, collectList, collectRecord } from './activation'
export {
  ModuleDefinitionsProvider,
  useActiveModules,
  useExtensionList,
  useExtensionRecord,
  useModuleDefinitions,
} from './context'
export {
  isLazyComponent,
  lazyComponent,
  loadEditorExtensions,
  usePreloadModules,
  type LazyComponent,
} from './lazy'
export { ModuleGate } from './module-gate'
export {
  defineModule,
  type Command,
  type CommandContext,
  type DimensionSection,
  type EditorExtension,
  type EditorExtensionLoader,
  type EntityPanel,
  type EntityViewProps,
  type FieldEditorExtensionProps,
  type FieldRendererProps,
  type GraphStyles,
  type KindUiConfig,
  type LinkRowProps,
  type ModuleDefinition,
  type NavSection,
  type RichTextNodeProps,
  type RouteFactory,
  type SearchHitProps,
  type SettingsPage,
  type TimelineLayer,
  type TimelineLayerProps,
} from './types'
