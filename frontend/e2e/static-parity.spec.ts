import type { APIRequestContext, Page } from '@playwright/test'

import { expect, STATIC_READER_URL, STATIC_URL, test } from './fixtures'

// Parity of the static export (ADR 0016, #374–#377): for the tiny sample world, every read the
// export holds answers what the read-only server answers readers for the same snapshot. Paged
// lists are compared as their concatenated pages (an export's cursors are its own).
test.skip(STATIC_URL === '' || STATIC_READER_URL === '', 'the static export is not served')

interface Answer {
  status: number
  body: unknown
}

type Json = Record<string, unknown>

const API = '/api/v1/'

/** The item at `index`, which the test knows is there. */
function at<T>(items: readonly T[], index: number): T {
  const item = items[index]
  if (item === undefined) throw new Error(`no item ${index}`)
  return item
}

/** The answers of the export (in the page) and of the server, for API routes. */
async function both(page: Page, request: APIRequestContext, routes: string[]) {
  const exported = await page.evaluate(
    async (urls) => {
      const fetch = (window as unknown as { loreStaticFetch: (r: Request) => Promise<Response> })
        .loreStaticFetch
      return Promise.all(
        urls.map(async (url) => {
          const response = await fetch(new Request(url))
          return { status: response.status, body: (await response.json()) as unknown }
        }),
      )
    },
    routes.map((route) => `http://static.invalid${API}${route}`),
  )
  const served: Answer[] = []
  for (let i = 0; i < routes.length; i += 8) {
    const batch = routes.slice(i, i + 8).map(async (route) => {
      const response = await request.get(`${STATIC_READER_URL}${API}${route}`)
      return { status: response.status(), body: (await response.json()) as unknown }
    })
    served.push(...(await Promise.all(batch)))
  }
  return routes.map((route, i) => ({ route, exported: at(exported, i), served: at(served, i) }))
}

/** Where two JSON values first differ (a path and both values), or `null`. */
function firstDifference(a: unknown, b: unknown, path = ''): string | null {
  if (typeof a !== 'object' || typeof b !== 'object' || a === null || b === null) {
    return Object.is(a, b) ? null : `${path}: ${JSON.stringify(a)} ≠ ${JSON.stringify(b)}`
  }
  if (Array.isArray(a) !== Array.isArray(b)) return `${path}: array ≠ object`
  const keys = new Set([...Object.keys(a), ...Object.keys(b)])
  for (const key of keys) {
    const found = firstDifference(
      (a as Record<string, unknown>)[key],
      (b as Record<string, unknown>)[key],
      `${path}.${key}`,
    )
    if (found) return found
  }
  return null
}

/** The routes whose answers differ: the route and where (export ≠ server). */
function differences(results: Awaited<ReturnType<typeof both>>) {
  return results.flatMap(({ route, exported, served }) => {
    const found = firstDifference(exported, served)
    return found ? [`${route} ${found}`] : []
  })
}

/** Every item of a paged list, from either side, following its own cursors. */
async function allPages(
  page: Page,
  request: APIRequestContext,
  route: string,
): Promise<{ exported: unknown[]; served: unknown[] }> {
  const join = route.includes('?') ? '&' : '?'
  const follow = async (get: (r: string) => Promise<Answer>) => {
    const items: unknown[] = []
    let cursor: string | null = null
    for (let n = 0; n < 50; n++) {
      const { status, body } = await get(cursor ? `${route}${join}cursor=${cursor}` : route)
      expect(status, route).toBe(200)
      const answer = body as { items: unknown[]; next_cursor: string | null }
      items.push(...answer.items)
      cursor = answer.next_cursor
      if (cursor === null) break
    }
    return items
  }
  const exported = await follow(async (r) => at(await both(page, request, [r]), 0).exported)
  const served = await follow(async (r) => {
    const response = await request.get(`${STATIC_READER_URL}${API}${r}`)
    return { status: response.status(), body: (await response.json()) as unknown }
  })
  return { exported, served }
}

/** Moments around every bound of the entity's facts and links: where answers change. */
function momentsOf(facts: Json[], links: Json[]): string[] {
  const found = new Set<bigint>([0n])
  for (const row of [...facts, ...links]) {
    for (const key of ['valid_from_t', 'valid_to_t']) {
      const t = row[key]
      if (typeof t === 'string') {
        for (const d of [-1n, 0n, 1n]) if (BigInt(t) + d >= 0n) found.add(BigInt(t) + d)
      }
    }
  }
  return [...found].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0)).map(String)
}

test('entity reads answer like the read-only server', async ({ page, request }) => {
  test.setTimeout(240_000)
  await page.goto(STATIC_URL)
  const vaults = (await (await request.get(`${STATIC_READER_URL}${API}vaults`)).json()) as {
    items: Json[]
  }
  const vault = at(vaults.items, 0).id as string
  const base = `vaults/${vault}`
  const listed = await allPages(page, request, `${base}/entities?limit=500`)
  expect(listed.exported).toEqual(listed.served)
  const entities = listed.served as Json[]
  const timelineEntities = entities.filter((e) => e.kind === 'timeline')
  const timelines = timelineEntities.map((e) => e.id as string)
  const dimensions = entities.filter((e) => e.kind === 'dimension').map((e) => e.id as string)

  // Every entity's own reads, without a cursor.
  const routes: string[] = []
  for (const { id } of entities) {
    const route = `${base}/entities/${id as string}`
    routes.push(route, `${route}/links`, `${route}/backlinks`, `${route}/facts`)
    routes.push(`${route}/unlinked-mentions`, `${route}/children`)
    routes.push(`${route}/links?direction=out`, `${route}/links?direction=in`)
  }
  expect(differences(await both(page, request, routes))).toEqual([])

  // As-of reads at the moments around every bound, in each timeline the entity is seen in.
  const asOf: string[] = []
  const served = await both(
    page,
    request,
    entities.flatMap(({ id }) => [
      `${base}/entities/${id as string}/facts`,
      `${base}/entities/${id as string}/links`,
    ]),
  )
  for (let i = 0; i < entities.length; i++) {
    const entity = at(entities, i)
    const facts = (at(served, 2 * i).served.body as { items: Json[] }).items
    const links = (at(served, 2 * i + 1).served.body as { items: Json[] }).items.map(
      (item) => item.link as Json,
    )
    const route = `${base}/entities/${entity.id as string}`
    // The default timeline, and each one the entity can be seen in (its dimension's, or all).
    const inTimelines = [
      ...(entity.dimension_id === null ? [] : ['']),
      ...timelineEntities
        .filter((t) => entity.dimension_id === null || t.dimension_id === entity.dimension_id)
        .map((t) => t.id as string),
    ]
    for (const at of momentsOf(facts, links)) {
      for (const timeline of inTimelines) {
        const query = `at=${at}${timeline ? `&timeline=${timeline}` : ''}`
        asOf.push(`${route}?${query}`, `${route}/state?${query}`, `${route}/links?${query}`)
        asOf.push(`${route}/backlinks?${query}`)
      }
    }
  }
  expect(differences(await both(page, request, asOf))).toEqual([])

  // Lists and trees, with filters, sorts and the cursor.
  const lists: string[] = []
  for (const sort of ['name', '-name', 'created', '-updated', 'sort_key']) {
    lists.push(`${base}/entities?sort=${sort}&limit=500`)
  }
  const kinds = [...new Set(entities.map((e) => e.kind as string))]
  for (const kind of kinds) lists.push(`${base}/entities?kind=${kind}&limit=500`)
  for (const dimension of dimensions) {
    lists.push(`${base}/entities?dimension=${dimension}&limit=500`)
    lists.push(`${base}/entities?dimension=${dimension}&include_multiversal=false&limit=500`)
    lists.push(`${base}/tree?dimension=${dimension}`)
    for (const at of ['0', '100000', '5000000', '9000000000']) {
      lists.push(`${base}/entities?dimension=${dimension}&at=${at}&limit=500`)
      lists.push(`${base}/tree?dimension=${dimension}&at=${at}`)
    }
  }
  for (const timeline of timelines) {
    lists.push(`${base}/entities?timeline=${timeline}&limit=500`)
    lists.push(`${base}/tree?timeline=${timeline}`)
  }
  lists.push(`${base}/entities?q=a&limit=500`, `${base}/entities?q=Il&limit=500`)
  lists.push(`${base}/tree`, `${base}/tree?kind=character`)
  for (const { id } of entities.filter((e) => e.parent_id !== null).slice(0, 20)) {
    lists.push(`${base}/entities?parent=${id as string}&limit=500`)
  }
  expect(differences(await both(page, request, lists))).toEqual([])

  // Paged with the default size: the same items, page after page.
  const paged = await allPages(page, request, `${base}/entities?limit=7&sort=-created`)
  expect(paged.exported).toEqual(paged.served)
})

test('time reads answer like the read-only server', async ({ page, request }) => {
  test.setTimeout(240_000)
  await page.goto(STATIC_URL)
  const get = async (route: string) =>
    (await (await request.get(`${STATIC_READER_URL}${API}${route}`)).json()) as Json
  const vault = at((await get('vaults')).items as Json[], 0).id as string
  const base = `vaults/${vault}`
  const entities = (await allPages(page, request, `${base}/entities?limit=500`)).served as Json[]
  const timelines = entities.filter((e) => e.kind === 'timeline')
  const dimensions = entities.filter((e) => e.kind === 'dimension').map((e) => e.id as string)
  const branches: string[] = []
  const routes: string[] = []
  for (const dimension of dimensions) {
    routes.push(`${base}/dimensions/${dimension}/timelines`)
    routes.push(`${base}/m/correspondences?dimension=${dimension}`)
    for (const t of (await get(`${base}/dimensions/${dimension}/timelines`)).items as Json[]) {
      if (t.parent_timeline_id !== null) branches.push(t.id as string)
    }
  }
  routes.push(`${base}/m/correspondences`)
  const syncMoments = new Set<bigint>([0n, 1n, 1_000_000n, 10n ** 12n])
  for (const c of (await get(`${base}/m/correspondences`)).items as Json[]) {
    routes.push(`${base}/m/correspondences/${c.id as string}`)
    for (const point of c.points as Json[]) {
      for (const key of ['a_t', 'b_t']) {
        const t = point[key]
        if (typeof t === 'string') for (const d of [-1n, 0n, 1n]) syncMoments.add(BigInt(t) + d)
      }
    }
  }
  // Mapping between every pair of dimensions, at the sync points and around them, past the end.
  for (const from of dimensions) {
    const ext = (await get(`${base}/entities/${from}`)).ext as Json
    const duration = BigInt(ext.duration as string)
    for (const to of dimensions) {
      for (const t of [...syncMoments, duration, duration + 1n]) {
        const query = `from_dimension=${from}&to_dimension=${to}&t=${t}`
        if (t >= 0n) routes.push(`${base}/m/correspondences/map?${query}`)
      }
    }
  }

  // Event trees (every level, paged small), and the graph around each event at a few sizes.
  for (const { id: timeline } of timelines) {
    const route = `${base}/timelines/${timeline as string}`
    const levels: (string | null)[] = [null]
    while (levels.length > 0) {
      const parent = levels.pop() ?? null
      const query = parent === null ? '' : `parent=${parent}&`
      const tree = await allPages(page, request, `${route}/event-tree?${query}limit=3`)
      expect(tree.exported, `${route} ${parent ?? 'roots'}`).toEqual(tree.served)
      for (const node of tree.served as Json[]) {
        if (node.has_children) levels.push(node.id as string)
        for (const size of ['depth=1', 'depth=2&limit=3', 'depth=6&limit=500', '']) {
          routes.push(`${route}/causality?event=${node.id as string}${size ? `&${size}` : ''}`)
        }
      }
    }
  }
  for (const branch of branches) {
    const route = `${base}/m/branches/timelines/${branch}/diff`
    routes.push(route, `${route}?limit=1`)
    for (const { id } of entities.slice(0, 40)) {
      routes.push(`${base}/m/branches/notes/${id as string}/${branch}`)
    }
  }

  // Worldlines: segments and personal timelines per timeline, presence around every bound.
  for (const entity of entities.filter((e) => e.kind === 'character')) {
    const route = `${base}/m/worldlines/entities/${entity.id as string}`
    for (const timeline of ['', ...timelines.map((t) => t.id as string)]) {
      const q = timeline ? `timeline=${timeline}` : ''
      const segments = await request.get(`${STATIC_READER_URL}${API}${route}/segments?${q}`)
      if (segments.status() !== 200) continue
      routes.push(`${route}/segments?${q}`, `${route}/personal-timeline?${q}`)
      routes.push(`${route}/personal-timeline?include=jumps&include=existence&${q}`)
      const moments = new Set<bigint>([0n])
      for (const s of ((await segments.json()) as { segments: Json[] }).segments) {
        for (const key of ['start_t', 'end_t']) {
          const t = s[key]
          if (typeof t === 'string') for (const d of [-1n, 0n, 1n]) moments.add(BigInt(t) + d)
        }
      }
      const where = timelines.find((t) => t.id === timeline)
      for (const dimension of where ? [where.dimension_id as string] : dimensions) {
        for (const t of moments) {
          if (t >= 0n) routes.push(`${route}/presence?dimension=${dimension}&t=${t}&${q}`)
        }
      }
    }
  }
  expect(differences(await both(page, request, routes))).toEqual([])
})

/** A seeded generator (mulberry32): the same windows every run. */
function seeded(seed: number) {
  let a = seed
  return () => {
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

test('window reads answer like the read-only server', async ({ page, request }) => {
  test.setTimeout(600_000)
  await page.goto(STATIC_URL)
  const get = async (route: string) =>
    (await (await request.get(`${STATIC_READER_URL}${API}${route}`)).json()) as Json
  const vault = at((await get('vaults')).items as Json[], 0).id as string
  const base = `vaults/${vault}`
  const entities = (await allPages(page, request, `${base}/entities?limit=500`)).served as Json[]
  const timelines = entities.filter((e) => e.kind === 'timeline')
  const characters = entities.filter((e) => e.kind === 'character').map((e) => e.id as string)
  const tags = ((await get(`${base}/tags?limit=1000`)).items as Json[]).map((t) => t.id as string)
  const random = seeded(375)
  const routes: string[] = []
  const series = new Set<string>()
  for (const timeline of timelines) {
    const dimension = (await get(`${base}/entities/${timeline.dimension_id as string}`)).ext as Json
    const duration = BigInt(dimension.duration as string)
    const route = `${base}/timelines/${timeline.id as string}/window`
    // The whole dimension at many budgets, then windows at every zoom (by powers of ten).
    const windows: [bigint, bigint][] = [[0n, duration + 1n]]
    for (let zoom = 1n; zoom <= duration; zoom *= 10n) {
      for (let n = 0; n < 2; n++) {
        const width = duration / zoom + BigInt(Math.floor(random() * 3))
        const start = (duration * BigInt(Math.floor(random() * 1_000_000))) / 1_000_000n
        windows.push([start, start + (width > 0n ? width : 1n)])
      }
    }
    const whole = await get(`${route}?from=0&to=${duration + 1n}&px=2000`)
    const items = whole.items as Json[]
    for (const item of items) if (item.series_id) series.add(item.series_id as string)
    for (const band of whole.series_bands as Json[]) series.add(band.entity_id as string)
    const categories = [...new Set(items.map((i) => i.category).filter((c) => c !== null))]
    const parents = items.filter((i) => i.has_children).map((i) => i.entity_id as string)
    const filters = [
      'min_importance=3',
      'min_importance=5',
      ...categories.slice(0, 3).map((c) => `category=${c as string}`),
      ...tags.slice(0, 3).map((t) => `tag=${t}`),
      ...characters.slice(0, 3).map((c) => `participant=${c}`),
      'participant_kind=character&participant_kind=location',
      ...parents.slice(0, 3).map((p) => `parent=${p}`),
      'include_series=false',
      'include_cancelled=true',
    ]
    for (const [i, [from, to]] of windows.entries()) {
      for (const px of [1, 120, 2400]) routes.push(`${route}?from=${from}&to=${to}&px=${px}`)
      const filter = filters[i % filters.length] ?? ''
      routes.push(`${route}?from=${from}&to=${to}&px=640&${filter}`)
    }
    for (const filter of filters) routes.push(`${route}?from=0&to=${duration + 1n}&px=40&${filter}`)
    routes.push(`${route}?from=5&to=5&px=100`, `${route}?from=0&to=10&px=10&parent=${vault}`)
  }

  // Occurrences of every series seen: as each timeline sees it, at every zoom and limit.
  for (const id of series) {
    const route = `${base}/events/${id}/occurrences`
    const event = await get(`${base}/entities/${id}`)
    const dimension = (await get(`${base}/entities/${event.dimension_id as string}`)).ext as Json
    const duration = BigInt(dimension.duration as string)
    for (const timeline of ['', ...timelines.map((t) => `&timeline=${t.id as string}`)]) {
      routes.push(`${route}?from=0&to=${duration + 1n}${timeline}`)
      routes.push(
        `${route}?from=0&to=${duration + 1n}&limit=1000&include_cancelled=true${timeline}`,
      )
      for (let zoom = 10n; zoom <= duration; zoom *= 100n) {
        const start = (duration * BigInt(Math.floor(random() * 1_000_000))) / 1_000_000n
        for (const limit of [1, 5, 100]) {
          routes.push(
            `${route}?from=${start}&to=${start + duration / zoom + 1n}&limit=${limit}${timeline}`,
          )
        }
      }
    }
    routes.push(`${route}?from=3&to=3`)
  }
  const nonSeries = entities.find((e) => e.kind === 'event' && !series.has(e.id as string))
  if (nonSeries) routes.push(`${base}/events/${nonSeries.id as string}/occurrences?from=0&to=10`)
  expect(series.size).toBeGreaterThan(0)
  expect(differences(await both(page, request, routes))).toEqual([])
})

test('module reads and files answer like the read-only server', async ({ page, request }) => {
  test.setTimeout(900_000)
  await page.goto(STATIC_URL)
  const get = async (route: string) =>
    (await (await request.get(`${STATIC_READER_URL}${API}${route}`)).json()) as Json
  const vault = at((await get('vaults')).items as Json[], 0).id as string
  const base = `vaults/${vault}`
  const entities = (await allPages(page, request, `${base}/entities?limit=500`)).served as Json[]
  const timelines = entities.filter((e) => e.kind === 'timeline')
  const dimensions = entities.filter((e) => e.kind === 'dimension').map((e) => e.id as string)
  const of = (kind: string) => entities.filter((e) => e.kind === kind).map((e) => e.id as string)
  // Every moment answers can change at (and around it), from every entity's facts and links.
  const moments = new Set<string>(['0'])
  for (const { id } of entities) {
    const facts = (await get(`${base}/entities/${id as string}/facts`)).items as Json[]
    const links = (await get(`${base}/entities/${id as string}/links`)).items as Json[]
    for (const t of momentsOf(facts, links)) moments.add(t)
  }
  const seenIn = (id: string) => {
    const dimension = entities.find((e) => e.id === id)?.dimension_id ?? null
    return timelines
      .filter((t) => dimension === null || t.dimension_id === dimension)
      .map((t) => t.id as string)
  }
  const routes: string[] = []
  /** The read without a timeline, in each timeline, and at every moment there. */
  const asOf = (route: string, id: string | null, timelineOnly = false) => {
    const join = route.includes('?') ? '&' : '?'
    routes.push(route)
    for (const timeline of id === null ? timelines.map((t) => t.id as string) : seenIn(id)) {
      routes.push(`${route}${join}timeline=${timeline}`)
      if (timelineOnly) continue
      for (const t of moments) routes.push(`${route}${join}timeline=${timeline}&at=${t}`)
    }
  }
  const m = `${base}/m`
  for (const id of of('character')) {
    asOf(`${m}/characters/${id}/relationships`, id)
    asOf(`${m}/characters/${id}/life`, id, true)
    for (const n of ['2', '3']) {
      const q = `up=${n}&down=${n}&include_spouses=true&include_siblings=true`
      asOf(`${m}/characters/${id}/family-tree?${q}`, id)
    }
  }
  for (const id of of('group')) {
    asOf(`${m}/groups/${id}/members?include_subgroups=false`, id)
    asOf(`${m}/groups/${id}/members?include_subgroups=true`, id)
    asOf(`${m}/groups/${id}/leaders`, id)
    asOf(`${m}/groups/${id}/territory`, id)
    asOf(`${m}/groups/${id}/org-chart?depth=3`, id)
  }
  routes.push(`${m}/locations/tree?depth=6&limit=500`)
  for (const id of of('location')) {
    routes.push(
      `${m}/locations/tree?root=${id}`,
      `${m}/locations/tree?root=${id}&depth=6&limit=500`,
    )
    asOf(`${m}/locations/${id}/events?include_descendants=true`, id, true)
    asOf(`${m}/locations/${id}/events?include_descendants=false`, id, true)
    asOf(`${m}/locations/${id}/residents`, id)
    routes.push(`${m}/maps/maps?location=${id}`)
  }
  for (const id of of('species')) asOf(`${m}/species/${id}/members`, id)
  for (const dimension of ['', ...dimensions]) {
    const q = dimension ? `?dimension=${dimension}` : ''
    routes.push(`${m}/species/descent-tree${q}`, `${m}/languages/family-tree${q}`)
  }
  // The graph page, and the local graph of a sample of entities.
  routes.push(`${m}/graph/graph`)
  for (const dimension of dimensions) {
    const route = `${m}/graph/graph?dimension=${dimension}`
    routes.push(route)
    for (const t of timelines.filter((t) => t.dimension_id === dimension)) {
      routes.push(`${route}&timeline=${t.id as string}`)
      for (const moment of moments) routes.push(`${route}&timeline=${t.id as string}&at=${moment}`)
    }
  }
  for (const { id } of entities.slice(0, 15)) {
    for (const depth of ['1', '2'])
      asOf(`${m}/graph/graph?center=${id as string}&depth=${depth}`, id as string)
  }
  // Maps, pins and galleries.
  routes.push(`${m}/maps/maps`)
  const maps = (await get(`${m}/maps/maps`)).items as Json[]
  // Pins have validities of their own: their bounds too.
  for (const map of maps) {
    const pins = (await get(`${m}/maps/maps/${map.id as string}`)).pins as Json[]
    for (const t of momentsOf(pins, [])) moments.add(t)
  }
  for (const map of maps) asOf(`${m}/maps/maps/${map.id as string}`, null)
  for (const { id } of entities) {
    routes.push(
      `${m}/maps/entities/${id as string}/pins`,
      `${m}/media/entities/${id as string}/gallery`,
    )
  }
  // The lexicon of each language, in each order and filtered; its entries.
  for (const language of of('language')) {
    const route = `${m}/languages/${language}/lexicon`
    for (const sort of ['collation', 'headword', 'recent']) {
      const list = await allPages(page, request, `${route}?sort=${sort}&limit=7`)
      expect(list.exported, `${route} ${sort}`).toEqual(list.served)
      for (const entry of list.served as Json[])
        routes.push(`${m}/languages/lexicon/${entry.id as string}`)
    }
    for (const q of ['a', 'Th', 'e', 'water', 'zz']) routes.push(`${route}?q=${q}&limit=50`)
    routes.push(`${route}?pos=noun`, `${route}?tag=core`, `${route}?sort=headword&q=a&limit=3`)
  }
  // The media library, filtered; each item.
  const library = await allPages(page, request, `${m}/media/items?limit=2`)
  expect(library.exported).toEqual(library.served)
  for (const item of library.served as Json[]) routes.push(`${m}/media/items/${item.id as string}`)
  for (const q of ['q=png', 'mime=image/', 'mime=image/png', 'unused=true', 'trashed=true']) {
    routes.push(`${m}/media/items?${q}`)
  }
  for (const { id } of entities.slice(0, 30)) routes.push(`${m}/media/items?entity=${id as string}`)
  expect(differences(await both(page, request, routes))).toEqual([])

  // The copied files are the server's bytes.
  const files = (await (
    await request.get(`${STATIC_URL}data/${base}/static/files.json`)
  ).json()) as Record<string, string>
  expect(Object.keys(files).length).toBeGreaterThan(0)
  for (const [key, path] of Object.entries(files)) {
    const [route = '', query = '[]'] = key.split('?')
    const params = new URLSearchParams(JSON.parse(query) as [string, string][])
    const served = await request.get(
      `${STATIC_READER_URL}${API}${base}/${route}?${params.toString()}`,
    )
    const copied = await request.get(`${STATIC_URL}data/${path}`)
    expect(copied.status(), path).toBe(200)
    expect(Buffer.compare(await copied.body(), await served.body()), path).toBe(0)
  }
})
