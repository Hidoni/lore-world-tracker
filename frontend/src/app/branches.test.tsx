import type { Editor } from '@tiptap/core'
import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'

import {
  CAPS,
  defaultRows,
  entityOut,
  kind,
  KINDS,
  row,
  serveVault,
  type FactRow,
  type LinkRow,
} from '@/test/fake-vault'
import { server } from '@/test/msw'
import { expectNoEditing, settled } from '@/test/reader'
import { renderApp } from '@/test/render-app'

import { moduleDefinitions } from '../modules'

const SECOND = { singular: 'second', plural: 'seconds', abbr: 's' }
const WAIT = { timeout: 5000 }

beforeEach(() => {
  localStorage.clear()
})

const EVENT_KIND = kind('event', 'Event', {
  allowed_parents: ['event'],
  capabilities: { ...CAPS, is_time_bound: true, has_existence: false },
})
const ARTIFACT = kind('artifact', 'Artifact', {
  allowed_parents: ['artifact'],
  capabilities: { ...CAPS, has_existence: true },
})

function eventRow(id: string, name: string, start: bigint, end: bigint, timeline = 'd1-prime') {
  const point = (t: bigint) => ({
    anchor: { kind: 'absolute', t: t.toString() },
    precision: 'base',
  })
  return row(id, 'event', name, {
    ext: {
      timeline_id: timeline,
      start: point(start),
      end: { kind: 'time_point', time_point: point(end) },
      start_t: start.toString(),
      end_t: end.toString(),
      importance: 3,
      category: null,
      recurrence: null,
      time_status: 'ok',
    },
    ...(timeline === 'd1-prime' ? {} : { origin_timeline_id: timeline }),
  })
}

const timeline = (id: string, name: string, parent: string | null, branchT: string | null) => ({
  id,
  name,
  visibility: 'public',
  is_prime: parent === null,
  parent_timeline_id: parent,
  branch_point:
    branchT === null ? null : { anchor: { kind: 'absolute', t: branchT }, precision: 'base' },
  branch_t: branchT,
  time_status: branchT === null ? null : 'ok',
  trashed: false,
  children: [] as unknown[],
})

interface Requests {
  notes: Record<string, unknown>[]
  branches: Record<string, unknown>[]
  overrides: Record<string, unknown>[]
  reverts: string[]
}

/**
 * The Empire (present at 500): Prime, and "Survives" branching at 200. The Coronation (100–150)
 * is the shared past, the Reign (100–300) spans the branch point, the Rescue (210–220) happens in
 * the branch only. The Crown exists 50–300 and was "Old Crown" until 150 (both from Prime).
 */
function world(
  options: {
    created?: unknown[]
    overridden?: unknown[]
    note?: { body: unknown; revision: number }
    facts?: FactRow[]
    links?: LinkRow[]
    modules?: string[]
  } = {},
) {
  const requests: Requests = { notes: [], branches: [], overrides: [], reverts: [] }
  let note: { body: unknown; revision: number } = options.note ?? { body: null, revision: 0 }
  serveVault({
    modules: options.modules ?? ['branches'],
    kinds: [...KINDS, EVENT_KIND, ARTIFACT, kind('timeline', 'Timeline')],
    rows: [
      ...defaultRows().filter((entity) => entity.id !== 'd1'),
      row('d1', 'dimension', 'Empire', {
        ext: {
          base_unit: SECOND,
          duration: '1000000',
          default_calendar_id: null,
          present: null,
          present_t: '500',
          time_status: 'ok',
          prime_timeline_id: 'd1-prime',
        },
      }),
      eventRow('ev-cor', 'Coronation', 100n, 150n),
      eventRow('ev-reign', 'Reign', 100n, 300n),
      eventRow('ev-rescue', 'Rescue', 210n, 220n, 'b1'),
      row('crown', 'artifact', 'Crown'),
      row('d1-prime', 'timeline', 'Prime'),
      row('b1', 'timeline', 'Survives', { summary: 'The emperor survives.' }),
    ],
    facts: options.facts ?? [
      { id: 'f-life', entity_id: 'crown', field_key: 'core.exists', valid_from_t: '50', valid_to_t: '300' },
      { id: 'f-old', entity_id: 'crown', field_key: 'core.exists', valid_from_t: '10', valid_to_t: '40' },
    ], // prettier-ignore
    links: options.links ?? [
      { id: 'l-past', link_type: 'core.related', source_id: 'crown', target_id: 'ev-cor',
        timeline_id: 'd1-prime', valid_from_t: '100', valid_to_t: '150' },
      { id: 'l-span', link_type: 'core.related', source_id: 'crown', target_id: 'ev-reign',
        timeline_id: 'd1-prime', valid_from_t: '100', valid_to_t: null },
    ], // prettier-ignore
  })
  const prime = timeline('d1-prime', 'Prime', null, null)
  prime.children = [timeline('b1', 'Survives', 'd1-prime', '200')]
  server.use(
    http.get('*/api/v1/vaults/v1/dimensions/d1/timelines', () =>
      HttpResponse.json({ dimension_id: 'd1', items: [prime] }),
    ),
    http.get('*/api/v1/vaults/v1/m/branches/timelines/:id/diff', ({ params }) =>
      HttpResponse.json({
        timeline_id: params.id,
        against_id: 'd1-prime',
        branch_t: '200',
        created: options.created ?? [],
        overridden: options.overridden ?? [],
        inherited_spanning: [],
        truncated: false,
      }),
    ),
    http.post('*/api/v1/vaults/v1/m/branches/timelines', async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>
      requests.branches.push(body)
      return HttpResponse.json(
        {
          entity: entityOut(row('b2', 'timeline', String(body.name))),
          affected: affected(['b2']),
        },
        { status: 201 },
      )
    }),
    http.post('*/api/v1/vaults/v1/m/branches/overrides', async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>
      requests.overrides.push(body)
      return HttpResponse.json(
        {
          record_type: body.record_type,
          id: 'override-1',
          root_id: body.root_id,
          timeline_id: body.timeline_id,
          affected: affected([]),
        },
        { status: 201 },
      )
    }),
    http.get('*/api/v1/vaults/v1/m/branches/notes/:entity/:timeline', ({ params }) =>
      HttpResponse.json({
        entity_id: params.entity,
        timeline_id: params.timeline,
        ...note,
        updated_at: null,
      }),
    ),
    http.put(
      '*/api/v1/vaults/v1/m/branches/notes/:entity/:timeline',
      async ({ request, params }) => {
        const body = (await request.json()) as { body: unknown; revision: number }
        requests.notes.push(body)
        note = { body: body.body, revision: body.revision + 1 }
        return HttpResponse.json({
          entity_id: params.entity,
          timeline_id: params.timeline,
          ...note,
          updated_at: '2026-10-14T10:00:00Z',
        })
      },
    ),
    // Time points resolve to their absolute moment (relative ones to 0).
    http.post('*/api/v1/vaults/v1/time/resolve', async ({ request }) => {
      const body = (await request.json()) as {
        items: { time_point: { anchor: { kind: string; t?: string } } }[]
      }
      const ok = (t: string) => ({
        t,
        status: 'ok',
        extent: { lo: t, hi: t },
        precision: 'base',
        approximate: false,
        display: `t = ${t}`,
        error: null,
        default_precision: null,
      })
      return HttpResponse.json({
        calendar_id: null,
        items: body.items.map(({ time_point }) => {
          const t = time_point.anchor.kind === 'absolute' ? (time_point.anchor.t ?? '0') : '0'
          return { start: ok(t), end: ok(t) }
        }),
      })
    }),
    http.delete('*/api/v1/vaults/v1/m/branches/overrides/:type/:id', ({ params }) => {
      requests.reverts.push(`${String(params.type)}/${String(params.id)}`)
      return HttpResponse.json({
        record_type: params.type,
        id: params.id,
        root_id: 'root',
        timeline_id: 'b1',
        affected: affected([]),
      })
    }),
  )
  return requests
}

const affected = (entities: string[]) => ({
  entities,
  dimensions: ['d1'],
  time_changed: true,
  search_changed: false,
})

const render = (path: string) => renderApp(path, moduleDefinitions)
const status = () => screen.findByTestId('event-branch-status', {}, WAIT)

describe('timeline switcher', () => {
  it('lists the timelines with their branch points and switches the timeline', async () => {
    world()
    const { router } = await render('/v/v1/e/crown')
    const switcher = await screen.findByRole('button', { name: 'Timeline: Prime' }, WAIT)
    await userEvent.click(switcher)
    expect(await screen.findByText('branches at t = 200 s')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('menuitemradio', { name: /Survives/ }))
    await waitFor(() => {
      expect(router.state.location.search).toMatchObject({ tl: 'b1' })
    })
    expect(await screen.findByRole('button', { name: 'Timeline: Survives' })).toBeInTheDocument()
  })

  it('creates a branch of the viewed timeline and switches to it', async () => {
    const requests = world()
    const { router } = await render('/v/v1/e/crown?tl=b1')
    await userEvent.click(await screen.findByRole('button', { name: 'Timeline: Survives' }, WAIT))
    await userEvent.click(await screen.findByRole('menuitem', { name: 'New branch…' }))
    const dialog = await screen.findByRole('dialog', { name: 'New branch' })
    await userEvent.type(within(dialog).getByLabelText('Name'), 'Exile')
    await userEvent.type(within(dialog).getByLabelText('Premise'), 'He flees north.')
    expect(within(dialog).getByLabelText('Branch from')).toHaveValue('b1')
    await userEvent.click(within(dialog).getByRole('tab', { name: 'Absolute' }))
    await userEvent.type(within(dialog).getByRole('textbox', { name: 'Moment (seconds)' }), '250')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Create branch' }))
    await waitFor(() => {
      expect(requests.branches).toHaveLength(1)
    })
    expect(requests.branches[0]).toMatchObject({
      parent_timeline_id: 'b1',
      name: 'Exile',
      summary: 'He flees north.',
      branch_point: { anchor: { kind: 'absolute', t: '250' } },
    })
    await waitFor(() => {
      expect(router.state.location.search).toMatchObject({ tl: 'b2' })
    }, WAIT)
  })

  it('offers readers switching only', async () => {
    world()
    await renderApp('/v/v1/e/crown', moduleDefinitions, { readOnly: true })
    await userEvent.click(await screen.findByRole('button', { name: 'Timeline: Prime' }, WAIT))
    expect(await screen.findByRole('menuitemradio', { name: /Survives/ })).toBeInTheDocument()
    expect(screen.queryByRole('menuitem', { name: 'New branch…' })).toBeNull()
  })
})

describe('events in a branch', () => {
  it('keeps the shared past read-only', async () => {
    world()
    await render('/v/v1/e/ev-cor?tl=b1')
    const found = await status()
    expect(within(found).getByText('Inherited from Prime')).toBeInTheDocument()
    expect(within(found).getByText('Shared past')).toBeInTheDocument()
    expect(within(found).getByText(/ended before Survives branched off/)).toBeInTheDocument()
    expect(within(found).queryByRole('button', { name: /Edit in this timeline/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /Edit time/ })).toBeNull()
  })

  it('edits a spanning event in this timeline (an override of its end)', async () => {
    const requests = world()
    await render('/v/v1/e/ev-reign?tl=b1')
    const found = await status()
    expect(within(found).getByText('Inherited from Prime')).toBeInTheDocument()
    expect(within(found).queryByText('Shared past')).toBeNull()
    expect(screen.queryByRole('button', { name: /Edit time/ })).toBeNull()
    await userEvent.click(within(found).getByRole('button', { name: /Edit in this timeline/ }))
    const dialog = await screen.findByRole('dialog', { name: 'Edit Reign in this timeline' })
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save in this timeline' }))
    await waitFor(() => {
      expect(requests.overrides).toHaveLength(1)
    })
    expect(requests.overrides[0]).toMatchObject({
      record_type: 'event',
      root_id: 'ev-reign',
      timeline_id: 'b1',
      changes: { end: { kind: 'time_point' } },
    })
  })

  it('shows and reverts the branch’s override', async () => {
    const requests = world({
      overridden: [
        {
          record_type: 'event',
          id: 'ov-reign',
          root_id: 'row-reign',
          entity_id: 'ev-reign',
          name: 'Reign',
          detail: null,
          start_t: '100',
          end_t: '250',
          before: { end_t: '300' },
          after: { end_t: '250' },
        },
      ],
    })
    await render('/v/v1/e/ev-reign?tl=b1')
    const found = await status()
    expect(within(found).getByText('Changed in Survives')).toBeInTheDocument()
    expect(within(found).getByText(/ends t = 250 s instead of t = 300 s/)).toBeInTheDocument()
    await userEvent.click(within(found).getByRole('button', { name: /Revert/ }))
    await waitFor(() => {
      expect(requests.reverts).toEqual(['event/ov-reign'])
    })
  })

  it('edits the branch’s own events as usual, and nothing changes in the prime', async () => {
    world()
    await render('/v/v1/e/ev-rescue?tl=b1')
    expect(await screen.findByRole('button', { name: /Edit time/ }, WAIT)).toBeInTheDocument()
    expect(screen.queryByTestId('event-branch-status')).toBeNull()
    expect(await screen.findByText('Only in Survives')).toBeInTheDocument()
  })

  it('edits events normally in the prime timeline', async () => {
    world()
    await render('/v/v1/e/ev-cor')
    expect(await screen.findByRole('button', { name: /Edit time/ }, WAIT)).toBeInTheDocument()
    expect(screen.queryByTestId('event-branch-status')).toBeNull()
  })

  it('branches “what if” at an event, anchored to it', async () => {
    const requests = world()
    await render('/v/v1/e/ev-reign')
    await userEvent.click(await screen.findByRole('button', { name: /What if…/ }, WAIT))
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Branch at its end…' }))
    const dialog = await screen.findByRole('dialog', { name: 'New branch' })
    expect(within(dialog).getByLabelText('Name')).toHaveValue('What if Reign…')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Create branch' }))
    await waitFor(() => {
      expect(requests.branches).toHaveLength(1)
    })
    expect(requests.branches[0]).toMatchObject({
      parent_timeline_id: 'd1-prime',
      branch_point: { anchor: { kind: 'relative', ref: { id: 'ev-reign', slot: 'end' } } },
    })
  })
})

describe('facts and links in a branch', () => {
  it('badges inherited values and edits spanning ones in this timeline', async () => {
    const requests = world()
    await render('/v/v1/e/crown?tl=b1')
    const lifespan = await screen.findByRole('region', { name: 'Lifespan' }, WAIT)
    const values = await within(lifespan).findAllByRole('listitem', { name: 'Value over time' })
    expect(values).toHaveLength(2)
    const [span, past] = values as [HTMLElement, HTMLElement]
    expect(within(span).getByText('Inherited from Prime')).toBeInTheDocument()
    expect(within(past).getByText('Shared past')).toBeInTheDocument()
    // Neither is edited or deleted directly in the branch; the shared past not at all.
    expect(within(lifespan).queryByRole('button', { name: 'Delete this value' })).toBeNull()
    expect(within(past).queryByRole('button', { name: /Edit in this timeline/ })).toBeNull()
    await userEvent.click(within(span).getByRole('button', { name: /Edit in this timeline/ }))
    const form = await within(lifespan).findByRole('form', { name: 'Edit in this timeline' })
    await userEvent.click(within(form).getByRole('button', { name: 'Save in this timeline' }))
    await waitFor(() => {
      expect(requests.overrides).toHaveLength(1)
    })
    expect(requests.overrides[0]).toMatchObject({
      record_type: 'fact',
      root_id: 'f-life',
      timeline_id: 'b1',
      changes: { valid_to: { anchor: { t: '300' } } },
    })
    expect(requests.overrides[0]?.changes).not.toHaveProperty('value')
  })

  it('reverts a fact override and edits it again against its root', async () => {
    const requests = world({
      facts: [
        { id: 'f-ov', entity_id: 'crown', field_key: 'core.exists', valid_from_t: '50',
          valid_to_t: '230', timeline_id: 'b1', overrides_id: 'f-life' },
      ], // prettier-ignore
    })
    await render('/v/v1/e/crown?tl=b1')
    const lifespan = await screen.findByRole('region', { name: 'Lifespan' }, WAIT)
    const value = await within(lifespan).findByRole('listitem', { name: 'Value over time' })
    expect(within(value).getByText('Changed in Survives')).toBeInTheDocument()
    await userEvent.click(within(value).getByRole('button', { name: /Edit in this timeline/ }))
    const form = await within(lifespan).findByRole('form', { name: 'Edit in this timeline' })
    await userEvent.click(within(form).getByRole('button', { name: 'Save in this timeline' }))
    await waitFor(() => {
      expect(requests.overrides[0]).toMatchObject({ record_type: 'fact', root_id: 'f-life' })
    })
    await userEvent.click(
      await within(lifespan).findByRole('button', { name: 'Revert to the inherited value' }, WAIT),
    )
    await waitFor(() => {
      expect(requests.reverts).toEqual(['fact/f-ov'])
    })
  })

  it('badges inherited links, keeps the shared past read-only and overrides spanning ones', async () => {
    const requests = world()
    await render('/v/v1/e/crown?tl=b1&at=all')
    const relations = await screen.findByRole('region', { name: 'Relations' }, WAIT)
    const past = (await within(relations).findByRole('link', { name: 'Coronation' })).closest('li')
    const span = within(relations).getByRole('link', { name: 'Reign' }).closest('li')
    if (past === null || span === null) throw new Error('links')
    expect(within(past).getByText('Shared past')).toBeInTheDocument()
    expect(within(past).queryByRole('button')).toBeNull()
    expect(within(span).getByText('Inherited from Prime')).toBeInTheDocument()
    await userEvent.click(
      within(span).getByRole('button', { name: 'Edit the link to Reign in this timeline' }),
    )
    const dialog = await screen.findByRole('dialog', { name: /Edit the link to Reign/ })
    await userEvent.type(within(dialog).getByLabelText('Role'), 'usurper')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save in this timeline' }))
    await waitFor(() => {
      expect(requests.overrides).toHaveLength(1)
    })
    expect(requests.overrides[0]).toMatchObject({
      record_type: 'link',
      root_id: 'l-span',
      timeline_id: 'b1',
      changes: { role: 'usurper', valid_to: null },
    })
  })
})

describe('with the branches module off', () => {
  it('offers the prime timeline only and no branching', async () => {
    world({ modules: [] })
    await render('/v/v1/e/ev-reign')
    expect(await screen.findByRole('button', { name: /Edit time/ }, WAIT)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Timeline:/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /What if…/ })).toBeNull()
  })
})

describe('compare mode', () => {
  const windowItem = (id: string, name: string, start: number, end: number) => ({
    entity_id: id,
    row_id: `row-${id}`,
    name,
    visibility: 'public',
    parent_id: null,
    has_children: false,
    start_t: String(start),
    end_t: String(end),
    start_precision: 'base',
    start_approximate: false,
    end_kind: 'time_point',
    end_precision: 'base',
    end_approximate: false,
    importance: 3,
    category: null,
    time_status: 'ok',
    occurrence_key: null,
    series_id: null,
    occurrence_state: null,
  })

  it('shows another timeline’s lanes, where the branch diverges and what differs', async () => {
    world({
      created: [
        { record_type: 'event', id: 'row-rescue', root_id: null, entity_id: 'ev-rescue',
          name: 'Rescue', detail: null, start_t: '210', end_t: '220' },
      ],
      overridden: [
        { record_type: 'event', id: 'ov-reign', root_id: 'row-reign', entity_id: 'ev-reign',
          name: 'Reign', detail: null, start_t: '100', end_t: '250',
          before: { end_t: '300' }, after: { end_t: '250' } },
      ],
    }) // prettier-ignore
    server.use(
      http.get('*/api/v1/vaults/v1/timelines/:id/window', ({ params }) =>
        HttpResponse.json({
          items:
            params.id === 'b1'
              ? [
                  windowItem('ev-reign', 'Reign', 100, 250),
                  windowItem('ev-rescue', 'Rescue', 210, 220),
                ]
              : [windowItem('ev-reign', 'Reign', 100, 300)],
          buckets: [],
          series_bands: [],
          total: 0,
          culled: 0,
        }),
      ),
    )
    await render('/v/v1/d/d1/timeline?tl=b1&from=0&to=1000')
    const timeline = await screen.findByRole('application', { name: 'Timeline' }, WAIT)
    expect(screen.queryByTestId('compare-group')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Compare timelines' }))
    await userEvent.click(await screen.findByRole('menuitemcheckbox', { name: 'Prime' }))
    await userEvent.keyboard('{Escape}')
    const prime = await within(timeline).findByRole('region', { name: 'Compared: Prime' }, WAIT)
    // The prime's Reign is as it was; the branch's own and changed events are outlined.
    expect(within(prime).getByRole('button', { name: 'Reign' })).not.toHaveAttribute('data-diff')
    await waitFor(() => {
      expect(
        within(timeline)
          .getAllByRole('button', { name: 'Rescue' })
          .some((item) => item.hasAttribute('data-diff')),
      ).toBe(true)
    })
    expect(screen.getByTestId('divergence-marker')).toHaveAttribute('data-timeline', 'b1')
    expect(within(timeline).getByText('Survives (viewed)')).toBeInTheDocument()
    // Stopping the comparison removes its lanes.
    await userEvent.click(within(prime).getByRole('button', { name: 'Stop comparing Prime' }))
    await waitFor(() => {
      expect(screen.queryByTestId('compare-group')).toBeNull()
    })
  })
})

describe('timeline pages and notes', () => {
  it('shows a branch’s lineage, branch point, differences and children', async () => {
    world({
      created: [
        { record_type: 'event', id: 'row-rescue', root_id: null, entity_id: 'ev-rescue',
          name: 'Rescue', detail: null, start_t: '210', end_t: '220' },
      ],
      overridden: [
        { record_type: 'fact', id: 'f-ov', root_id: 'f-life', entity_id: 'crown', name: 'Crown',
          detail: 'core.exists', start_t: '50', end_t: '230',
          before: { valid_to_t: '300' }, after: { valid_to_t: '230' } },
      ],
    }) // prettier-ignore
    const { router } = await render('/v/v1/e/b1')
    const panel = await screen.findByRole('region', { name: 'Timeline' }, WAIT)
    const lineage = await within(panel).findByRole('navigation', { name: 'Lineage' }, WAIT)
    expect(within(lineage).getByRole('link', { name: 'Prime' })).toBeInTheDocument()
    expect(within(lineage).getByText('Survives')).toHaveAttribute('aria-current', 'page')
    expect(await within(panel).findByText(/1 created · 1 changed · 0 carried over/)).toBeVisible()
    const created = within(panel).getByRole('region', { name: 'Created in this branch' })
    expect(within(created).getByRole('link', { name: 'Rescue' })).toBeInTheDocument()
    const changed = within(panel).getByRole('region', { name: 'Changed in this branch' })
    expect(within(changed).getByText('changed: valid_to_t')).toBeInTheDocument()
    expect(within(panel).getByText('None')).toBeInTheDocument() // no child branches
    await userEvent.click(within(panel).getByRole('button', { name: /View this timeline/ }))
    await waitFor(() => {
      expect(router.state.location.search).toMatchObject({ tl: 'b1' })
    })
  })

  it('lists a prime timeline’s branches', async () => {
    world()
    await render('/v/v1/e/d1-prime')
    const panel = await screen.findByRole('region', { name: 'Timeline' }, WAIT)
    const children = await within(panel).findByRole('list', { name: 'Child branches' })
    expect(within(children).getByRole('link', { name: 'Survives' })).toBeInTheDocument()
    expect(within(panel).queryByText('Branch point')).toBeNull()
  })

  it('writes an entity’s notes in the viewed branch', async () => {
    const requests = world()
    await render('/v/v1/e/crown?tl=b1')
    const notes = await screen.findByRole('region', { name: 'Notes in this timeline' }, WAIT)
    const textbox = await within(notes).findByRole(
      'textbox',
      { name: 'Notes in Survives' },
      { timeout: 4000 },
    )
    const editor = (textbox as HTMLElement & { editor: Editor }).editor
    act(() => {
      editor.chain().focus('end').insertContent('He became a pirate.').run()
    })
    await waitFor(
      () => {
        expect(requests.notes).toHaveLength(1)
      },
      { timeout: 4000 },
    )
    expect(requests.notes[0]).toMatchObject({ revision: 0, body: { type: 'doc' } })
    act(() => {
      editor.chain().focus('end').insertContent(' Then a king.').run()
    })
    await waitFor(
      () => {
        expect(requests.notes).toHaveLength(2)
      },
      { timeout: 4000 },
    )
    // Each save goes from the revision the last one returned.
    expect(requests.notes[1]).toMatchObject({ revision: 1 })
  })

  it('shows readers the note, and no notes outside branches', async () => {
    world({
      note: {
        body: { type: 'doc', content: [{ type: 'paragraph',
          content: [{ type: 'text', text: 'He became a pirate.' }] }] },
        revision: 1,
      },
    }) // prettier-ignore
    await renderApp('/v/v1/e/crown?tl=b1', moduleDefinitions, { readOnly: true })
    const notes = await screen.findByRole('region', { name: 'Notes in this timeline' }, WAIT)
    expect(await within(notes).findByText('He became a pirate.')).toBeInTheDocument()
    expect(within(notes).queryByRole('textbox')).toBeNull()
  })

  it('hides the notes in the prime timeline', async () => {
    world()
    await render('/v/v1/e/crown')
    await screen.findByRole('region', { name: 'Lifespan' }, WAIT)
    expect(screen.queryByRole('region', { name: 'Notes in this timeline' })).toBeNull()
  })
})

describe('branches pages in reader mode', () => {
  it.each(['/v/v1/e/crown?tl=b1', '/v/v1/e/b1', '/v/v1/d/d1/timeline?tl=b1&from=0&to=1000'])(
    '%s offers no editing',
    async (path) => {
      world()
      await renderApp(path, undefined, { readOnly: true })
      await settled()
      expectNoEditing()
    },
  )
})
