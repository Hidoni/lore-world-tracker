import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'

import { AXE_TIMEOUT, expectAccessible } from '@/test/axe'
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

const dimensionExt = (prime: string) => ({
  base_unit: SECOND,
  duration: '1000000',
  default_calendar_id: null,
  present: null,
  present_t: null,
  time_status: 'ok',
  prime_timeline_id: prime,
})

const point = (t: number) => ({ anchor: { kind: 'absolute', t: String(t) }, precision: 'base' })

function eventRow(id: string, name: string, start: number, dimension = 'd1') {
  return row(id, 'event', name, {
    dimension_id: dimension,
    ext: {
      timeline_id: `${dimension}-prime`,
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

/** The Portal: 100 ↔ 1000 and 200 ↔ 3000 (one second in Aetheria is twenty in the Dreamrealm). */
const PORTAL = {
  id: 'c1',
  dimension_a_id: 'd1',
  dimension_b_id: 'd2',
  name: 'The Portal',
  extrapolation: 'none',
  rate_before: null,
  rate_after: null,
  note: null,
  visibility: 'public',
  revision: 1,
  created_at: '2026-10-14T10:00:00Z',
  updated_at: '2026-10-14T10:00:00Z',
  deleted_at: null,
  points: [
    { id: 'p1', a: point(100), b: point(1000), a_t: '100', b_t: '1000', time_status: 'ok', note: null },
    { id: 'p2', a: point(200), b: point(3000), a_t: '200', b_t: '3000', time_status: 'ok', note: null },
  ],
} // prettier-ignore

function world(options: { modules?: string[]; correspondences?: unknown[] } = {}) {
  const writes: { method: string; body: Record<string, unknown> }[] = []
  const stored = [...(options.correspondences ?? [PORTAL])]
  serveVault({
    modules: options.modules ?? ['correspondences'],
    kinds: [...KINDS, EVENT_KIND, kind('timeline', 'Timeline')],
    rows: [
      ...defaultRows().filter((entity) => entity.id !== 'd1'),
      row('d1', 'dimension', 'Aetheria', { ext: dimensionExt('d1-prime') }),
      row('d2', 'dimension', 'Dreamrealm', { ext: dimensionExt('d2-prime') }),
      row('d1-prime', 'timeline', 'Prime'),
      row('d2-prime', 'timeline', 'Dream prime', { dimension_id: 'd2' }),
      eventRow('ev-1', 'Opening', 150),
      eventRow('ev-early', 'Before', 50),
    ],
  })
  const affected = { entities: ['d1', 'd2'], dimensions: ['d1', 'd2'], time_changed: true,
    search_changed: false } // prettier-ignore
  server.use(
    http.get('*/api/v1/vaults/v1/m/correspondences', ({ request }) => {
      const dimension = new URL(request.url).searchParams.get('dimension')
      const items = stored.filter((item) => {
        const { dimension_a_id: a, dimension_b_id: b } = item as typeof PORTAL
        return dimension === null || a === dimension || b === dimension
      })
      return HttpResponse.json({ items })
    }),
    http.post('*/api/v1/vaults/v1/m/correspondences', async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>
      writes.push({ method: 'POST', body })
      return HttpResponse.json({ correspondence: PORTAL, affected }, { status: 201 })
    }),
    http.patch('*/api/v1/vaults/v1/m/correspondences/:id', async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>
      writes.push({ method: 'PATCH', body })
      return HttpResponse.json({ correspondence: PORTAL, affected })
    }),
    http.get('*/api/v1/vaults/v1/timelines/:id/window', ({ params }) =>
      HttpResponse.json({
        items:
          params.id === 'd2-prime'
            ? [
                {
                  entity_id: 'ev-dream',
                  row_id: 'row-dream',
                  name: 'Dream Feast',
                  visibility: 'public',
                  parent_id: null,
                  has_children: false,
                  start_t: '2000',
                  end_t: '2400',
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
                },
              ]
            : [],
        buckets: [],
        series_bands: [],
        total: 0,
        culled: 0,
      }),
    ),
  )
  return writes
}

const render = (path: string) => renderApp(path, moduleDefinitions)

async function absolute(group: HTMLElement, t: string) {
  const tab = within(group).queryByRole('tab', { name: 'Absolute' })
  if (tab !== null) await userEvent.click(tab)
  const input = within(group).getByRole('textbox', { name: /Moment/ })
  await userEvent.clear(input)
  await userEvent.type(input, t)
}

describe('the dimension overview', () => {
  it('lists the correspondences and the connected dimensions', async () => {
    world()
    await render('/v/v1/d/d1')
    const list = await screen.findByRole('list', { name: 'Correspondences' }, WAIT)
    expect(within(list).getByText('The Portal')).toBeInTheDocument()
    expect(within(list).getByRole('link', { name: 'Dreamrealm' })).toBeInTheDocument()
    expect(within(list).getByText('2 sync points')).toBeInTheDocument()
    expect(screen.getByTestId('connected-dimensions')).toBeInTheDocument()
    const connected = screen.getByRole('list', { name: 'Connected dimensions' })
    expect(within(connected).getByRole('link', { name: 'Dreamrealm' })).toHaveAttribute(
      'href',
      '/v/v1/d/d2',
    )
  })

  it('creates a correspondence, previewing and trying the mapping', async () => {
    const writes = world({ correspondences: [] })
    await render('/v/v1/d/d1')
    await userEvent.click(await screen.findByRole('button', { name: 'New correspondence' }, WAIT))
    const dialog = await screen.findByRole('dialog', { name: 'New correspondence' })
    await userEvent.type(within(dialog).getByLabelText('Name'), 'The Portal')
    expect(within(dialog).getByLabelText('Corresponds with')).toHaveValue('d2')
    const first = await within(dialog).findByRole('group', { name: 'Sync point 1' }, WAIT)
    await absolute(within(first).getByRole('group', { name: 'In Aetheria' }), '100')
    await absolute(within(first).getByRole('group', { name: 'In Dreamrealm' }), '1000')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Add sync point' }))
    const second = within(dialog).getByRole('group', { name: 'Sync point 2' })
    await absolute(within(second).getByRole('group', { name: 'In Aetheria' }), '200')
    await absolute(within(second).getByRole('group', { name: 'In Dreamrealm' }), '3000')
    // The preview: the chart, and a moment tried through the draft.
    expect(await within(dialog).findByTestId('mapping-chart')).toBeInTheDocument()
    expect(within(dialog).getAllByTestId('sync-marker')).toHaveLength(2)
    const tester = within(dialog).getByRole('region', { name: 'Conversion tester' })
    await absolute(within(tester).getByRole('group', { name: 'Moment in Aetheria' }), '150')
    expect(within(tester).getByTestId('conversion-result')).toHaveTextContent('in Dreamrealm')
    expect(within(tester).getByTestId('conversion-result')).toHaveTextContent('2,000')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save correspondence' }))
    await waitFor(() => {
      expect(writes).toHaveLength(1)
    })
    expect(writes[0]?.body).toMatchObject({
      dimension_a_id: 'd1',
      dimension_b_id: 'd2',
      name: 'The Portal',
      extrapolation: 'none',
      rate_before: null,
      rate_after: null,
      points: [
        { a: { anchor: { kind: 'absolute', t: '100' } }, b: { anchor: { kind: 'absolute', t: '1000' } } },
        { a: { anchor: { kind: 'absolute', t: '200' } }, b: { anchor: { kind: 'absolute', t: '3000' } } },
      ],
    }) // prettier-ignore
  })

  it('flags sync points that go backwards before saving', async () => {
    world({ correspondences: [] })
    await render('/v/v1/d/d1')
    await userEvent.click(await screen.findByRole('button', { name: 'New correspondence' }, WAIT))
    const dialog = await screen.findByRole('dialog', { name: 'New correspondence' })
    const first = await within(dialog).findByRole('group', { name: 'Sync point 1' }, WAIT)
    await absolute(within(first).getByRole('group', { name: 'In Aetheria' }), '100')
    await absolute(within(first).getByRole('group', { name: 'In Dreamrealm' }), '1000')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Add sync point' }))
    const second = within(dialog).getByRole('group', { name: 'Sync point 2' })
    await absolute(within(second).getByRole('group', { name: 'In Aetheria' }), '200')
    await absolute(within(second).getByRole('group', { name: 'In Dreamrealm' }), '500')
    expect(await within(dialog).findByText(/increase strictly in both/)).toBeInTheDocument()
    expect(within(dialog).queryByTestId('mapping-chart')).toBeNull()
  })

  it('sets both rates with the helper and edits an existing correspondence', async () => {
    const writes = world()
    await render('/v/v1/d/d1')
    await userEvent.click(await screen.findByRole('button', { name: 'Edit The Portal' }, WAIT))
    const dialog = await screen.findByRole('dialog', { name: 'Edit correspondence' })
    expect(within(dialog).getByLabelText('Corresponds with')).toBeDisabled()
    await userEvent.selectOptions(within(dialog).getByLabelText('Outside the sync points'), 'rate')
    // 1 base unit here = 365 base units there (the dimensions have no calendars).
    const there = within(dialog).getByRole('textbox', { name: 'Amount in Dreamrealm' })
    await userEvent.clear(there)
    await userEvent.type(there, '365')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Use for both rates' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save correspondence' }))
    await waitFor(() => {
      expect(writes).toHaveLength(1)
    })
    expect(writes[0]).toMatchObject({
      method: 'PATCH',
      body: {
        revision: 1,
        extrapolation: 'rate',
        rate_before: { num: '365', den: '1' },
        rate_after: { num: '365', den: '1' },
      },
    })
  })

  it('shows nothing of correspondences with the module off', async () => {
    world({ modules: [] })
    await render('/v/v1/d/d1')
    await screen.findByRole('heading', { name: 'Aetheria' }, WAIT)
    expect(screen.queryByRole('button', { name: 'New correspondence' })).toBeNull()
    expect(screen.queryByText('Correspondences')).toBeNull()
  })
})

describe('events', () => {
  it('show what happens concurrently in the other dimensions', async () => {
    world()
    await render('/v/v1/e/ev-1')
    const panel = await screen.findByTestId('concurrently', {}, WAIT)
    expect(within(panel).getByRole('link', { name: 'Dreamrealm' })).toBeInTheDocument()
    expect(panel).toHaveTextContent('2,000')
  })

  it('leave the section out when nothing corresponds', async () => {
    world()
    await render('/v/v1/e/ev-early')
    await screen.findByRole('heading', { name: 'Before' }, WAIT)
    // Give the correspondences time to load: the section still doesn't appear.
    await new Promise((resolve) => setTimeout(resolve, 200))
    expect(screen.queryByTestId('concurrently')).toBeNull()
    expect(screen.queryByText('Concurrently in…')).toBeNull()
  })
})

describe('the timeline', () => {
  it('maps another dimension’s events onto its axis in a lane of their own', async () => {
    world()
    await render('/v/v1/d/d1/timeline?from=0&to=400')
    const timeline = await screen.findByRole('application', { name: 'Timeline' }, WAIT)
    await userEvent.click(await screen.findByRole('button', { name: 'Add dimension lane' }, WAIT))
    await userEvent.click(await screen.findByRole('menuitemcheckbox', { name: 'Dreamrealm' }))
    await userEvent.keyboard('{Escape}')
    const lane = await within(timeline).findByRole(
      'region',
      { name: 'Dimension: Dreamrealm' },
      WAIT,
    )
    expect(
      await within(lane).findByRole('button', { name: 'Dream Feast' }, WAIT),
    ).toBeInTheDocument()
    expect(within(lane).getAllByTestId('dimension-tick').length).toBeGreaterThan(0)
    await userEvent.click(within(lane).getByRole('button', { name: 'Remove the Dreamrealm lane' }))
    await waitFor(() => {
      expect(screen.queryByTestId('dimension-lane')).toBeNull()
    })
  })
})

describe('correspondences pages in reader mode', () => {
  it.each(['/v/v1/d/d1', '/v/v1/e/ev-1', '/v/v1/d/d1/timeline?from=0&to=400'])(
    '%s offers no editing',
    async (path) => {
      world()
      await renderApp(path, undefined, { readOnly: true })
      await settled()
      expectNoEditing()
      await expectAccessible()
    },
    AXE_TIMEOUT,
  )
})

describe('correspondences pages for the author', () => {
  it.each(['/v/v1/d/d1', '/v/v1/e/ev-1', '/v/v1/d/d1/timeline?from=0&to=400'])(
    '%s is accessible',
    async (path) => {
      world()
      await renderApp(path)
      await settled()
      await expectAccessible()
    },
    AXE_TIMEOUT,
  )
})
