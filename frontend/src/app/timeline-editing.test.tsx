import { fromFields } from '@lore/chronology'
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { compiledCalendar } from '@/core/time'
import { calendarRow, dimensionRow, presetCalendar, testDimension } from '@/test/calendars'
import { CAPS, defaultRows, kind, KINDS, row, serveVault } from '@/test/fake-vault'
import { server } from '@/test/msw'
import { renderApp } from '@/test/render-app'

const dimension = { ...testDimension('c-greg'), duration: 10n ** 13n }
const compiled = compiledCalendar(presetCalendar('c-greg', 'gregorian'), dimension)
if (compiled === null) throw new Error('gregorian')
const CALENDAR = compiled
const at = (year: number) => fromFields(CALENDAR, { year: String(year) }, 'year')
const LOADED = { timeout: 5000 }

const EVENT_KIND = kind('event', 'Event', {
  allowed_parents: ['event'],
  capabilities: { ...CAPS, is_time_bound: true, has_existence: false },
})

const yearPoint = (year: number) => ({
  anchor: { kind: 'calendar', calendar_id: 'c-greg', fields: { year: String(year) } },
  precision: 'year',
})

function item(id: string, name: string, extra: Record<string, unknown> = {}) {
  return {
    entity_id: id,
    row_id: `row-${id}`,
    name,
    visibility: 'public',
    parent_id: null,
    has_children: false,
    start_t: at(2000).toString(),
    end_t: at(2010).toString(),
    start_precision: 'year',
    start_approximate: false,
    end_kind: 'time_point',
    end_precision: 'year',
    end_approximate: false,
    importance: 3,
    category: null,
    time_status: 'ok',
    occurrence_key: null,
    series_id: null,
    occurrence_state: null,
    ...extra,
  }
}

/**
 * The Long War (2000–2010, typed years, with a sub-event), Aftermath (relative to the war),
 * Feast (a festival). Returns the writes and the window requests' parameters.
 */
function world() {
  const writes = serveVault({
    kinds: [...KINDS, kind('calendar', 'Calendar'), EVENT_KIND],
    rows: [
      ...defaultRows().filter((entity) => entity.id !== 'd1'),
      dimensionRow('d1', 'Aetheria', 'c-greg', { duration: 10n ** 13n }),
      calendarRow('c-greg', 'Gregorian', 'gregorian'),
      row('war', 'event', 'The Long War', {
        dimension_id: 'd1',
        ext: {
          start: yearPoint(2000),
          end: { kind: 'time_point', time_point: yearPoint(2010) },
          timeline_id: 'd1-prime',
          importance: 5,
          category: 'war',
        },
      }),
      row('battle', 'event', 'First Battle', { dimension_id: 'd1', parent_id: 'war' }),
      row('after', 'event', 'Aftermath', {
        dimension_id: 'd1',
        ext: {
          start: {
            anchor: {
              kind: 'relative',
              ref: { type: 'event', id: 'war', slot: 'end' },
              offset: { kind: 'base', units: '0' },
            },
            precision: 'year',
          },
          end: { kind: 'instant' },
          timeline_id: 'd1-prime',
        },
      }),
      row('feast', 'event', 'Feast', { dimension_id: 'd1' }),
    ],
  })
  const requests: URLSearchParams[] = []
  server.use(
    http.post('*/api/v1/vaults/v1/time/resolve', async ({ request }) => {
      const body = (await request.json()) as { items: unknown[] }
      const ok = {
        t: '0',
        status: 'ok',
        extent: { lo: '0', hi: '0' },
        precision: 'base',
        approximate: false,
        display: 'resolved',
        error: null,
        default_precision: null,
      }
      return HttpResponse.json({
        calendar_id: 'c-greg',
        items: body.items.map(() => ({ start: ok, end: ok })),
      })
    }),
    http.get('*/api/v1/vaults/v1/timelines/:id/window', ({ request }) => {
      const params = new URL(request.url).searchParams
      requests.push(params)
      const parent = params.get('parent')
      const items =
        parent === 'war'
          ? [
              item('battle', 'First Battle', {
                parent_id: 'war',
                start_t: at(2002).toString(),
                end_t: at(2003).toString(),
              }),
            ]
          : [
              item('war', 'The Long War', { has_children: true, importance: 5, category: 'war' }),
              item('battle', 'First Battle', {
                parent_id: 'war',
                start_t: at(2002).toString(),
                end_t: at(2003).toString(),
              }),
              item('after', 'Aftermath', {
                start_t: at(2010).toString(),
                end_t: at(2010).toString(),
                end_kind: 'instant',
                end_precision: null,
              }),
              item('feast', 'Feast', {
                start_t: at(2005).toString(),
                end_t: at(2006).toString(),
                category: 'feast',
                importance: 2,
              }),
            ]
      return HttpResponse.json({
        items,
        buckets: [],
        series_bands: [],
        total: items.length,
        culled: 0,
      })
    }),
  )
  return { writes, requests }
}

const VIEW = `/v/v1/d/d1/timeline?from=${at(1998)}&to=${at(2014)}`
/** Pixels per year in that view (960 px for 16 years). */
const YEAR_PX = 60

function drag(element: HTMLElement, from: number, dx: number) {
  fireEvent.pointerDown(element, { clientX: from, button: 0, pointerId: 1 })
  act(() => {
    window.dispatchEvent(new MouseEvent('pointermove', { clientX: from + dx / 2 }))
    window.dispatchEvent(new MouseEvent('pointermove', { clientX: from + dx }))
    window.dispatchEvent(new MouseEvent('pointerup', { clientX: from + dx }))
  })
}

const patches = (writes: { method: string; path: string; body: unknown }[]) =>
  writes.filter((write) => write.method === 'PATCH') as {
    path: string
    body: { ext: { start: { anchor: { fields: Record<string, string> } }; end: unknown } }
  }[]

describe('timeline editing', () => {
  it('drags an event to move it, typed in its calendar, snapped to the axis unit', async () => {
    const { writes } = world()
    await renderApp(VIEW)
    const war = await screen.findByRole('button', { name: 'The Long War' }, LOADED)
    drag(war, 300, YEAR_PX)
    await waitFor(() => {
      expect(patches(writes)).toHaveLength(1)
    })
    const [patch] = patches(writes)
    expect(patch?.path).toBe('/entities/war')
    expect(patch?.body.ext.start.anchor.fields).toEqual({ year: '2001' })
    expect(patch?.body.ext.end).toEqual({ kind: 'time_point', time_point: yearPoint(2011) })
    expect(await screen.findByText('Moved The Long War')).toBeInTheDocument()
  })

  it('drags an end edge, leaving the start', async () => {
    const { writes } = world()
    await renderApp(VIEW)
    const war = await screen.findByRole('button', { name: 'The Long War' }, LOADED)
    war.getBoundingClientRect = () => new DOMRect(100, 0, 600, 18)
    drag(war, 698, 2 * YEAR_PX)
    await waitFor(() => {
      expect(patches(writes)).toHaveLength(1)
    })
    const [patch] = patches(writes)
    expect(patch?.body.ext.start.anchor.fields).toEqual({ year: '2000' })
    expect(patch?.body.ext.end).toEqual({ kind: 'time_point', time_point: yearPoint(2012) })
  })

  it('locks events with relative times: no drag, a lock and "Edit offset"', async () => {
    const { writes } = world()
    await renderApp(VIEW)
    const after = await screen.findByRole('button', { name: 'Aftermath' }, LOADED)
    drag(after, 600, YEAR_PX)
    expect(
      (await screen.findAllByText(/relative to another record: edit the offset/i)).at(-1),
    ).toBeInTheDocument()
    expect(patches(writes)).toHaveLength(0)

    await userEvent.click(after)
    const preview = await screen.findByRole('complementary', { name: 'Selected event' })
    expect(await within(preview).findByRole('button', { name: 'Edit offset' })).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Aftermath' })).toHaveAttribute('data-locked')
    })
    // A screen reader hears the selection.
    expect(screen.getByTestId('timeline-announcement')).toHaveTextContent(
      /^Aftermath, .+, importance 3$/,
    )
  })

  it('creates an event where empty space is double-clicked, at the axis unit', async () => {
    const { writes } = world()
    await renderApp(VIEW)
    const lanes = await screen.findByTestId('timeline-lanes')
    await screen.findByRole('button', { name: 'The Long War' }, LOADED)
    fireEvent.doubleClick(lanes, { clientX: 7 * YEAR_PX + 10 })
    const dialog = await screen.findByRole('dialog', { name: 'New event' })
    await userEvent.type(within(dialog).getByRole('textbox', { name: 'Name' }), 'Treaty')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Create event' }))
    await waitFor(() => {
      expect(writes.some((write) => write.method === 'POST')).toBe(true)
    })
    const post = writes.find((write) => write.method === 'POST')?.body as {
      ext: {
        start: { anchor: { kind: string; fields: Record<string, string> } }
        timeline_id: string
      }
    }
    expect(post.ext.start.anchor).toMatchObject({ kind: 'calendar', calendar_id: 'c-greg' })
    expect(post.ext.start.anchor.fields.year).toBe('2005')
    expect(post.ext.timeline_id).toBe('d1-prime')
  })
})

describe('timeline hierarchy, filters and grouping', () => {
  it('expands sub-events inline and drills in with a breadcrumb', async () => {
    const { requests } = world()
    const { router } = await renderApp(VIEW)
    const war = await screen.findByRole('button', { name: 'The Long War' }, LOADED)
    fireEvent.contextMenu(war)
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Expand its sub-events' }))
    const group = await screen.findByRole('region', { name: 'Sub-events of The Long War' })
    expect(await within(group).findByRole('button', { name: 'First Battle' })).toBeInTheDocument()
    expect(requests.some((params) => params.get('parent') === 'war')).toBe(true)
    // The sub-event left the main lanes for its group.
    expect(screen.getAllByRole('button', { name: 'First Battle' })).toHaveLength(1)
    await userEvent.click(within(group).getByRole('button', { name: 'Collapse The Long War' }))
    expect(screen.queryByRole('region', { name: 'Sub-events of The Long War' })).toBeNull()

    fireEvent.contextMenu(screen.getByRole('button', { name: 'The Long War' }))
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Drill in' }))
    await waitFor(() => {
      expect((router.state.location.search as { in?: string }).in).toBe('war')
    })
    const crumbs = await screen.findByRole('navigation', { name: 'Drilled into' })
    expect(await within(crumbs).findByText('The Long War')).toBeInTheDocument()
    const [from, to] = [
      BigInt((router.state.location.search as { from: string }).from),
      BigInt((router.state.location.search as { to: string }).to),
    ]
    expect(from < at(2000) && to > at(2010) && to - from < at(2012) - at(1998)).toBe(true)
    await waitFor(() => {
      expect(requests.at(-1)?.get('parent')).toBe('war')
    })
    await userEvent.click(within(crumbs).getByRole('button', { name: 'All events' }))
    await waitFor(() => {
      expect((router.state.location.search as { in?: string }).in).toBeUndefined()
    })
  })

  it('filters the window and groups the lanes', async () => {
    const { requests } = world()
    await renderApp(VIEW)
    await screen.findByRole('button', { name: 'The Long War' }, LOADED)
    await userEvent.click(screen.getByRole('button', { name: 'Filters (0)' }))
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Minimum importance' }), '4')
    await waitFor(() => {
      expect(requests.at(-1)?.get('min_importance')).toBe('4')
    })
    await userEvent.click(screen.getByRole('checkbox', { name: 'war' }))
    await waitFor(() => {
      expect(requests.at(-1)?.getAll('category')).toEqual(['war'])
    })
    await userEvent.click(screen.getByRole('checkbox', { name: 'Artifact' }))
    await waitFor(() => {
      expect(requests.at(-1)?.getAll('participant_kind')).toEqual(['artifact'])
    })
    await userEvent.click(screen.getByRole('button', { name: 'Clear the filters' }))
    await userEvent.keyboard('{Escape}')

    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Group lanes' }), 'category')
    await waitFor(() => {
      expect(
        screen.getAllByTestId('lane-group').map((group) => group.getAttribute('aria-label')),
      ).toEqual(['feast', 'war', 'Uncategorized'])
    })
    const war = screen.getByRole('region', { name: 'war' })
    expect(within(war).getByRole('button', { name: 'The Long War' })).toBeInTheDocument()
    await userEvent.selectOptions(
      screen.getByRole('combobox', { name: 'Group lanes' }),
      'importance',
    )
    await waitFor(() => {
      expect(screen.getAllByTestId('lane-group')[0]).toHaveAttribute('aria-label', '5 · Major')
    })
    expect(screen.getByRole('link', { name: 'List view' })).toHaveAttribute(
      'href',
      '/v/v1/d/d1/events',
    )
  })
})
