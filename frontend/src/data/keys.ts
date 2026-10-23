/**
 * Query keys (frontend.md §5.1): `[vault, area, id?, params?]`, defined here only, so
 * `invalidateAffected` can find every query a write touches. `meta` and the vault list live
 * outside any vault.
 */
export const keys = {
  meta: () => ['meta'] as const,
  vaults: () => ['vaults'] as const,
  vault: (vault: string) => [vault, 'vault'] as const,
  settings: (vault: string) => [vault, 'settings'] as const,
  registry: (vault: string) => [vault, 'registry'] as const,
  backups: (vault: string) => [vault, 'backups'] as const,
  mcpToken: (vault: string) => [vault, 'mcp-token'] as const,
  publish: (vault: string) => [vault, 'publish'] as const,
  entities: (vault: string, params?: object) => [vault, 'entities', params ?? {}] as const,
  entity: (vault: string, id: string, params?: object) =>
    [vault, 'entity', id, params ?? {}] as const,
  entityState: (vault: string, id: string, params: object) =>
    [vault, 'entityState', id, params] as const,
  facts: (vault: string, id: string, params?: object) =>
    [vault, 'facts', id, params ?? {}] as const,
  causedFacts: (vault: string, event: string) => [vault, 'causedFacts', event] as const,
  children: (vault: string, id: string, params?: object) =>
    [vault, 'children', id, params ?? {}] as const,
  tree: (vault: string, params?: object) => [vault, 'tree', params ?? {}] as const,
  trash: (vault: string, params?: object) => [vault, 'trash', params ?? {}] as const,
  fieldValues: (vault: string, params: object) => [vault, 'fieldValues', params] as const,
  tags: (vault: string, params: object) => [vault, 'tags', params] as const,
  links: (vault: string, id: string, params?: object) =>
    [vault, 'links', id, params ?? {}] as const,
  backlinks: (vault: string, id: string, params?: object) =>
    [vault, 'backlinks', id, params ?? {}] as const,
  unlinkedMentions: (vault: string, id: string, params?: object) =>
    [vault, 'unlinkedMentions', id, params ?? {}] as const,
  linkTypes: (vault: string) => [vault, 'linkTypes'] as const,
  changes: (vault: string, params?: object) => [vault, 'changes', params ?? {}] as const,
  change: (vault: string, id: string) => [vault, 'change', id] as const,
  history: (vault: string, id: string, params?: object) =>
    [vault, 'history', id, params ?? {}] as const,
  search: (vault: string, params: object) => [vault, 'search', params] as const,
  quickSearch: (vault: string, params: object) => [vault, 'quickSearch', params] as const,
  findings: (vault: string, params?: object) => [vault, 'findings', params ?? {}] as const,
  consistencyRules: (vault: string) => [vault, 'consistencyRules'] as const,
  timelines: (vault: string, dimension: string) => [vault, 'timelines', dimension] as const,
  branchDiff: (vault: string, timeline: string) => [vault, 'branchDiff', timeline] as const,
  worldline: (vault: string, entity: string, params?: object) =>
    [vault, 'worldline', entity, params ?? {}] as const,
  presence: (vault: string, entity: string, params: object) =>
    [vault, 'presence', entity, params] as const,
  personalTimeline: (vault: string, entity: string, params?: object) =>
    [vault, 'personalTimeline', entity, params ?? {}] as const,
  correspondences: (vault: string, dimension: string | null) =>
    [vault, 'correspondences', dimension ?? ''] as const,
  correspondence: (vault: string, id: string) => [vault, 'correspondences', 'one', id] as const,
  timelineNote: (vault: string, entity: string, timeline: string) =>
    [vault, 'timelineNote', entity, timeline] as const,
  calendarPresets: (vault: string) => [vault, 'calendarPresets'] as const,
  eventTree: (vault: string, timeline: string, params?: object) =>
    [vault, 'eventTree', timeline, params ?? {}] as const,
  causality: (vault: string, timeline: string, params: object) =>
    [vault, 'causality', timeline, params] as const,
  window: (vault: string, timeline: string, params: object) =>
    [vault, 'window', timeline, params] as const,
  occurrences: (vault: string, event: string, params: object) =>
    [vault, 'occurrences', event, params] as const,
  locationTree: (vault: string, params: object) => [vault, 'locationTree', params] as const,
  locationEvents: (vault: string, location: string, params: object) =>
    [vault, 'locationEvents', location, params] as const,
  /** Everything of the media module (one prefix: its writes return no `affected`). */
  media: (vault: string) => [vault, 'media'] as const,
  mediaItems: (vault: string, params?: object) => [vault, 'media', 'items', params ?? {}] as const,
  mediaItem: (vault: string, media: string) => [vault, 'media', 'item', media] as const,
  gallery: (vault: string, entity: string) => [vault, 'media', 'gallery', entity] as const,
  maps: (vault: string, params?: object) => [vault, 'maps', params ?? {}] as const,
  customFields: (vault: string, params?: object) => [vault, 'customFields', params ?? {}] as const,
  customKinds: (vault: string) => [vault, 'customKinds'] as const,
  mapDetail: (vault: string, map: string, params?: object) =>
    [vault, 'mapDetail', map, params ?? {}] as const,
  entityPins: (vault: string, entity: string) => [vault, 'entityPins', entity] as const,
  locationResidents: (vault: string, location: string, params?: object) =>
    [vault, 'locationResidents', location, params ?? {}] as const,
  characterRelationships: (vault: string, character: string, params?: object) =>
    [vault, 'characterRelationships', character, params ?? {}] as const,
  characterFamilyTree: (vault: string, character: string, params: object) =>
    [vault, 'characterFamilyTree', character, params] as const,
  characterLife: (vault: string, character: string, params: object) =>
    [vault, 'characterLife', character, params] as const,
  groupMembers: (vault: string, group: string, params: object) =>
    [vault, 'groupMembers', group, params] as const,
  groupLeaders: (vault: string, group: string, params?: object) =>
    [vault, 'groupLeaders', group, params ?? {}] as const,
  groupOrgChart: (vault: string, group: string, params: object) =>
    [vault, 'groupOrgChart', group, params] as const,
  groupTerritory: (vault: string, group: string, params?: object) =>
    [vault, 'groupTerritory', group, params ?? {}] as const,
  languageFamilyTree: (vault: string, params: object) =>
    [vault, 'languageFamilyTree', params] as const,
  lexicon: (vault: string, language: string, params: object) =>
    [vault, 'lexicon', language, params] as const,
  lexiconEntry: (vault: string, entry: string) => [vault, 'lexiconEntry', entry] as const,
  speciesMembers: (vault: string, species: string, params?: object) =>
    [vault, 'speciesMembers', species, params ?? {}] as const,
  graph: (vault: string, params: object) => [vault, 'graph', params] as const,
  speciesDescentTree: (vault: string, params: object) =>
    [vault, 'speciesDescentTree', params] as const,
}
