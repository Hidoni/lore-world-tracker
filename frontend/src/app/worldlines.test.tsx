import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'

import { expectAccessible } from '@/test/axe'
import { CAPS, defaultRows, kind, KINDS, row, serveVault } from '@/test/fake-vault'
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
const CHARACTER = kind('character', 'Character', {
  capabilities: { ...CAPS, can_have_worldline: true },
})
const point = (t: number) => ({ anchor: { kind: 'absolute', t: String(t) }, precision: 'base' })
/** A time point as the picker types it. */
const typed = (t: number) => ({ ...point(t), approximate: false })

function eventRow(id: string, name: string, start: number) {
  return row(id, 'event', name, {
    ext: {
      timeline_id: 'd1-prime',
      start: point(start),
      end: { kind: 'instant' },
      start_t: String(start),
      end_t: String(start),
      importance: 3,
      category: null,
      recurrence: null,
      time_status: 'ok',
    },
  })
}

function segment(id: string | null, seq: number, start: number, end: number, extra = {}) {
  return {
    id,
    seq,
    dimension_id: 'd1',
    timeline_id: 'd1-prime',
    start: id === null ? null : point(start),
    end: id === null ? null : point(end),
    start_t: String(start),
    end_t: String(end),
    time_status: id === null ? null : 'ok',
    rate: { num: '1', den: '1' },
    subjective_start: { num: '0', den: '1' },
    subjective_end: { num: String(end - start), den: '1' },
    departure_event_id: null,
    arrival_event_id: null,
    note: null,
    visibility: 'public',
    ...extra,
  }
}

const VEY_SEGMENTS = [segment('s1', 1, 100, 300), segment('s2', 2, 150, 200)]

interface Requests {
  puts: { segments: Record<string, unknown>[] }[]
  travels: Record<string, unknown>[]
}

/**
 * Aetheria (seconds, no calendars), Vey the traveler (100–300, then back for 150–200), Ilsa who
 * never travels, a Meeting at 170 both visits of Vey cover, and a Coronation at 250.
 */
function world(options: { modules?: string[]; implicit?: boolean } = {}) {
  const requests: Requests = { puts: [], travels: [] }
  const writes = serveVault({
    modules: options.modules ?? ['characters', 'worldlines'],
    kinds: [...KINDS, EVENT_KIND, CHARACTER, kind('timeline', 'Timeline')],
    rows: [
      ...defaultRows().filter((entity) => entity.id !== 'd1'),
      row('d1', 'dimension', 'Aetheria', {
        ext: {
          base_unit: SECOND,
          duration: '1000000',
          default_calendar_id: null,
          present: null,
          present_t: null,
          time_status: 'ok',
          prime_timeline_id: 'd1-prime',
        },
      }),
      row('d1-prime', 'timeline', 'Prime'),
      row('vey', 'character', 'Vey'),
      row('ilsa', 'character', 'Ilsa'),
      eventRow('meeting', 'Meeting', 170),
      eventRow('coronation', 'Coronation', 250),
    ],
    links: [
      { id: 'l-meet', link_type: 'core.participant', source_id: 'meeting', target_id: 'vey' },
      { id: 'l-cor', link_type: 'core.participant', source_id: 'coronation', target_id: 'vey' },
    ],
  })
  const implicit = options.implicit ?? false
  const worldline = (entity: string) => ({
    entity_id: entity,
    implicit: implicit || entity !== 'vey',
    personal_dimension_id: 'd1',
    segments: implicit || entity !== 'vey' ? [segment(null, 1, 0, 1000000)] : VEY_SEGMENTS,
  })
  const affected = {
    entities: ['vey'],
    dimensions: ['d1'],
    time_changed: true,
    search_changed: false,
  }
  server.use(
    http.get('*/api/v1/vaults/v1/timelines/:id/window', () =>
      HttpResponse.json({ items: [], buckets: [], series_bands: [], total: 0, culled: 0 }),
    ),
    http.get('*/api/v1/vaults/v1/dimensions/d1/timelines', () =>
      HttpResponse.json({
        dimension_id: 'd1',
        items: [
          {
            id: 'd1-prime',
            name: 'Prime',
            visibility: 'public',
            is_prime: true,
            parent_timeline_id: null,
            branch_point: null,
            branch_t: null,
            time_status: null,
            trashed: false,
            children: [],
          },
        ],
      }),
    ),
    http.get('*/api/v1/vaults/v1/m/worldlines/entities/:id/segments', ({ params }) =>
      HttpResponse.json(worldline(String(params.id))),
    ),
    http.put('*/api/v1/vaults/v1/m/worldlines/entities/:id/segments', async ({ request, params }) => {
      const body = (await request.json()) as { segments: Record<string, unknown>[] }
      requests.puts.push(body)
      return HttpResponse.json({ worldline: worldline(String(params.id)), affected })
    }),
    http.post('*/api/v1/vaults/v1/m/worldlines/entities/:id/time-travel', async ({ request, params }) => {
      const body = (await request.json()) as Record<string, unknown>
      requests.travels.push(body)
      return HttpResponse.json({
        worldline: worldline(String(params.id)),
        affected,
        timeline_id: 'd1-prime',
        branch_id: null,
        departure_event_id: null,
        arrival_event_id: null,
      })
    }),
    http.get('*/api/v1/vaults/v1/m/worldlines/entities/:id/presence', ({ params, request }) => {
      const t = Number(new URL(request.url).searchParams.get('t'))
      const segments = params.id === 'vey' ? VEY_SEGMENTS.filter((s) => {
        return Number(s.start_t) <= t && t <= Number(s.end_t)
      }) : []
      return HttpResponse.json({
        entity_id: params.id, dimension_id: 'd1', timeline_id: 'd1-prime', t: String(t),
        implicit: params.id !== 'vey', segments,
      })
    }),
    http.get('*/api/v1/vaults/v1/m/worldlines/entities/:id/personal-timeline', ({ params }) =>
      HttpResponse.json({
        entity_id: params.id,
        implicit: params.id !== 'vey' || implicit,
        personal_dimension_id: 'd1',
        truncated: false,
        items:
          params.id === 'vey'
            ? [
                {
                  kind: 'participation', subjective_t: { num: '70', den: '1' },
                  age: { t: '70', display: '70 seconds' }, segment_id: 's1',
                  segment_ids: ['s1', 's2'], dimension_id: 'd1', timeline_id: 'd1-prime',
                  t: '170', event_id: 'meeting', name: 'Meeting', roles: [],
                  assignment: 'ambiguous',
                },
                {
                  kind: 'participation', subjective_t: { num: '150', den: '1' },
                  age: { t: '150', display: '150 seconds' }, segment_id: 's1',
                  segment_ids: ['s1'], dimension_id: 'd1', timeline_id: 'd1-prime',
                  t: '250', event_id: 'coronation', name: 'Coronation', roles: ['guest'],
                  assignment: 'implied',
                },
                {
                  kind: 'jump', subjective_t: { num: '200', den: '1' },
                  age: { t: '200', display: '200 seconds' }, segment_id: 's1',
                  segment_ids: ['s1'], dimension_id: 'd1', timeline_id: 'd1-prime', t: '300',
                  event_id: null, name: null, roles: [], to_dimension_id: 'd1',
                  to_timeline_id: 'd1-prime', to_t: '150', arrival_event_id: null,
                },
              ]
            : [],
      }),
    ),
  ) // prettier-ignore
  return { requests, writes }
}

const render = (path: string) => renderApp(path, moduleDefinitions)

async function absolute(group: HTMLElement, t: string) {
  const tab = within(group).queryByRole('tab', { name: 'Absolute' })
  if (tab !== null) await userEvent.click(tab)
  const input = within(group).getByRole('textbox', { name: /Moment/ })
  await userEvent.clear(input)
  await userEvent.type(input, t)
}

describe('the worldline panel', () => {
  it('lists the segments and splits, reorders and removes them', async () => {
    const { requests } = world()
    await render('/v/v1/e/vey')
    const list = await screen.findByRole('list', { name: 'Worldline segments' }, WAIT)
    expect(within(list).getAllByRole('listitem')).toHaveLength(2)
    await userEvent.click(within(list).getByRole('button', { name: 'Move segment 1 down' }))
    await waitFor(() => {
      expect(requests.puts).toHaveLength(1)
    })
    expect(requests.puts[0]?.segments.map((s) => s.start)).toEqual([point(150), point(100)])
    await userEvent.click(within(list).getByRole('button', { name: 'Split segment 1' }))
    const dialog = await screen.findByRole('dialog', { name: 'Split segment 1' })
    await absolute(within(dialog).getByRole('group', { name: 'Split at' }), '200')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Split' }))
    await waitFor(() => {
      expect(requests.puts).toHaveLength(2)
    })
    expect(requests.puts[1]?.segments.map((s) => [s.start, s.end])).toEqual([
      [point(100), typed(200)],
      [typed(200), point(300)],
      [point(150), point(200)],
    ])
    await userEvent.click(within(list).getByRole('button', { name: 'Remove segment 2' }))
    await waitFor(() => {
      expect(requests.puts).toHaveLength(3)
    })
    expect(requests.puts[2]?.segments).toHaveLength(1)
  })

  it('starts a worldline and sends someone through time', async () => {
    const { requests } = world({ implicit: true })
    await render('/v/v1/e/vey')
    expect(await screen.findByText(/Lives its lifespan in order/, {}, WAIT)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Add segment' }))
    const add = await screen.findByRole('dialog', { name: 'New segment' })
    await absolute(await within(add).findByRole('group', { name: 'From' }, WAIT), '10')
    await absolute(within(add).getByRole('group', { name: 'Until' }), '20')
    await userEvent.click(within(add).getByRole('button', { name: 'Save segment' }))
    await waitFor(() => {
      expect(requests.puts).toHaveLength(1)
    })
    expect(requests.puts[0]?.segments).toEqual([
      expect.objectContaining({
        dimension_id: 'd1',
        timeline_id: 'd1-prime',
        start: typed(10),
        end: typed(20),
        rate: { num: '1', den: '1' },
      }),
    ])
    await userEvent.click(screen.getByRole('button', { name: 'Time travel…' }))
    const wizard = await screen.findByRole('dialog', { name: 'Time travel' })
    await absolute(await within(wizard).findByRole('group', { name: 'Leaves at' }, WAIT), '300')
    await userEvent.type(within(wizard).getByLabelText('Departure event name'), 'The Vanishing')
    await absolute(await within(wizard).findByRole('group', { name: 'Arrives at' }, WAIT), '150')
    await userEvent.click(within(wizard).getByRole('button', { name: 'Travel' }))
    await waitFor(() => {
      expect(requests.travels).toHaveLength(1)
    })
    expect(requests.travels[0]).toMatchObject({
      departure: { at: point(300), event_name: 'The Vanishing' },
      destination: { dimension_id: 'd1', timeline_id: 'd1-prime', arrival: point(150) },
    })
  })

  it('is not on kinds without worldlines, nor with the module off', async () => {
    world()
    await render('/v/v1/e/meeting')
    await screen.findByRole('heading', { name: 'Meeting' }, WAIT)
    expect(screen.queryByRole('button', { name: 'Time travel…' })).toBeNull()
    world({ modules: ['characters'] })
    await render('/v/v1/e/vey')
    await screen.findByRole('heading', { name: 'Vey' }, WAIT)
    await new Promise((resolve) => setTimeout(resolve, 200))
    expect(screen.queryByRole('list', { name: 'Worldline segments' })).toBeNull()
  })
})

describe('the personal timeline view', () => {
  it('shows lived time with jumps as breaks, and a list', async () => {
    world()
    await render('/v/v1/m/worldlines/entities/vey')
    const axis = await screen.findByTestId('subjective-axis', {}, WAIT)
    expect(within(axis).getAllByTestId('lived-mark')).toHaveLength(2)
    expect(within(axis).getByTestId('jump-break')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'List view' }))
    const table = screen.getByRole('table', { name: 'Personal timeline' })
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringContaining('70 seconds'),
      expect.stringContaining('as guest'),
      expect.stringContaining('Jumps'),
    ])
    expect(rows[0]).toHaveTextContent('(which visit?)')
  })
})

describe('participations', () => {
  it('ask which visit of a time traveler takes part', async () => {
    const { writes } = world()
    await render('/v/v1/e/meeting')
    const choice = await screen.findByRole('combobox', { name: 'Which visit of Vey' }, WAIT)
    expect(screen.getByText('Which visit?')).toBeInTheDocument()
    await userEvent.selectOptions(choice, 's2')
    await waitFor(() => {
      expect(writes.some((w) => w.method === 'PATCH' && w.path.endsWith('/links/l-meet'))).toBe(
        true,
      )
    })
    const patch = writes.find((w) => w.method === 'PATCH' && w.path.endsWith('/links/l-meet'))
    expect(patch?.body).toMatchObject({ data: { segment_id: 's2' } })
  })

  it('show lived ages in the life panel', async () => {
    world()
    server.use(
      http.get('*/api/v1/vaults/v1/m/characters/characters/:id/life', () =>
        HttpResponse.json({
          items: [
            {
              id: 'coronation', name: 'Coronation', start_t: '250', end_t: '250',
              display: { calendar_id: 'absolute', start: 't = 250', end: null },
              roles: ['guest'], timeline_id: 'd1-prime',
            },
          ],
          truncated: false,
        }),
      ),
    ) // prettier-ignore
    await render('/v/v1/e/vey')
    const life = await screen.findByRole('list', { name: 'Life events' }, WAIT)
    expect(await within(life).findByText('lived 150 seconds', {}, WAIT)).toBeInTheDocument()
  })
})

describe('the timeline', () => {
  it('draws the jumps of chosen entities', async () => {
    world()
    await render('/v/v1/d/d1/timeline?from=0&to=400')
    const timeline = await screen.findByRole('application', { name: 'Timeline' }, WAIT)
    await userEvent.click(await within(timeline).findByRole('button', { name: 'Jumps' }, WAIT))
    await userEvent.type(await screen.findByLabelText('Find an entity'), 'Vey')
    await userEvent.click(await screen.findByRole('button', { name: 'Vey' }, WAIT))
    await waitFor(() => {
      expect(timeline.querySelector('[data-testid="jump-arc"]')).not.toBeNull()
    })
    // The arcs as a list: the chosen entity's personal timeline.
    expect(screen.getByRole('link', { name: 'Personal timeline of Vey' })).toHaveAttribute(
      'href',
      '/v/v1/m/worldlines/entities/vey',
    )
  })
})

describe('worldlines pages in reader mode', () => {
  it.each(['/v/v1/e/vey', '/v/v1/m/worldlines/entities/vey'])(
    '%s offers no editing',
    async (path) => {
      world()
      await renderApp(path, undefined, { readOnly: true })
      await settled()
      expectNoEditing()
      await expectAccessible()
    },
  )
})

describe('worldlines pages for the author', () => {
  it.each(['/v/v1/e/vey', '/v/v1/m/worldlines/entities/vey'])('%s is accessible', async (path) => {
    world()
    await renderApp(path)
    await settled()
    await expectAccessible()
  })
})
