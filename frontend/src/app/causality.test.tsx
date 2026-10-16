import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { layoutCausality, layoutEdges } from '@/core/events/causality/layout'
import type { CausalityGraph } from '@/data'
import { AXE_TIMEOUT, expectAccessible } from '@/test/axe'
import { dimensionRow } from '@/test/calendars'
import { CAPS, defaultRows, kind, KINDS, row, serveVault } from '@/test/fake-vault'
import { server } from '@/test/msw'
import { expectNoEditing, settled } from '@/test/reader'
import { renderApp } from '@/test/render-app'

/** The first layout loads ELK, which can take a while under a loaded test run. */
const LAID_OUT = { timeout: 10_000 }

const EVENT_KIND = kind('event', 'Event', {
  allowed_parents: ['event'],
  capabilities: { ...CAPS, is_time_bound: true, has_existence: false },
})

/** Spark (1) → Riot (5) → War (10) → Famine (20) → Riot (a cycle); War → Peace (50). */
const EVENTS: [string, string, number][] = [
  ['spark', 'Spark', 1],
  ['riot', 'Riot', 5],
  ['war', 'War', 10],
  ['famine', 'Famine', 20],
  ['peace', 'Peace', 50],
]
const LINKS: [string, string, string | null][] = [
  ['spark', 'riot', 'a spark'],
  ['riot', 'war', null],
  ['war', 'famine', null],
  ['famine', 'riot', null],
  ['war', 'peace', null],
]

function wire(focus: string, depth: number) {
  // Breadth-first from the focus, like the server.
  const distance = new Map([[focus, 0]])
  let frontier = [focus]
  for (let d = 1; d <= depth; d++) {
    const next: string[] = []
    for (const [source, target] of LINKS) {
      for (const [from, to] of [
        [source, target],
        [target, source],
      ] as const) {
        if (frontier.includes(from) && !distance.has(to)) {
          distance.set(to, d)
          next.push(to)
        }
      }
    }
    frontier = next
  }
  return {
    focus,
    nodes: EVENTS.filter(([id]) => distance.has(id)).map(([id, name, t]) => ({
      id,
      name,
      visibility: 'public',
      start_t: String(t),
      end_t: String(t),
      time_status: 'ok',
      importance: 3,
      category: null,
      display: { calendar_id: 'absolute', start: `${t} s`, end: `${t} s` },
      distance: distance.get(id) ?? 0,
    })),
    edges: LINKS.filter(([s, t]) => distance.has(s) && distance.has(t)).map(([s, t, d]) => ({
      id: `${s}-${t}`,
      source_id: s,
      target_id: t,
      description: d,
    })),
    truncated: false,
  }
}

function world() {
  serveVault({
    kinds: [...KINDS, EVENT_KIND],
    rows: [
      ...defaultRows().filter((entity) => entity.id !== 'd1'),
      dimensionRow('d1', 'Aetheria', null),
      ...EVENTS.map(([id, name]) => row(id, 'event', name, { dimension_id: 'd1' })),
      row('lonely', 'event', 'Lonely', { dimension_id: 'd1' }),
    ],
  })
  const depths: number[] = []
  server.use(
    http.get('*/api/v1/vaults/v1/timelines/d1-prime/causality', ({ request }) => {
      const params = new URL(request.url).searchParams
      const event = params.get('event') ?? ''
      const depth = Number(params.get('depth') ?? '2')
      depths.push(depth)
      if (event === 'lonely') return HttpResponse.json({ ...wire('spark', 0), focus: 'lonely' })
      if (!EVENTS.some(([id]) => id === event)) {
        return HttpResponse.json(
          { type: 'about:blank', title: 'Not found', status: 404, code: 'not_found', detail: '' },
          { status: 404, headers: { 'content-type': 'application/problem+json' } },
        )
      }
      return HttpResponse.json(wire(event, depth))
    }),
  )
  return depths
}

describe('causality view', () => {
  it('draws the graph around an event on its page, opens events and lists them', async () => {
    const depths = world()
    const { router } = await renderApp('/v/v1/e/riot')
    const figure = await screen.findByRole('figure', { name: 'Causality graph' })
    // Depth 1 on event pages: Riot's causes and effects, the cycle included.
    await waitFor(() => {
      expect(within(figure).getAllByTestId('causality-node')).toHaveLength(4)
    }, LAID_OUT)
    expect(depths).toContain(1)
    const focus = within(figure)
      .getAllByTestId('causality-node')
      .find((node) => node.hasAttribute('data-focus'))
    expect(focus).toHaveTextContent('Riot')

    await userEvent.click(screen.getByRole('checkbox', { name: 'As a list' }))
    const items = screen.getAllByTestId('causality-item').map((item) => item.textContent)
    expect(items).toEqual([
      'Spark · 1 s · leads to Riot',
      'Riot · 5 s · caused by Spark, Famine · leads to War',
      'War · 10 s · caused by Riot · leads to Famine',
      'Famine · 20 s · caused by War · leads to Riot',
    ])
    await userEvent.click(screen.getByRole('checkbox', { name: 'As a list' }))

    const war = (await within(await screen.findByRole('figure')).findByText('War')).closest(
      '.react-flow__node',
    )
    if (!(war instanceof HTMLElement)) throw new Error('no War node')
    // A click without a press: d3-zoom's press handling needs a real window in the event.
    fireEvent.click(war)
    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/v/v1/e/war')
    })
  })

  it('has a full page with a depth control and focus buttons', async () => {
    const depths = world()
    const { router } = await renderApp('/v/v1/e/riot')
    await userEvent.click(await screen.findByRole('link', { name: 'Full view' }))
    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/v/v1/e/riot/causality')
    })
    expect(await screen.findByRole('heading', { name: 'Causality' })).toBeInTheDocument()
    const figure = await screen.findByRole('figure', { name: 'Causality graph' })
    await waitFor(() => {
      expect(within(figure).getAllByTestId('causality-node')).toHaveLength(5) // depth 2: Peace
    }, LAID_OUT)
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Depth' }), '3')
    await waitFor(() => {
      expect(depths.at(-1)).toBe(3)
    })
    fireEvent.click(within(figure).getByLabelText('Focus on Peace'))
    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/v/v1/e/peace/causality')
    })
  })

  it('says when there is nothing to draw or the event is not on the timeline', async () => {
    world()
    await renderApp('/v/v1/e/lonely')
    expect(await screen.findByText('No causes or effects on this timeline.')).toBeInTheDocument()
    expect(screen.queryByRole('figure')).not.toBeInTheDocument()
    await renderApp('/v/v1/e/lonely-elsewhere/causality')
    expect(await screen.findByText("This event isn't on this timeline.")).toBeInTheDocument()
  })
})

describe('causality layout', () => {
  const graph = wire('riot', 3) as unknown as CausalityGraph
  const typed = {
    ...graph,
    nodes: graph.nodes.map((node) => ({
      ...node,
      start_t: BigInt(node.start_t as unknown as string),
    })),
  } as CausalityGraph

  it('lays edges out from the earlier event to the later one', () => {
    const edges = layoutEdges(typed)
    expect(edges.find((edge) => edge.id === 'famine-riot')).toMatchObject({
      sources: ['riot'],
      targets: ['famine'],
    })
    expect(edges.find((edge) => edge.id === 'riot-war')).toMatchObject({
      sources: ['riot'],
      targets: ['war'],
    })
  })

  it('places a cyclic graph left to right in time', async () => {
    const positions = await layoutCausality(typed)
    const x = (id: string) => positions.get(id)?.x ?? Number.NaN
    expect(x('spark')).toBeLessThan(x('riot'))
    expect(x('riot')).toBeLessThan(x('war'))
    expect(x('war')).toBeLessThan(x('famine'))
    expect(x('war')).toBeLessThan(x('peace'))
  })
})

describe('sidebar events', () => {
  it('lists the timeline’s top-level events and expands sub-events lazily', async () => {
    world()
    const parents: (string | null)[] = []
    server.use(
      http.get('*/api/v1/vaults/v1/timelines/d1-prime/event-tree', ({ request }) => {
        const parent = new URL(request.url).searchParams.get('parent')
        parents.push(parent)
        const node = (id: string, name: string, start: string, children = false) => ({
          id,
          name,
          visibility: 'public',
          parent_id: parent,
          start_t: '1',
          end_t: '1',
          time_status: 'ok',
          importance: 3,
          category: null,
          display: { calendar_id: 'absolute', start, end: start },
          has_children: children,
          participants: 0,
        })
        const items =
          parent === null
            ? [node('war', 'War', '10 s', true), node('peace', 'Peace', '50 s')]
            : [node('famine', 'Famine', '20 s')]
        return HttpResponse.json({ items, next_cursor: null })
      }),
    )
    const { router } = await renderApp('/v/v1')
    const section = await screen.findByRole('region', { name: 'Events' })
    expect(await within(section).findByRole('link', { name: /^War/ })).toBeInTheDocument()
    expect(parents).toEqual([null])
    await userEvent.click(within(section).getByRole('button', { name: 'Expand War' }))
    expect(await within(section).findByRole('link', { name: /^Famine/ })).toBeInTheDocument()
    expect(parents).toEqual([null, 'war'])

    await userEvent.click(within(section).getByRole('link', { name: 'Event outline' }))
    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/v/v1/d/d1/events')
    })
    // Collapsing the section is remembered.
    await userEvent.click(within(section).getByRole('button', { name: 'Events' }))
    expect(within(section).queryByRole('link', { name: /^War/ })).not.toBeInTheDocument()
    expect(localStorage.getItem('lore.sidebar.collapsed')).toContain(':events')
  })
})

describe('causality pages in reader mode', () => {
  it.each(['/v/v1/e/riot', '/v/v1/e/riot/causality'])(
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

describe('causality pages for the author', () => {
  it.each(['/v/v1/e/riot', '/v/v1/e/riot/causality'])(
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
