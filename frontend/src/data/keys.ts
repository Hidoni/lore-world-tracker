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
  entities: (vault: string, params?: object) => [vault, 'entities', params ?? {}] as const,
  entity: (vault: string, id: string, params?: object) =>
    [vault, 'entity', id, params ?? {}] as const,
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
  locationResidents: (vault: string, location: string) =>
    [vault, 'locationResidents', location] as const,
  characterRelationships: (vault: string, character: string) =>
    [vault, 'characterRelationships', character] as const,
  characterFamilyTree: (vault: string, character: string, params: object) =>
    [vault, 'characterFamilyTree', character, params] as const,
  characterLife: (vault: string, character: string, params: object) =>
    [vault, 'characterLife', character, params] as const,
  groupMembers: (vault: string, group: string, params: object) =>
    [vault, 'groupMembers', group, params] as const,
  groupLeaders: (vault: string, group: string) => [vault, 'groupLeaders', group] as const,
  groupTerritory: (vault: string, group: string) => [vault, 'groupTerritory', group] as const,
  languageFamilyTree: (vault: string, params: object) =>
    [vault, 'languageFamilyTree', params] as const,
  lexicon: (vault: string, language: string, params: object) =>
    [vault, 'lexicon', language, params] as const,
  lexiconEntry: (vault: string, entry: string) => [vault, 'lexiconEntry', entry] as const,
  speciesMembers: (vault: string, species: string) => [vault, 'speciesMembers', species] as const,
  speciesDescentTree: (vault: string, params: object) =>
    [vault, 'speciesDescentTree', params] as const,
}
