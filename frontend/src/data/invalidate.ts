import type { QueryClient, QueryKey } from '@tanstack/react-query'

import type { Affected } from './source'

/** Areas every write may change: lists, trees, the change feed, findings (and rule counts). */
const VAULT_WIDE = [
  'vault',
  'entities',
  'tree',
  'children',
  'trash',
  'fieldValues',
  'tags',
  'changes',
  // Changesets change too (merged saves, undone).
  'change',
  'findings',
  'consistencyRules',
  // Outline rows carry names and participant counts.
  'eventTree',
  // Causality graphs carry names and the links between events.
  'causality',
  // A series' list changes with its occurrences' writes (cancel, materialize), keyed by the series.
  'occurrences',
  // Module reads built from entities and links (names, sites, residents).
  'locationTree',
  'locationEvents',
  'locationResidents',
  'characterRelationships',
  'characterLife',
  'characterFamilyTree',
  'groupMembers',
  'groupLeaders',
  'groupTerritory',
  'groupOrgChart',
  'languageFamilyTree',
  // Lexicon writes return no entity: every write refreshes the lexicon (pages and entries).
  'lexicon',
  'lexiconEntry',
  'speciesMembers',
  'speciesDescentTree',
  // An event's "changes caused" (keyed by the event, written through the entity).
  'causedFacts',
  // What branches changed: their records and overrides, by name (timeline trees refresh with
  // time changes, which a new branch is).
  'branchDiff',
  // Correspondences show dimension names and drop out with a trashed dimension.
  'correspondences',
]
/** Areas keyed by an entity id. */
const PER_ENTITY = [
  'entity',
  'entityState',
  'facts',
  'links',
  'backlinks',
  'history',
  'occurrences',
  'worldline',
  'personalTimeline',
  'presence',
]
/** Areas that show resolved moments. */
const TIME = [
  'window',
  'eventTree',
  'causality',
  'occurrences',
  'timelines',
  'resolve',
  'locationEvents',
  'characterLife',
  // As-of reads: a moved event moves the facts and links anchored to it.
  'entityState',
  'facts',
  'links',
  'backlinks',
  // Sync points anchored to events move with them.
  'correspondences',
  // Segments anchored to events move with them; participations follow events.
  'worldline',
  'personalTimeline',
]
// Unlinked mentions read every entity's text and the aliases.
const SEARCH = ['search', 'quickSearch', 'unlinkedMentions']

/**
 * The query keys a write's `affected` makes stale (frontend.md §5.1). Prefixes: each matches every
 * query that starts with it.
 */
export function affectedKeys(vault: string, affected: Affected): QueryKey[] {
  const found: QueryKey[] = VAULT_WIDE.map((area) => [vault, area])
  for (const id of affected.entities) {
    for (const area of PER_ENTITY) found.push([vault, area, id])
  }
  // Windows are keyed by timeline: a time change anywhere refreshes the vault's windows (a
  // dimension's timelines aren't known here).
  if (affected.time_changed) for (const area of TIME) found.push([vault, area])
  for (const dimension of affected.dimensions) found.push([vault, 'timelines', dimension])
  if (affected.search_changed) for (const area of SEARCH) found.push([vault, area])
  return found
}

/** Invalidates what a write changed (`affected` of every write response). */
export async function invalidateAffected(
  client: QueryClient,
  vault: string,
  affected: Affected,
): Promise<void> {
  await Promise.all(
    affectedKeys(vault, affected).map((queryKey) => client.invalidateQueries({ queryKey })),
  )
}
