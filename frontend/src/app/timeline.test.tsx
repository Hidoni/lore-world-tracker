import { formatDate, fromFields, nextPhaseAt, rational, unitBounds } from '@lore/chronology'
import { fromPx, ticks, toPx, viewport } from '@lore/chronology/viewport'
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { compiledCalendar } from '@/core/time'
import { TickSnap } from '@/core/timeline/cursor-line'
import { expectAccessible } from '@/test/axe'
import { calendarRow, dimensionRow, presetCalendar, testDimension } from '@/test/calendars'
import { defaultRows, kind, KINDS, row, serveVault } from '@/test/fake-vault'
import { server } from '@/test/msw'
import { expectNoEditing, settled } from '@/test/reader'
import { renderApp } from '@/test/render-app'

const D = 10n ** 100n
/** The first window's items can take a while under a loaded test run. */
const LOADED = { timeout: 5000 }
const WIDTH = 960
const dimension = { ...testDimension('c-greg'), duration: D }
const compiled = compiledCalendar(presetCalendar('c-greg', 'gregorian'), dimension)
if (compiled === null) throw new Error('gregorian')
const CALENDAR = compiled

function world(duration = D) {
  serveVault({
    kinds: [...KINDS, kind('calendar', 'Calendar')],
    rows: [
      ...defaultRows().filter((entity) => entity.id !== 'd1'),
      dimensionRow('d1', 'Aetheria', 'c-greg', { duration }),
      calendarRow('c-greg', 'Gregorian', 'gregorian'),
    ],
  })
}

/** The viewport in the URL. */
function urlRange(router: { state: { location: { search: unknown } } }): [bigint, bigint] {
  const search = router.state.location.search as { from?: string; to?: string }
  if (search.from === undefined || search.to === undefined) throw new Error('no range in the URL')
  return [BigInt(search.from), BigInt(search.to)]
}

/** The axis' tick labels by moment, as rendered. */
function rendered(): { major: [bigint, string][]; minor: [bigint, string][] } {
  const read = (id: string) =>
    screen
      .queryAllByTestId(id)
      .map((tick): [bigint, string] => [
        BigInt(tick.getAttribute('data-t') ?? '0'),
        tick.textContent,
      ])
  return { major: read('major-tick'), minor: read('minor-tick') }
}

afterEach(() => {
  vi.useRealTimers()
})

describe('the timeline view', () => {
  it('keeps the axis labels exact while zooming across 100 orders of magnitude', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    world()
    const { router } = await renderApp('/v/v1/d/d1/timeline')
    const view = await screen.findByRole('application', { name: 'Timeline' })
    act(() => {
      vi.advanceTimersByTime(300)
    })
    await waitFor(() => {
      expect((router.state.location.search as { from?: string }).from).toBeDefined()
    })
    // The whole dimension fits.
    const [from0, to0] = urlRange(router)
    expect(from0 <= 0n && to0 >= D).toBe(true)

    let previousSpan = to0 - from0
    let checks = 0
    // Zoom in at the center ~340 times (each halves the span) down to the minimum span, checking the
    // rendered labels against the engine's ticks for the viewport in the URL every 10 steps.
    for (let step = 0; step < 34; step++) {
      for (let i = 0; i < 10; i++) fireEvent.keyDown(view, { key: '+' })
      act(() => {
        vi.advanceTimersByTime(300)
      })
      await waitFor(() => {
        const [from, to] = urlRange(router)
        expect(to - from).toBeLessThanOrEqual(previousSpan)
      })
      const [from, to] = urlRange(router)
      const v = viewport(from, to - from, WIDTH)
      const expected = ticks(CALENDAR, v)
      const shown = rendered()
      expect(shown.major).toEqual(expected.major.map((tick) => [tick.t, tick.label]))
      expect(shown.minor).toEqual(expected.minor.map((tick) => [tick.t, tick.label]))
      // Every tick is on screen, in order.
      const xs = [...shown.major, ...shown.minor].map(([t]) => toPx(v, t)).sort((a, b) => a - b)
      for (const x of xs) {
        expect(x).toBeGreaterThanOrEqual(0)
        expect(x).toBeLessThan(WIDTH)
      }
      expect(shown.major.length + shown.minor.length).toBeGreaterThan(0)
      previousSpan = to - from
      checks++
    }
    expect(checks).toBe(34)
    // Down to the narrowest span (10 s): seconds are labelled.
    expect(previousSpan).toBe(10n)
    expect(rendered().minor.some(([, label]) => label.includes(':'))).toBe(true)

    // And back out to the whole dimension.
    fireEvent.keyDown(view, { key: 'Home' })
    act(() => {
      vi.advanceTimersByTime(300)
    })
    await waitFor(() => {
      const [from, to] = urlRange(router)
      expect(to - from).toBeGreaterThanOrEqual(D)
    })
  }, 60_000)

  it('zooms with a two-finger pinch (touch)', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const year = 10n ** 12n
    world(year * 100_000n)
    const { router } = await renderApp(`/v/v1/d/d1/timeline?from=${year * 10n}&to=${year * 20n}`)
    await screen.findByRole('application', { name: 'Timeline' })
    const lanes = screen.getByTestId('timeline-lanes')
    fireEvent.pointerDown(lanes, { pointerId: 1, clientX: 100 })
    fireEvent.pointerDown(lanes, { pointerId: 2, clientX: 200 })
    // Spreading the fingers to four times their distance zooms in four times.
    fireEvent.pointerMove(lanes, { pointerId: 1, clientX: 0 })
    fireEvent.pointerMove(lanes, { pointerId: 2, clientX: 400 })
    fireEvent.pointerUp(lanes, { pointerId: 1 })
    fireEvent.pointerUp(lanes, { pointerId: 2 })
    act(() => {
      vi.advanceTimersByTime(300)
    })
    await waitFor(() => {
      const [from, to] = urlRange(router)
      expect(to - from).toBe((year * 10n) / 4n)
    })
  })

  it('pans with the keyboard and the minimap, zooms with the wheel, and goes to a date', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const year = 10n ** 12n
    world(year * 100_000n)
    const { router } = await renderApp(`/v/v1/d/d1/timeline?from=${year * 10n}&to=${year * 20n}`)
    const view = await screen.findByRole('application', { name: 'Timeline' })
    const range = () => urlRange(router)
    const settle = () => {
      act(() => {
        vi.advanceTimersByTime(300)
      })
    }
    // The URL's range is the view's.
    expect(screen.getByTestId('timeline-range').textContent).not.toBe('')
    fireEvent.keyDown(view, { key: 'ArrowRight' })
    settle()
    await waitFor(() => {
      expect(range()[0]).toBeGreaterThan(year * 10n)
    })
    const [panned] = range()
    expect(range()[1] - panned).toBe(year * 10n)

    // The wheel zooms at the cursor (here: x = 0, so the start stays).
    fireEvent.wheel(screen.getByTestId('timeline-lanes'), { deltaY: -300, clientX: 0 })
    settle()
    await waitFor(() => {
      expect(range()[1] - range()[0]).toBe(year * 5n)
    })
    expect(range()[0]).toBe(panned)

    // With "pans (Ctrl zooms)", the plain wheel pans instead.
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Wheel zooms' }), 'ctrl')
    fireEvent.wheel(screen.getByTestId('timeline-lanes'), { deltaY: 96, clientX: 0 })
    settle()
    await waitFor(() => {
      expect(range()[0]).toBeGreaterThan(panned)
    })
    expect(range()[1] - range()[0]).toBe(year * 5n)

    // G: go to a date (the year 5 of the Gregorian calendar).
    fireEvent.keyDown(view, { key: 'g' })
    const dialog = await screen.findByRole('dialog', { name: 'Go to a date' })
    await userEvent.type(within(dialog).getByRole('textbox', { name: 'year' }), '5')
    await userEvent.selectOptions(
      within(dialog).getByRole('combobox', { name: 'Precision' }),
      'year',
    )
    await userEvent.click(within(dialog).getByRole('button', { name: 'Go' }))
    settle()
    const fiveStart = fromFields(CALENDAR, { year: '5' }, 'year')
    const sixStart = fromFields(CALENDAR, { year: '6' }, 'year')
    await waitFor(() => {
      const [from, to] = range()
      expect(from).toBeLessThanOrEqual(fiveStart)
      expect(to).toBeGreaterThanOrEqual(sixStart)
      expect(to - from).toBeLessThan((sixStart - fiveStart) * 2n)
    })
    expect(
      screen
        .getAllByTestId('major-tick')
        .some((tick) => tick.textContent.includes(formatDate(CALENDAR, fiveStart, 'year'))),
    ).toBe(true)
  }, 30_000)

  it('moves the view from the minimap, keeping its span', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const total = 10n ** 15n
    world(total)
    const { router } = await renderApp(`/v/v1/d/d1/timeline?from=0&to=${10n ** 12n}`)
    const minimap = await screen.findByRole('slider', { name: 'Minimap' })
    fireEvent.pointerDown(minimap, { clientX: WIDTH / 2, pointerId: 1 })
    fireEvent.pointerUp(minimap, { pointerId: 1 })
    act(() => {
      vi.advanceTimersByTime(300)
    })
    await waitFor(() => {
      const [from, to] = urlRange(router)
      expect(to - from).toBe(10n ** 12n)
      // Centered on the middle of the dimension (to a pixel of the whole strip).
      const middle = (from + to) / 2n
      expect(middle > total / 2n - total / 500n && middle < total / 2n + total / 500n).toBe(true)
    })
  })
})

describe('event lanes', () => {
  const at = (year: number) => fromFields(CALENDAR, { year: String(year) }, 'year')

  function item(id: string, name: string, extra: Record<string, unknown>) {
    return {
      entity_id: id,
      row_id: `row-${id}`,
      name,
      visibility: 'public',
      parent_id: null,
      has_children: false,
      start_t: at(2000).toString(),
      end_t: at(2001).toString(),
      start_precision: 'day',
      start_approximate: false,
      end_kind: 'time_point',
      end_precision: 'day',
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

  /** A world whose window answers with a few events and counts its requests. */
  function eventsWorld() {
    serveVault({
      kinds: [...KINDS, kind('calendar', 'Calendar'), kind('event', 'Event')],
      rows: [
        ...defaultRows().filter((entity) => entity.id !== 'd1'),
        dimensionRow('d1', 'Aetheria', 'c-greg', { duration: 10n ** 13n }),
        calendarRow('c-greg', 'Gregorian', 'gregorian'),
        row('war', 'event', 'The Long War', { dimension_id: 'd1' }),
        row('crowning', 'event', 'Crowning', { dimension_id: 'd1' }),
      ],
    })
    const requests: URLSearchParams[] = []
    server.use(
      http.get('*/api/v1/vaults/v1/timelines/:id/window', ({ request }) => {
        const params = new URL(request.url).searchParams
        requests.push(params)
        const from = BigInt(params.get('from') ?? '0')
        const to = BigInt(params.get('to') ?? '0')
        // A band counts the occurrences in each tile: here all in the tile holding its start.
        const holdsBand = from <= at(2000) && at(2000) < to
        return HttpResponse.json({
          items: [
            item('war', 'The Long War', {
              start_t: at(2000).toString(),
              end_t: at(2010).toString(),
              start_precision: 'year',
              end_precision: 'year',
              importance: 5,
            }),
            item('crowning', 'Crowning', {
              start_t: at(2003).toString(),
              end_t: at(2003).toString(),
              end_kind: 'instant',
              start_precision: 'base',
            }),
            item('rumour', 'Rumour', {
              start_t: at(2004).toString(),
              end_t: null,
              end_kind: 'unknown',
              start_approximate: true,
            }),
          ],
          buckets:
            from <= at(2005) && at(2005) < to
              ? [{ from: at(2005).toString(), to: at(2006).toString(), starts: 7, active: 9 }]
              : [],
          series_bands: !holdsBand
            ? []
            : [
                {
                  entity_id: 'tide',
                  row_id: 'row-tide',
                  name: 'Tides',
                  visibility: 'public',
                  importance: 2,
                  category: null,
                  from: at(2000).toString(),
                  to: at(2008).toString(),
                  estimated_count: '5000',
                },
              ],
          total: 10,
          culled: 7,
        })
      }),
    )
    return requests
  }

  const lanesOf = (): Record<string, string | undefined> =>
    Object.fromEntries<string | undefined>(
      [...document.querySelectorAll<HTMLElement>('[data-item]')].map((element) => [
        element.getAttribute('aria-label') ?? '',
        /translate\([^,]+px, ([^)]+)px\)/.exec(element.style.transform)?.[1],
      ]),
    )

  it('draws events by tile, with fuzzy edges, bands and density, and keeps lanes on pan', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const requests = eventsWorld()
    await renderApp(`/v/v1/d/d1/timeline?from=${at(1998)}&to=${at(2014)}`)
    const war = await screen.findByRole('button', { name: 'The Long War' }, LOADED)
    expect(requests.length).toBeGreaterThan(0)
    // Each tile asks for at least the view's width in pixels, from tile bounds.
    for (const params of requests) {
      expect(Number(params.get('px'))).toBeGreaterThanOrEqual(WIDTH)
      expect(BigInt(params.get('to') ?? '0') > BigInt(params.get('from') ?? '0')).toBe(true)
    }
    // A coarse span fades in and out; an exact instant is a diamond; an unknown end fades.
    expect(war.style.background).toMatch(/linear-gradient\(to right, transparent 0%/)
    expect(screen.getByRole('button', { name: 'Crowning' })).toHaveAttribute('data-kind', 'instant')
    expect(screen.getByRole('button', { name: 'Rumour' }).style.background).toMatch(
      /transparent 100%\)$/,
    )
    expect(screen.getByTestId('series-band')).toHaveTextContent('Tides ×5000')
    expect(screen.getAllByTestId('density-bucket')).toHaveLength(1)
    expect(screen.getByTestId('timeline-status')).toHaveTextContent(
      /\d+ events, \d+ shown as density/,
    )

    // Panning a little keeps every item in its lane and reuses the tiles.
    const before = lanesOf()
    const asked = requests.length
    const view = screen.getByRole('application', { name: 'Timeline' })
    fireEvent.keyDown(view, { key: 'ArrowRight' })
    fireEvent.keyDown(view, { key: 'ArrowLeft' })
    fireEvent.keyDown(view, { key: 'ArrowLeft' })
    await waitFor(() => {
      expect(lanesOf()).toEqual(before)
    })
    expect(requests.length).toBeLessThanOrEqual(asked + 2) // at most the prefetched neighbours
  })

  it('selects with a click or the arrow keys, previews, and opens', async () => {
    eventsWorld()
    const { router } = await renderApp(`/v/v1/d/d1/timeline?from=${at(1998)}&to=${at(2014)}`)
    await userEvent.click(await screen.findByRole('button', { name: 'Crowning' }, LOADED))
    const preview = await screen.findByRole('complementary', { name: 'Selected event' })
    expect(within(preview).getByRole('link', { name: 'Crowning' })).toHaveAttribute(
      'href',
      '/v/v1/e/crowning',
    )
    expect(preview).toHaveTextContent('Importance 3')

    // ↓ selects the next event by start, ↑ the one before.
    const view = screen.getByRole('application', { name: 'Timeline' })
    view.focus()
    await userEvent.keyboard('{ArrowDown}')
    expect(
      within(screen.getByRole('complementary', { name: 'Selected event' })).getByRole('heading'),
    ).toHaveTextContent('Rumour')
    await userEvent.keyboard('{ArrowUp}{ArrowUp}')
    expect(screen.getByRole('button', { name: 'The Long War' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    await userEvent.keyboard('{Enter}')
    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/v/v1/e/war')
    })
  })

  it('opens an event with a double-click', async () => {
    eventsWorld()
    const { router } = await renderApp(`/v/v1/d/d1/timeline?from=${at(1998)}&to=${at(2014)}`)
    await userEvent.dblClick(await screen.findByRole('button', { name: 'Crowning' }, LOADED))
    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/v/v1/e/crowning')
    })
  })
})

describe('timeline layers', () => {
  const at = (year: number, month = 'jan', day = 1) =>
    fromFields(CALENDAR, { year: String(year), month, day: String(day) }, 'day')

  function layersWorld(present: bigint | null = null, items: unknown[] = []) {
    serveVault({
      kinds: [...KINDS, kind('calendar', 'Calendar'), kind('event', 'Event')],
      rows: [
        ...defaultRows().filter((entity) => entity.id !== 'd1'),
        dimensionRow('d1', 'Aetheria', 'c-greg', { duration: 10n ** 13n, present }),
        calendarRow('c-greg', 'Gregorian', 'gregorian'),
      ],
    })
    server.use(
      http.get('*/api/v1/vaults/v1/timelines/:id/window', () =>
        HttpResponse.json({ items, buckets: [], series_bands: [], total: items.length, culled: 0 }),
      ),
    )
  }

  it("draws the display calendar's eras, clipped to the view", async () => {
    layersWorld()
    await renderApp(`/v/v1/d/d1/timeline?from=${at(-20)}&to=${at(30)}`)
    const eras = await screen.findAllByTestId('era-band')
    expect(eras.map((era) => era.textContent)).toEqual(['Before Christ', 'Anno Domini'])
    expect(eras[1]).toHaveAttribute('title', 'Anno Domini (AD)')
    // The boundary is at 1 January of year 1, in pixels of the view.
    const v = viewport(at(-20), at(30) - at(-20), WIDTH)
    expect(eras[1]?.style.transform).toBe(`translateX(${toPx(v, at(1))}px)`)
  })

  it('shows phase glyphs once zoomed in enough, exactly at the phase changes', async () => {
    layersWorld()
    const from = at(2000)
    const to = at(2000, 'mar')
    const { router } = await renderApp(`/v/v1/d/d1/timeline?from=${from}&to=${to}`)
    const moon = await screen.findByRole('group', { name: 'Moon' })
    const full = within(moon).getAllByRole('img', { name: 'Moon: Full Moon' })
    expect(full[0]).toHaveAttribute(
      'data-t',
      nextPhaseAt(CALENDAR, from, 'moon', rational(7n, 16n)).toString(),
    )
    expect(full[0]).toHaveTextContent('🌕')
    // New moons start once (the phase either side of 0 is one).
    const news = within(moon).getAllByRole('img', { name: 'Moon: New Moon' })
    expect(news[0]).toHaveTextContent('🌑')
    expect(news.length).toBeLessThanOrEqual(3)
    expect(screen.getByRole('group', { name: 'Seasons' })).toBeInTheDocument()

    // Zoomed out to centuries, the phases are too close: no overlay.
    await router.navigate({
      to: '.',
      search: (previous: Record<string, unknown>) => ({
        ...previous,
        from: String(at(1900)),
        to: String(at(2100)),
      }),
    })
    await waitFor(() => {
      expect(screen.queryByTestId('overlay-row')).not.toBeInTheDocument()
    })
  })

  it("drags and steps the time cursor, snapping to the axis' minor unit; marks the present", async () => {
    const present = at(2006, 'jul')
    layersWorld(present)
    const from = at(1998)
    const to = at(2014)
    const { router } = await renderApp(`/v/v1/d/d1/timeline?from=${from}&to=${to}&at=${at(2005)}`)
    const handle = await screen.findByRole('slider', { name: 'Time cursor' })
    expect(screen.getByTestId('cursor-line')).toHaveAttribute('data-t', at(2005).toString())
    expect(screen.getByTestId('present-marker')).toHaveAttribute(
      'title',
      expect.stringMatching(/^Present: /),
    )

    const v = viewport(from, to - from, WIDTH)
    const minor = ticks(CALENDAR, v).minor[0]
    if (minor === undefined) throw new Error('no minor ticks')
    const snap = new TickSnap(CALENDAR, minor.level, 1n, 10n ** 13n)
    const cursorIn = () => BigInt((router.state.location.search as { at?: string }).at ?? '-1')

    // → moves to the next unit; the timeline doesn't pan.
    fireEvent.keyDown(handle, { key: 'ArrowRight' })
    await waitFor(() => {
      expect(cursorIn()).toBe(unitBounds(CALENDAR, at(2005), minor.level).end)
    })
    expect(urlRange(router)).toEqual([from, to])

    // Dragging snaps to the nearest unit and sets the cursor when let go.
    const dragged = await screen.findByRole('slider', { name: 'Time cursor' })
    fireEvent.pointerDown(dragged, { clientX: toPx(v, cursorIn()), pointerId: 1 })
    fireEvent.pointerMove(dragged, { clientX: 700.4, pointerId: 1 })
    fireEvent.pointerUp(dragged, { pointerId: 1 })
    const expected = snap.snap(fromPx(v, 700.4))
    await waitFor(() => {
      expect(cursorIn()).toBe(expected)
    })
    const bounds = unitBounds(CALENDAR, expected, minor.level)
    expect(bounds.start).toBe(expected)
  })

  it('marks occurrences as ticks and materialized ones with sub-events', async () => {
    const occurrence = (key: string, extra: Record<string, unknown>) => ({
      entity_id: 'feast',
      row_id: `row-feast-${key}`,
      name: `Feast ${key}`,
      visibility: 'public',
      parent_id: null,
      has_children: false,
      start_t: at(2000 + Number(key)).toString(),
      end_t: at(2000 + Number(key)).toString(),
      start_precision: 'day',
      start_approximate: false,
      end_kind: 'instant',
      end_precision: null,
      end_approximate: false,
      importance: 3,
      category: null,
      time_status: 'ok',
      occurrence_key: key,
      series_id: 'feast',
      occurrence_state: null,
      ...extra,
    })
    layersWorld(null, [
      occurrence('1', {}),
      occurrence('2', { entity_id: 'feast-2', occurrence_state: 'modified', has_children: true }),
    ])
    await renderApp(`/v/v1/d/d1/timeline?from=${at(1998)}&to=${at(2014)}`)
    const computed = await screen.findByRole('button', { name: 'Feast 1' }, LOADED)
    expect(computed).toHaveAttribute('data-occurrence', '1')
    expect(computed).not.toHaveAttribute('data-sub-events')
    const materialized = screen.getByRole('button', { name: 'Feast 2' })
    expect(materialized).toHaveAttribute('data-sub-events')
    expect(materialized).toHaveAttribute('title', 'Feast 2 (has sub-events)')
  })
})

describe('timeline pages in reader mode', () => {
  it.each(['/v/v1/d/d1/timeline'])('%s offers no editing', async (path) => {
    world()
    await renderApp(path, undefined, { readOnly: true })
    await settled()
    expectNoEditing()
    await expectAccessible()
  })
})

describe('timeline pages for the author', () => {
  it.each(['/v/v1/d/d1/timeline'])('%s is accessible', async (path) => {
    world()
    await renderApp(path)
    await settled()
    await expectAccessible()
  })
})
