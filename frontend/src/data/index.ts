// Data layer: DataSource & Mutations, query keys, mappers and hooks (frontend.md §5).
import './query-meta'

/** API schema types, for code outside the data layer (which can't import `api/`). */
export type { components } from '@/api'

export { DataProvider, useDataSource, useMutations } from './context'
export {
  bigintReplacer,
  bigintReviver,
  entityToDomain,
  EXT_MOMENTS,
  momentString,
  parseDomain,
  stringifyDomain,
  toDomain,
  toDomainAs,
  toWire,
  type Domain,
} from './domain'
export {
  useChildren,
  useCreateEntity,
  useDeleteEntity,
  useEntities,
  useEntity,
  useEntityList,
  useFieldValues,
  useRegistry,
  useRestoreEntity,
  useTags,
  useTrash,
  useTrashList,
  useTree,
  useTreeLevel,
  useUpdateEntity,
  useUpdateLatest,
} from './entities'
export { ApiError, fieldErrors, isRevisionConflict } from './errors'
export {
  useConsistencyRules,
  useFindingPages,
  useFindings,
  useScanConsistency,
  useSuppressFinding,
  useUnsuppressFinding,
  useUpdateConsistencyRule,
} from './consistency'
export {
  blockingFindings,
  isConsistencyError,
  withSaveAnyway,
  type BlockingFinding,
  type SaveAnywayPrompt,
} from './save-anyway'
export {
  useChanges,
  useChangeset,
  useChangesPages,
  useHistory,
  useHistoryPages,
  useRevertChange,
} from './history'
export { createHttpDataSource, createHttpMutations } from './http'
export { affectedKeys, invalidateAffected } from './invalidate'
export { keys } from './keys'
export {
  useBacklinks,
  useCreateLink,
  useDeleteLink,
  useLinks,
  useLinkTypes,
  useUpdateLink,
} from './links'
export { useMeta } from './meta'
export { useQuickSearch, useSearch, useSearchPages } from './search'
export type {
  CalendarProposal,
  CausalityGraph,
  EventTreeNode,
  RecurrenceProposal,
  TimelineWindow,
  WindowFilters,
  WindowTile,
} from './time'
export type {
  Affected,
  DataSource,
  Entity,
  EntityPage,
  EntityWriteResult,
  Meta,
  Mutations,
  Query,
  Vault,
  VaultList,
} from './source'
export {
  backupDownloadUrl,
  useBackups,
  useCreateBackup,
  useCreateLinkType,
  useDeleteLinkType,
  useRestoreBackup,
  useSetModule,
  useSettings,
  useUpdateLinkType,
  useUpdateSettings,
} from './settings'
export {
  useApplyCalendarProposal,
  useApplyRecurrenceProposal,
  useCausality,
  useDeleteOccurrence,
  useMaterializeOccurrence,
  useOccurrences,
  useProposeRecurrenceChange,
  useCalendarPresets,
  useCalendarPreview,
  useProposeCalendarChange,
  useCreateDimension,
  useDimensionCalendars,
  useDimensions,
  useEventTreeLevel,
  useTimeResolution,
  useTimelines,
  useWindowTiles,
} from './time'
export { useCreateVault, useDeleteVault, useRenameVault, useVault, useVaults } from './vaults'
