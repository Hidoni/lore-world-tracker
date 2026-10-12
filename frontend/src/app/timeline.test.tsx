import { formatDate, fromFields } from '@lore/chronology'
import { ticks, toPx, viewport } from '@lore/chronology/viewport'
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { compiledCalendar } from '@/core/time'
import { calendarRow, dimensionRow, presetCalendar, testDimension } from '@/test/calendars'
import { defaultRows, kind, KINDS, serveVault } from '@/test/fake-vault'
import { renderApp } from '@/test/render-app'

const D = 10n ** 100n
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
