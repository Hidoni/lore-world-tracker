import type { components, operations } from '@/api'

import type { Domain } from './domain'

type Schemas = components['schemas']
/** An operation's query parameters (`as_reader` included: the "preview as reader" mode). */
export type Query<Op extends keyof operations> = NonNullable<operations[Op]['parameters']['query']>
type D<Name extends keyof Schemas> = Domain<Schemas[Name]>

export type Meta = Schemas['MetaResponse']
export type Vault = Schemas['Vault']
export type VaultList = Schemas['VaultList']
export type Entity = D<'EntityOut'>
export type EntityPage = D<'EntityPage'>
export type EntityWriteResult = D<'EntityWriteResult'>
/** A link seen from one entity (resolved validity moments as `bigint`). */
export type EntityLink = D<'EntityLink'>
export type EntityState = D<'EntityStateOut'>
export type Fact = D<'FactOut'>
export type Affected = Schemas['Affected']

/**
 * Every read the UI makes (frontend.md §5.1, ADR-0012). Implementable from a static snapshot
 * (post-MVP `StaticDataSource`, visibility-and-sharing.md §6), so it holds reads only; resolved
 * moments come back as `bigint`. Later issues add methods as endpoints land.
 */
export interface DataSource {
  meta(): Promise<Meta>
  vaults(): Promise<VaultList>
  vault(vault: string): Promise<Vault>
  settings(vault: string): Promise<Schemas['VaultSettings']>
  registry(vault: string): Promise<Schemas['Registry']>
  backups(vault: string): Promise<Schemas['BackupList']>
  /** Whether the vault can be published and when it last was (author-only). */
  publishStatus(vault: string): Promise<Schemas['PublishStatus']>
  entities(vault: string, query?: Query<'entities_list'>): Promise<EntityPage>
  entity(vault: string, id: string, query?: Query<'entities_get'>): Promise<Entity>
  /** As-of state (time-model.md §10.5): existence, name and temporal fields at a moment. */
  entityState(vault: string, id: string, query: Query<'entities_state'>): Promise<EntityState>
  /** An entity's facts (temporal field values, existence, names over time). */
  facts(vault: string, id: string, query?: Query<'facts_list_facts'>): Promise<D<'FactList'>>
  /** An event's "changes caused": the facts whose source it is. */
  causedFacts(vault: string, event: string): Promise<D<'FactList'>>
  children(vault: string, id: string, query?: Query<'entities_children'>): Promise<D<'TreePage'>>
  tree(vault: string, query?: Query<'tree_get'>): Promise<D<'TreePage'>>
  trash(vault: string, query?: Query<'trash_list'>): Promise<D<'TrashPage'>>
  fieldValues(vault: string, query: Query<'entities_field_values'>): Promise<D<'FieldValueList'>>
  tags(vault: string, query?: Query<'tags_list'>): Promise<D<'TagList'>>
  links(vault: string, id: string, query?: Query<'entities_links'>): Promise<D<'EntityLinks'>>
  backlinks(vault: string, id: string, query?: Query<'entities_backlinks'>): Promise<D<'Backlinks'>>
  unlinkedMentions(
    vault: string,
    id: string,
    query?: Query<'entities_unlinked_mentions'>,
  ): Promise<D<'UnlinkedMentions'>>
  linkTypes(vault: string): Promise<D<'LinkTypeList'>>
  changes(vault: string, query?: Query<'changes_list'>): Promise<D<'ChangesetPage'>>
  change(vault: string, id: string, query?: Query<'changes_get'>): Promise<D<'ChangesetDetail'>>
  history(vault: string, id: string, query?: Query<'entities_history'>): Promise<D<'ChangesetPage'>>
  search(vault: string, query: Query<'search_search'>): Promise<D<'SearchPage'>>
  quickSearch(vault: string, query: Query<'search_quick'>): Promise<D<'QuickResults'>>
  findings(vault: string, query?: Query<'consistency_findings'>): Promise<D<'FindingPage'>>
  consistencyRules(vault: string, query?: Query<'consistency_rules'>): Promise<D<'RuleList'>>
  timelines(
    vault: string,
    dimension: string,
    query?: Query<'dimensions_timelines'>,
  ): Promise<D<'TimelineTree'>>
  calendarPresets(vault: string): Promise<D<'PresetList'>>
  eventTree(
    vault: string,
    timeline: string,
    query?: Query<'timelines_event_tree'>,
  ): Promise<D<'EventTreePage'>>
  causality(
    vault: string,
    timeline: string,
    query: Query<'timelines_causality'>,
  ): Promise<D<'CausalityGraphOut'>>
  timelineWindow(
    vault: string,
    timeline: string,
    query: Query<'timelines_window'>,
  ): Promise<D<'TimelineWindow'>>
  occurrences(
    vault: string,
    event: string,
    query: Query<'events_occurrences'>,
  ): Promise<D<'OccurrencePage'>>
  // The locations module (docs/modules/locations.md).
  locationTree(vault: string, query?: Query<'locations_tree'>): Promise<D<'LocationTree'>>
  locationEvents(
    vault: string,
    location: string,
    query: Query<'locations_events'>,
  ): Promise<D<'LocationEvents'>>
  locationResidents(
    vault: string,
    location: string,
    query?: Query<'locations_residents'>,
  ): Promise<D<'EntityLinks'>>
  // The media module (docs/modules/media.md).
  /** The media library, newest first. */
  mediaItems(vault: string, query?: Query<'media_list'>): Promise<D<'MediaItemList'>>
  mediaItem(vault: string, media: string): Promise<D<'MediaItemOut'>>
  gallery(vault: string, entity: string): Promise<D<'GalleryOut'>>
  // The maps module (docs/modules/maps.md).
  maps(vault: string, query?: Query<'maps_list'>): Promise<D<'MapList'>>
  mapDetail(vault: string, map: string, query?: Query<'maps_get'>): Promise<D<'MapDetail'>>
  entityPins(vault: string, entity: string): Promise<D<'EntityPins'>>
  // The custom_fields module (docs/modules/custom_fields.md).
  customFields(vault: string, query?: Query<'custom_fields_list'>): Promise<D<'CustomFieldList'>>
  customKinds(vault: string): Promise<D<'CustomKindList'>>
  // The characters module (docs/modules/characters.md).
  characterRelationships(
    vault: string,
    character: string,
    query?: Query<'characters_relationships'>,
  ): Promise<D<'Relationships'>>
  characterFamilyTree(
    vault: string,
    character: string,
    query?: Query<'characters_family_tree'>,
  ): Promise<D<'Genealogy'>>
  characterLife(
    vault: string,
    character: string,
    query: Query<'characters_life'>,
  ): Promise<D<'Life'>>
  // The groups module (docs/modules/groups.md).
  groupMembers(vault: string, group: string, query?: Query<'groups_members'>): Promise<D<'Members'>>
  groupLeaders(vault: string, group: string, query?: Query<'groups_leaders'>): Promise<D<'Leaders'>>
  groupOrgChart(
    vault: string,
    group: string,
    query?: Query<'groups_org_chart'>,
  ): Promise<D<'OrgChart'>>
  groupTerritory(
    vault: string,
    group: string,
    query?: Query<'groups_territory'>,
  ): Promise<D<'EntityLinks'>>
  // The languages module (docs/modules/languages.md).
  languageFamilyTree(
    vault: string,
    query?: Query<'languages_family_tree'>,
  ): Promise<D<'FamilyTree'>>
  lexicon(
    vault: string,
    language: string,
    query?: Query<'languages_lexicon_list'>,
  ): Promise<D<'LexiconPage'>>
  lexiconEntry(vault: string, entry: string): Promise<D<'LexiconEntryOut'>>
  // The graph module (docs/modules/graph.md).
  graph(vault: string, query?: Query<'graph_graph'>): Promise<D<'Graph'>>
  // The species module (docs/modules/species.md).
  speciesMembers(
    vault: string,
    species: string,
    query?: Query<'species_members'>,
  ): Promise<D<'EntityLinks'>>
  speciesDescentTree(
    vault: string,
    query?: Query<'species_descent_tree'>,
  ): Promise<D<'DescentTree'>>
  // The branches module (docs/modules/branches.md).
  /** What a branch created, overrode and inherits across its branch point. */
  branchDiff(
    vault: string,
    timeline: string,
    query?: Query<'branches_timeline_diff'>,
  ): Promise<D<'BranchDiff'>>
  /** A branch's note on an entity (body `null` and revision 0 when there is none). */
  timelineNote(vault: string, entity: string, timeline: string): Promise<D<'NoteOut'>>
  // The correspondences module (docs/modules/correspondences.md).
  /** The live correspondences (of a dimension, either side), with their resolved sync points. */
  correspondences(
    vault: string,
    query?: Query<'correspondences_list'>,
  ): Promise<D<'CorrespondenceList'>>
  correspondence(vault: string, id: string): Promise<D<'CorrespondenceOut'>>
  /** A moment mapped to another dimension along the shortest path of correspondences. */
  mapMoment(vault: string, query: Query<'correspondences_map'>): Promise<D<'MapOut'>>
  // The worldlines module (docs/modules/worldlines.md).
  /** An entity's worldline: explicit segments, or the implicit one (its existence). */
  worldline(
    vault: string,
    entity: string,
    query?: Query<'worldlines_segments'>,
  ): Promise<D<'Worldline'>>
  /** The segments covering a moment (a traveler can be present twice). */
  presence(
    vault: string,
    entity: string,
    query: Query<'worldlines_presence'>,
  ): Promise<D<'Presence'>>
  /** What the entity lives through, in its own order, with subjective time and ages. */
  personalTimeline(
    vault: string,
    entity: string,
    query?: Query<'worldlines_personal_timeline'>,
  ): Promise<D<'PersonalTimeline'>>
}

/**
 * Author-only requests (frontend.md §13): writes, and the `POST` helpers a read-only server
 * refuses (time resolution, calendar previews). Absent in reader and static contexts, so editing
 * UI checks `useMutations()` for `null`. Request bodies take time specs as JSON and moments as
 * `bigint` or strings (`toWire`).
 */
export interface Mutations {
  createVault(name: string): Promise<Vault>
  renameVault(vault: string, name: string): Promise<Vault>
  deleteVault(vault: string): Promise<void>
  migrateVault(vault: string): Promise<Schemas['MigrationResponse']>
  /** Restores a backup zip into a new vault; `onProgress` gets the upload's fraction (0..1). */
  restoreBackup(file: Blob, onProgress?: (fraction: number) => void): Promise<Vault>
  createBackup(vault: string, body: Schemas['BackupCreate']): Promise<Schemas['Backup']>
  /** Publishes a sanitized snapshot into the server's publish directory. */
  publishVault(vault: string): Promise<Schemas['PublishStatus']>
  /** Exports the latest snapshot as a static site (visibility-and-sharing.md §8). */
  exportStaticSite(vault: string): Promise<Schemas['PublishStatus']>
  updateSettings(
    vault: string,
    body: Schemas['VaultSettingsUpdate'],
  ): Promise<Schemas['VaultSettings']>
  setModule(
    vault: string,
    module: string,
    body: Schemas['ModuleUpdate'],
  ): Promise<Schemas['ModuleUpdateResponse']>
  createEntity(vault: string, body: Schemas['EntityCreate']): Promise<EntityWriteResult>
  updateEntity(vault: string, id: string, body: Schemas['EntityUpdate']): Promise<EntityWriteResult>
  deleteEntity(
    vault: string,
    id: string,
    options?: { purge?: boolean; suppress?: Schemas['SuppressIn'] },
  ): Promise<D<'EntityDeleteResult'>>
  restoreEntity(
    vault: string,
    id: string,
    suppress?: Schemas['SuppressIn'],
  ): Promise<EntityWriteResult>
  createFact(
    vault: string,
    entity: string,
    body: Schemas['FactCreate'],
  ): Promise<D<'FactWriteResult'>>
  updateFact(vault: string, id: string, body: Schemas['FactUpdate']): Promise<D<'FactWriteResult'>>
  deleteFact(vault: string, id: string): Promise<D<'FactWriteResult'>>
  createLink(vault: string, body: Schemas['LinkCreate']): Promise<D<'LinkWriteResult'>>
  updateLink(vault: string, id: string, body: Schemas['LinkUpdate']): Promise<D<'LinkWriteResult'>>
  deleteLink(
    vault: string,
    id: string,
    suppress?: Schemas['SuppressIn'],
  ): Promise<D<'LinkDeleteResult'>>
  createLinkType(vault: string, body: Schemas['LinkTypeCreate']): Promise<D<'LinkTypeOut'>>
  updateLinkType(
    vault: string,
    key: string,
    body: Schemas['LinkTypeUpdate'],
  ): Promise<D<'LinkTypeOut'>>
  deleteLinkType(vault: string, key: string): Promise<D<'LinkTypeDeleted'>>
  revertChange(
    vault: string,
    id: string,
    suppress?: Schemas['SuppressIn'],
  ): Promise<D<'RevertResult'>>
  scanConsistency(vault: string): Promise<D<'ScanResult'>>
  updateConsistencyRule(
    vault: string,
    rule: string,
    body: Schemas['RuleUpdate'],
  ): Promise<D<'RuleInfo'>>
  suppressFinding(vault: string, body: Schemas['SuppressionIn']): Promise<D<'FindingOut'>>
  unsuppressFinding(vault: string, fingerprint: string): Promise<void>
  createDimension(vault: string, body: Schemas['DimensionWizardIn']): Promise<D<'DimensionCreated'>>
  previewCalendar(vault: string, body: Schemas['CalendarPreviewIn']): Promise<D<'Preview'>>
  proposeCalendarChange(
    vault: string,
    calendar: string,
    body: Schemas['CalendarProposalIn'],
  ): Promise<D<'CalendarProposalOut'>>
  applyCalendarProposal(
    vault: string,
    calendar: string,
    proposal: string,
    body: Schemas['CalendarApplyIn'],
  ): Promise<D<'CalendarApplyOut'>>
  resolveTime(vault: string, body: Schemas['ResolveIn']): Promise<D<'ResolveOut'>>
  convertTime(vault: string, body: Domain<Schemas['ConvertIn']>): Promise<D<'ConvertOut'>>
  materializeOccurrence(vault: string, event: string, key: string): Promise<EntityWriteResult>
  deleteOccurrence(
    vault: string,
    event: string,
    key: string,
    options?: { trashSubEvents?: boolean },
  ): Promise<D<'EntityDeleteResult'>>
  proposeRecurrenceChange(
    vault: string,
    event: string,
    body: Schemas['RecurrenceProposalIn'],
  ): Promise<D<'RecurrenceProposalOut'>>
  applyRecurrenceProposal(
    vault: string,
    event: string,
    proposal: string,
    body: Schemas['RecurrenceApplyIn'],
  ): Promise<D<'RecurrenceApplyOut'>>
  // The media module: uploads take `onProgress` (the upload's fraction, 0..1).
  uploadMedia(
    vault: string,
    file: Blob,
    form?: { alt?: string; caption?: string; filename?: string },
    onProgress?: (fraction: number) => void,
  ): Promise<D<'MediaUploadResult'>>
  updateMedia(
    vault: string,
    media: string,
    body: Schemas['MediaItemUpdate'],
  ): Promise<D<'MediaItemOut'>>
  trashMedia(vault: string, media: string): Promise<D<'MediaItemOut'>>
  restoreMedia(vault: string, media: string): Promise<D<'MediaItemOut'>>
  replaceMediaFile(
    vault: string,
    media: string,
    file: Blob,
    revision: number,
    onProgress?: (fraction: number) => void,
  ): Promise<D<'MediaItemOut'>>
  addToGallery(
    vault: string,
    entity: string,
    body: Schemas['GalleryItemCreate'],
  ): Promise<D<'GalleryItemOut'>>
  updateGalleryItem(
    vault: string,
    item: string,
    body: Schemas['GalleryItemUpdate'],
  ): Promise<D<'GalleryItemOut'>>
  removeFromGallery(vault: string, item: string): Promise<void>
  // The maps module.
  createMap(vault: string, body: Schemas['MapCreate']): Promise<D<'MapWriteResult'>>
  updateMap(vault: string, map: string, body: Schemas['MapUpdate']): Promise<D<'MapWriteResult'>>
  deleteMap(vault: string, map: string): Promise<D<'MapWriteResult'>>
  createPin(vault: string, map: string, body: Schemas['PinCreate']): Promise<D<'PinWriteResult'>>
  updatePin(vault: string, pin: string, body: Schemas['PinUpdate']): Promise<D<'PinWriteResult'>>
  deletePin(vault: string, pin: string): Promise<D<'PinWriteResult'>>
  createRegion(
    vault: string,
    map: string,
    body: Schemas['RegionCreate'],
  ): Promise<D<'RegionWriteResult'>>
  updateRegion(
    vault: string,
    region: string,
    body: Schemas['RegionUpdate'],
  ): Promise<D<'RegionWriteResult'>>
  deleteRegion(vault: string, region: string): Promise<D<'RegionWriteResult'>>
  // The custom_fields module.
  createCustomField(
    vault: string,
    body: Schemas['CustomFieldCreate'],
  ): Promise<D<'CustomFieldWriteResult'>>
  updateCustomField(
    vault: string,
    field: string,
    body: Schemas['CustomFieldUpdate'],
  ): Promise<D<'CustomFieldWriteResult'>>
  deleteCustomField(
    vault: string,
    field: string,
    deleteValues: boolean,
  ): Promise<D<'CustomFieldDeleteResult'>>
  reorderCustomFields(vault: string, body: Schemas['FieldReorder']): Promise<D<'CustomFieldList'>>
  createCustomKind(
    vault: string,
    body: Schemas['CustomKindCreate'],
  ): Promise<D<'CustomKindWriteResult'>>
  updateCustomKind(
    vault: string,
    kind: string,
    body: Schemas['CustomKindUpdate'],
  ): Promise<D<'CustomKindWriteResult'>>
  deleteCustomKind(vault: string, kind: string): Promise<D<'CustomKindDeleteResult'>>
  convertKind(vault: string, body: Schemas['ConvertKind']): Promise<D<'ConvertKindResult'>>
  // The languages module's lexicon.
  createLexiconEntry(
    vault: string,
    language: string,
    body: Schemas['LexiconEntryCreate'],
  ): Promise<D<'LexiconWriteResult'>>
  updateLexiconEntry(
    vault: string,
    entry: string,
    body: Schemas['LexiconEntryUpdate'],
  ): Promise<D<'LexiconWriteResult'>>
  deleteLexiconEntry(vault: string, entry: string): Promise<D<'LexiconWriteResult'>>
  importLexicon(
    vault: string,
    language: string,
    body: Schemas['ImportIn'],
    dryRun: boolean,
  ): Promise<Schemas['ImportReport']>
  // The branches module.
  createBranch(vault: string, body: Schemas['BranchCreate']): Promise<EntityWriteResult>
  saveOverride(vault: string, body: Schemas['OverrideCreate']): Promise<D<'OverrideOut'>>
  revertOverride(
    vault: string,
    recordType: 'event' | 'fact' | 'link',
    override: string,
  ): Promise<D<'OverrideOut'>>
  putTimelineNote(
    vault: string,
    entity: string,
    timeline: string,
    body: Schemas['NoteIn'],
  ): Promise<D<'NoteOut'>>
  // The correspondences module.
  createCorrespondence(
    vault: string,
    body: Schemas['CorrespondenceCreate'],
  ): Promise<D<'CorrespondenceWriteResult'>>
  updateCorrespondence(
    vault: string,
    id: string,
    body: Schemas['CorrespondenceUpdate'],
  ): Promise<D<'CorrespondenceWriteResult'>>
  deleteCorrespondence(vault: string, id: string): Promise<D<'CorrespondenceWriteResult'>>
  // The worldlines module.
  replaceSegments(
    vault: string,
    entity: string,
    body: Schemas['SegmentsPut'],
  ): Promise<D<'WorldlineWriteResult'>>
  timeTravel(
    vault: string,
    entity: string,
    body: Schemas['TimeTravelIn'],
  ): Promise<D<'TimeTravelResult'>>
}
