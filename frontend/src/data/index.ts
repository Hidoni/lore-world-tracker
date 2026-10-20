// Data layer: DataSource & Mutations, query keys, mappers and hooks (frontend.md §5).
import './query-meta'

/** API schema types, for code outside the data layer (which can't import `api/`). */
export type { components } from '@/api'

export { DataProvider, useDataSource, useMutations } from './context'
export { ReaderModeProvider, useReaderMode, type ReaderMode } from './reader'
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
  useEntityState,
  useFacts,
  useCausedFacts,
  useCreateFact,
  useUpdateFact,
  useDeleteFact,
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
export {
  createStaticDataSource,
  createStaticFetch,
  staticConfig,
  type StaticConfig,
} from './static'
export { loadStaticFiles } from './static-modules'
export { affectedKeys, invalidateAffected } from './invalidate'
export { keys } from './keys'
export {
  useBacklinks,
  useUnlinkedMentions,
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
  EntityLink,
  EntityState,
  Fact,
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
  markdownExportUrl,
  useBackups,
  useCreateBackup,
  useCreateLinkType,
  useDeleteLinkType,
  useExportStaticSite,
  usePublish,
  usePublishStatus,
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
  useEntitiesById,
  useDimensions,
  useEventTreeLevel,
  useTimeResolution,
  useTimelines,
  useWindowTiles,
} from './time'
export {
  useCharacterFamilyTree,
  useCharacterLife,
  useCharacterRelationships,
  type FamilyTreeQuery,
  type Genealogy,
  type LifeEvent,
  type RelationshipGroup,
} from './characters'
export {
  useGroupLeaders,
  useGroupMembers,
  useGroupOrgChart,
  useGroupTerritory,
  type Leadership,
  type Membership,
  type OrgChart,
} from './groups'
export {
  lexiconExportUrl,
  useCreateLexiconEntry,
  useDeleteLexiconEntry,
  useImportLexicon,
  useLanguageFamilyTree,
  useLexicon,
  useLexiconEntry,
  useUpdateLexiconEntry,
  type EtymologySource,
  type FamilyTree,
  type LexiconDefinition,
  type LexiconEntryUpdate,
  type WireTimePoint,
  type LexiconEntry,
  type LexiconImportReport,
  type LexiconQuery,
} from './languages'
export { useGraph, type GraphData, type GraphQuery } from './graph'
export {
  useBranchDiff,
  useBranchDiffs,
  useCreateBranch,
  useRevertOverride,
  useSaveOverride,
  useSaveTimelineNote,
  useTimelineNote,
  type BranchCreate,
  type BranchDiff,
  type DiffRecord,
  type OverrideInput,
  type OverrideRecordType,
  type TimelineNote,
  type TimelineNode,
} from './branches'
export {
  useCorrespondences,
  useCreateCorrespondence,
  useDeleteCorrespondence,
  useUpdateCorrespondence,
  type CorrespondenceCreate,
  type CorrespondenceOut,
  type CorrespondenceUpdate,
  type MapOut,
  type SyncPointOut,
} from './correspondences'
export {
  usePersonalTimeline,
  usePresence,
  useReplaceSegments,
  useTimeTravel,
  useWorldline,
  type PersonalItem,
  type PersonalTimeline,
  type SegmentIn,
  type TimeTravelIn,
  type Worldline,
  type WorldlineSegment,
} from './worldlines'
export { useSpeciesDescentTree, useSpeciesMembers, type DescentTree } from './species'
export {
  useCreateMap,
  useCreatePin,
  useCreateRegion,
  useDeleteMap,
  useDeletePin,
  useDeleteRegion,
  useEntityPins,
  useMapDetail,
  useMaps,
  useUpdateMap,
  useUpdatePin,
  useUpdateRegion,
  type EntityPins,
  type MapDetail,
  type MapPin,
  type MapQuery,
  type MapRecord,
  type MapRegion,
} from './maps'
export {
  useCreateCustomField,
  useCreateCustomKind,
  useCustomFields,
  useCustomKinds,
  useDeleteCustomField,
  useDeleteCustomKind,
  useReorderCustomFields,
  useUpdateCustomField,
  useUpdateCustomKind,
  type CustomField,
  type CustomKind,
} from './custom-fields'
export {
  IMAGE_TYPES,
  isImage,
  isRaster,
  mediaFileUrl,
  RASTER_TYPES,
  SVG_TYPE,
  useAddToGallery,
  useGallery,
  useMediaItem,
  useMediaItems,
  useRemoveFromGallery,
  useReplaceMediaFile,
  useRestoreMedia,
  useTrashMedia,
  useUpdateGalleryItem,
  useUpdateMedia,
  useUploadMedia,
  type GalleryItem,
  type MediaItem,
  type MediaQuery,
  type MediaSize,
  type UploadInput,
} from './media'
export {
  useLocationEvents,
  useLocationResidents,
  useLocationTree,
  type LocationEvent,
  type LocationNode,
} from './locations'
export {
  useCreateVault,
  useDeleteVault,
  useMigrateVault,
  useRenameVault,
  useVault,
  useVaults,
} from './vaults'
