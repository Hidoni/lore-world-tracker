import type { components } from '@/api'

import { NotInExport, type Handler } from './static-core'
import { existenceAt, invalid, loadIndex, notFound } from './static-entities'

/**
 * Family trees of a static export (#386, ADR 0016's exception), computed in the browser for any
 * generations up and down, with or without spouses and siblings: a port of
 * `modules/characters/service.py` `family_tree` over `static/m/characters/family`
 * (`Characters.static_data`: every family link, each character's lifespan per timeline) and the
 * entity index (names, existence over time).
 */

type Genealogy = components['schemas']['Genealogy']

const PARENT_OF = 'characters.parent_of'
const SPOUSE_OF = 'characters.spouse_of'
const SIBLING_OF = 'characters.sibling_of'
const FAMILY: Record<string, Genealogy['edges'][number]['kind']> = {
  [PARENT_OF]: 'parent',
  [SPOUSE_OF]: 'spouse',
  [SIBLING_OF]: 'sibling',
}

/** `[id, type, source, target, relation]`, by id. */
type FamilyLink = [string, string, string, string, string | null]

interface FamilyData {
  links: FamilyLink[]
  /** By timeline, by character: `[from, to]`. */
  lifespans: Record<string, Record<string, [string | null, string | null]>>
}

/** The people being gathered: generation by id, in the order found (`_Tree`). */
class Tree {
  readonly generations = new Map<string, number>()
  truncated = false

  constructor(readonly limit: number) {}

  add(ids: Iterable<string>, generation: number): string[] {
    const added: string[] = []
    for (const person of ids) {
      if (this.generations.has(person)) continue
      if (this.generations.size >= this.limit) {
        this.truncated = true
        break
      }
      this.generations.set(person, generation)
      added.push(person)
    }
    return added
  }

  generation(person: string): number {
    return this.generations.get(person) ?? 0
  }
}

/** FastAPI's booleans. */
function bool(params: URLSearchParams, name: string): boolean {
  const value = params.get(name)
  if (value === null) return true
  const lower = value.toLowerCase()
  if (['true', '1', 'yes', 'on', 't', 'y'].includes(lower)) return true
  if (['false', '0', 'no', 'off', 'f', 'n'].includes(lower)) return false
  throw invalid(`${name} must be a boolean.`)
}

function int(params: URLSearchParams, name: string, fallback: number, min: number, max: number) {
  const value = params.get(name)
  if (value === null) return fallback
  const n = Number(value)
  if (!/^-?\d+$/.test(value.trim()) || n < min || n > max) {
    throw invalid(`${name} must be an integer from ${min} to ${max}.`)
  }
  return n
}

/** `GET m/characters/{id}/family-tree`. */
export const familyTree: Handler = async (load, _route, params, [vault = '', characterId = '']) => {
  const up = int(params, 'up', 3, 0, 10)
  const down = int(params, 'down', 3, 0, 10)
  const spouses = bool(params, 'include_spouses')
  const siblings = bool(params, 'include_siblings')
  const limit = int(params, 'limit', 500, 1, 1000)
  const at = params.get('at')
  let timeline = params.get('timeline')
  const derived = await loadIndex(load, vault)
  let data: FamilyData
  try {
    data = (await load(`vaults/${vault}/static/m/characters/family`)) as FamilyData
  } catch (error) {
    if (error instanceof NotInExport) throw notFound('route')
    throw error
  }
  const root = derived.index.entities[characterId]
  if (root === undefined) throw notFound(`entity ${characterId}`)
  if (root.summary.kind !== 'character') throw notFound(`character ${characterId}`)
  if (timeline !== null && !(timeline in derived.index.timelines)) {
    throw notFound(`timeline ${timeline}`)
  }
  const dimension = root.summary.dimension_id
  if (at !== null) {
    if (!/^\d+$/.test(at)) throw invalid('`at` must be a moment.')
    if (timeline === null && (dimension === null || !derived.primes.has(dimension))) {
      throw invalid('`at` needs a timeline here.')
    }
  }
  if (timeline === null && dimension !== null) timeline = derived.primes.get(dimension) ?? null

  /** The family links of `types` with `side` in `ids`, by id (`_family_links`). */
  const linksOf = (ids: Iterable<string>, types: string[], side: 'source' | 'target' | 'any') => {
    const among = new Set(ids)
    return data.links.filter(
      ([, type, source, target]) =>
        types.includes(type) &&
        (side === 'source'
          ? among.has(source)
          : side === 'target'
            ? among.has(target)
            : among.has(source) || among.has(target)),
    )
  }
  const tree = new Tree(limit)
  tree.add([characterId], 0)
  const line = [characterId]
  let frontier = [characterId]
  for (let generation = 1; generation <= up; generation++) {
    const parents = linksOf(frontier, [PARENT_OF], 'target')
    frontier = tree.add(
      parents.map(([, , source]) => source),
      -generation,
    )
    line.push(...frontier)
  }
  frontier = [characterId]
  for (let generation = 1; generation <= down; generation++) {
    const children = linksOf(frontier, [PARENT_OF], 'source')
    frontier = tree.add(
      children.map(([, , , target]) => target),
      generation,
    )
  }
  /** The people linked to `among` by a symmetric `type`, in their generation. */
  const addSymmetric = (among: string[], type: string) => {
    const set = new Set(among)
    for (const [, , source, target] of linksOf(among, [type], 'any')) {
      for (const [person, other] of [
        [source, target],
        [target, source],
      ] as const) {
        if (set.has(person)) tree.add([other], tree.generation(person))
      }
    }
  }
  if (siblings) {
    addSymmetric(line, SIBLING_OF)
    const ancestors = line.filter((person) => person !== characterId)
    for (const [, , source, target] of linksOf(ancestors, [PARENT_OF], 'source')) {
      tree.add([target], tree.generation(source) + 1)
    }
  }
  if (spouses) {
    const people = [...tree.generations.keys()]
    addSymmetric(people, SPOUSE_OF)
    const offspring = people.filter(
      (person) => person !== characterId && tree.generation(person) - 1 >= -up,
    )
    for (const [, , source, target] of linksOf(offspring, [PARENT_OF], 'target')) {
      tree.add([source], tree.generation(target) - 1)
    }
  }
  const ids = [...tree.generations.keys()]
  const edges = linksOf(ids, Object.keys(FAMILY), 'source')
    .filter(([, , , target]) => tree.generations.has(target))
    .map(([id, type, source, target, relation]) => ({
      id,
      kind: FAMILY[type] ?? 'parent',
      source_id: source,
      target_id: target,
      relation,
    }))
  // Stable: the character first, then by generation, each in the order found.
  const order = ids
    .map((person, found) => ({ person, found }))
    .sort(
      (a, b) =>
        Number(a.person !== characterId) - Number(b.person !== characterId) ||
        tree.generation(a.person) - tree.generation(b.person) ||
        a.found - b.found,
    )
    .map(({ person }) => person)
  const lifespans = timeline === null ? {} : (data.lifespans[timeline] ?? {})
  return {
    root_id: characterId,
    people: order.map((person) => {
      const entry = derived.index.entities[person]
      const [from, to] = lifespans[person] ?? [null, null]
      return {
        id: person,
        name: entry?.summary.name ?? '',
        visibility: entry?.summary.visibility ?? 'public',
        generation: tree.generation(person),
        from_t: from,
        to_t: to,
        existence:
          at !== null && timeline !== null && entry !== undefined
            ? existenceAt(entry, timeline, at)
            : null,
      }
    }),
    edges,
    truncated: tree.truncated,
  }
}
