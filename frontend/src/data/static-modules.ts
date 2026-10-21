import type { components } from '@/api'

import { NotInExport, type Handler, type Load } from './static-core'
import { queryKey } from './static-files'
import { lowerAscii, pick } from './static-entities'
import { familyTree } from './static-family'
import { graph } from './static-graph'
import { replay, type Refused } from './static-time'

/**
 * Module reads of a static export (#376, ADR 0016), as each module declares them
 * (`ModuleSpec.static_reads`) and the builder records them (`lore/static_export/modules.py`):
 * one file per route under `static/reads/`, with the answer for each query recorded, as-of
 * answers by moment (the last one at or before the cursor), and paged lists whole (filtered and
 * paged here, like the server does). A read naming its entity in the query (`graph?center=…`) has
 * a file per entity under `static/split/<route>/<param>/<id>`, listed in `static/split`: an
 * entity page loads only its own.
 */

type Schemas = components['schemas']

interface ReadsFile {
  answers: Record<string, unknown>
  as_of: Record<string, [string, unknown][]>
  lists: Record<string, unknown[]>
  /** The objects of the answers, each once: their lists are `{"#": [index, …]}`. */
  pool?: unknown[]
}

/** An answer with its pooled lists filled back in (`modules.py` `_Pool`). */
function unpool(value: unknown, pool: readonly unknown[]): unknown {
  if (Array.isArray(value)) return value.map((item) => unpool(item, pool))
  if (value === null || typeof value !== 'object') return value
  const entries = Object.entries(value)
  const [first] = entries
  if (entries.length === 1 && first?.[0] === '#' && Array.isArray(first[1]))
    return (first[1] as number[]).map((index) => unpool(pool[index], pool))
  return Object.fromEntries(entries.map(([key, item]) => [key, unpool(item, pool)]))
}

async function readsOf(load: Load, vault: string, route: string): Promise<ReadsFile> {
  return (await load(`vaults/${vault}/static/reads/${route}`)) as ReadsFile
}

/** A recorded module read: its answer for the query, at the cursor for as-of reads. */
export const moduleRead: Handler = async (load, _route, params, [vault = '', route = '']) => {
  // Reads naming their entity in the query have a file per entity (`static/split`).
  const split = ((await load(`vaults/${vault}/static/split`)) as Record<string, string[]>)[
    route
  ]?.find((name) => params.has(name))
  let file: ReadsFile
  try {
    file =
      split === undefined
        ? await readsOf(load, vault, route)
        : ((await load(
            `vaults/${vault}/static/split/${route}/${split}/${params.get(split) ?? ''}`,
          )) as ReadsFile)
  } catch (error) {
    // Not a declared read: a read recorded as a plain file (`m/correspondences/<id>`).
    if (!(error instanceof NotInExport) || queryKey(params) !== '[]') throw error
    return load(`vaults/${vault}/${route}`)
  }
  const key = queryKey(params)
  const at = params.get('at')
  if (at !== null) {
    const intervals = file.as_of[key]
    if (intervals === undefined) throw new NotInExport(route)
    return replay(unpool(pick(intervals, at), file.pool ?? []) as object | Refused, route)
  }
  if (!(key in file.answers)) throw new NotInExport(route)
  return replay(unpool(file.answers[key], file.pool ?? []) as object | Refused, route)
}

/** Our own cursors: the position after the last item returned. */
function page<T>(items: T[], params: URLSearchParams, fallback: number) {
  const cursor = params.get('cursor')
  const start = cursor === null ? 0 : Number(atob(cursor))
  const end = start + Number(params.get('limit') ?? String(fallback))
  return {
    items: items.slice(start, end),
    next_cursor: end < items.length ? btoa(String(end)) : null,
  }
}

type Entry = Schemas['LexiconEntryOut']

/** `GET …/lexicon`: the recorded list in the asked order, filtered as `lexicon.py` `page`. */
const lexicon: Handler = async (load, _route, params, [vault = '', language = '']) => {
  const route = `m/languages/${language}/lexicon`
  const file = await readsOf(load, vault, route)
  const sort = params.get('sort') ?? 'collation'
  const items = file.lists[JSON.stringify([['sort', sort]])] as Entry[] | undefined
  if (items === undefined) throw new NotInExport(route)
  const q = lowerAscii((params.get('q') ?? '').trim())
  const pos = params.get('pos')
  const tag = params.get('tag')
  const matches = (entry: Entry) =>
    (q === '' ||
      lowerAscii(entry.headword).startsWith(q) ||
      lowerAscii(entry.romanization ?? '').startsWith(q) ||
      entry.definitions.some((d) => lowerAscii(d.gloss).includes(q))) &&
    (!pos || entry.part_of_speech === pos) &&
    (!tag || entry.tags.includes(tag))
  return page(items.filter(matches), params, 100)
}

type MediaItem = Schemas['MediaItemOut']

/** `GET m/media/items`: the recorded library (newest first), filtered as `media/service.py`. */
const mediaItems: Handler = async (load, _route, params, [vault = '']) => {
  const route = 'm/media/items'
  const file = await readsOf(load, vault, route)
  const items = file.lists['[]'] as MediaItem[] | undefined
  if (items === undefined) throw new NotInExport(route)
  // A published snapshot holds no trashed items, and no references readers can't see.
  if (params.get('trashed') === 'true') return { items: [], next_cursor: null }
  const q = lowerAscii(params.get('q') ?? '')
  const mime = params.get('mime')
  const entity = params.get('entity')
  const unused = params.get('unused') === 'true'
  const matches = (item: MediaItem) =>
    (!unused || (item.refs ?? []).length === 0) &&
    (entity === null || (item.refs ?? []).some((ref) => ref.entity_id === entity)) &&
    (!q || [item.filename, item.alt, item.caption].some((text) => lowerAscii(text).includes(q))) &&
    (!mime || (mime.endsWith('/') ? item.mime.startsWith(mime) : item.mime === mime))
  return page(items.filter(matches), params, 100)
}

const V = '^vaults/([^/]+)'

/** The module reads of a static export, by route: lists and computed views first, then any
 * recorded read. */
export const MODULE_HANDLERS: readonly (readonly [RegExp, Handler])[] = [
  [new RegExp(`${V}/m/languages/([^/]+)/lexicon$`), lexicon],
  [new RegExp(`${V}/m/media/items$`), mediaItems],
  [new RegExp(`${V}/m/graph/graph$`), graph],
  [new RegExp(`${V}/m/characters/([^/]+)/family-tree$`), familyTree],
  [new RegExp(`${V}/(m/.+)$`), moduleRead],
]
