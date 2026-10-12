import {
  formatDate,
  fromFields,
  nextOccurrences,
  type RecurrenceRule,
  type TimePoint,
} from '@lore/chronology'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { compiledCalendar } from '@/core/time'
import { calendarRow, dimensionRow, presetCalendar, testDimension } from '@/test/calendars'
import { CAPS, defaultRows, kind, KINDS, linkType, row, serveVault } from '@/test/fake-vault'
import { server } from '@/test/msw'
import { renderApp } from '@/test/render-app'

const compiled = compiledCalendar(presetCalendar('c-greg', 'gregorian'), testDimension())
if (compiled === null) throw new Error('gregorian')
const CALENDAR = compiled

const typed = (year: string, month: string, day: string): TimePoint => ({
  anchor: { kind: 'calendar', calendar_id: 'c-greg', fields: { year, month, day } },
  precision: 'day',
})
const at = (point: TimePoint): bigint => {
  const anchor = point.anchor
  if (anchor.kind === 'absolute') return BigInt(anchor.t)
  if (anchor.kind === 'calendar') {
    return fromFields(CALENDAR, anchor.fields, point.precision)
  }
  return 0n
}
const START = at(typed('5', 'mar', '10'))
const YEARLY: RecurrenceRule = {
  kind: 'calendar',
  calendar_id: 'c-greg',
  freq: { level: 'year' },
  limit: { kind: 'never' },
}
const show = (t: bigint) => formatDate(CALENDAR, t, 'day')
const yearly = nextOccurrences(
  YEARLY,
  {
    seriesStart: START,
    end: { kind: 'instant' },
    dimensionDuration: 10n ** 40n,
    calendar: CALENDAR,
  },
  START - 1n,
  4,
)

function event(id: string, name: string, ext: Record<string, unknown>) {
  return row(id, 'event', name, {
    dimension_id: 'd1',
    ext: {
      timeline_id: 'd1-prime',
      importance: 3,
      category: null,
      recurrence: null,
      time_status: 'ok',
      start: typed('5', 'mar', '10'),
      end: { kind: 'instant' },
      start_t: START.toString(),
      end_t: START.toString(),
      ...ext,
    },
  })
}

const EVENT_KIND = kind('event', 'Event', {
  allowed_parents: ['event'],
  capabilities: { ...CAPS, is_time_bound: true, has_existence: false },
  fields: [
    {
      key: 'mood',
      label: 'Mood',
      type: 'text',
      options: [],
      multiple: false,
      required: false,
      temporal: false,
      default_visibility: 'public',
      section: null,
      sort: 0,
      help: '',
      searchable: true,
      archived: false,
    },
  ],
})

/** Occurrence keys materialized through the API. */
const materialized: string[] = []

/** Aetheria with Coronation (once), Festival (yearly) and two materialized occurrences of it. */
function world() {
  materialized.length = 0
  const festival = event('festival', 'Festival', {
    recurrence: YEARLY,
    series_start_t: START.toString(),
  })
  festival.fields = { mood: 'joyful' }
  const writes = serveVault({
    kinds: [...KINDS, kind('calendar', 'Calendar'), EVENT_KIND],
    rows: [
      ...defaultRows().filter((entity) => entity.id !== 'd1'),
      dimensionRow('d1', 'Aetheria', 'c-greg'),
      calendarRow('c-greg', 'Gregorian', 'gregorian'),
      event('coronation', 'Coronation', {}),
      festival,
      event('occ-1', 'Festival (second)', {
        series_id: 'festival',
        occurrence_key: '1',
        occurrence_state: 'modified',
        occurrence_number: 2,
        original_start_t: (yearly[1]?.start ?? 0n).toString(),
        series_participants: [{ entity_id: 'a1', role: 'host' }],
      }),
      event('occ-3', 'Festival (fourth)', {
        series_id: 'festival',
        occurrence_key: '3',
        occurrence_state: 'referenced',
        occurrence_number: 4,
        // At its computed occurrence (as materializing anchors it), plus a day.
        start: {
          anchor: {
            kind: 'relative',
            ref: { type: 'event', id: 'festival', slot: 'start', occurrence: '3' },
            offset: { kind: 'base', units: '86400' },
          },
          precision: 'day',
        },
      }),
    ],
    linkTypes: [linkType('core.participant', 'participant')],
  })
  server.use(
    http.post('*/api/v1/vaults/v1/time/resolve', async ({ request }) => {
      const body = (await request.json()) as { items: { time_point: TimePoint }[] }
      const ok = (t: bigint) => ({
        t: t.toString(),
        status: 'ok',
        extent: { lo: t.toString(), hi: t.toString() },
        precision: 'day',
        approximate: false,
        display: show(t),
        error: null,
        default_precision: null,
      })
      return HttpResponse.json({
        calendar_id: 'c-greg',
        items: body.items.map(({ time_point }) => ({
          start: ok(at(time_point)),
          end: ok(at(time_point)),
        })),
      })
    }),
    http.get('*/api/v1/vaults/v1/events/festival/occurrences', ({ request }) => {
      const url = new URL(request.url)
      const from = BigInt(url.searchParams.get('from') ?? '0')
      const to = BigInt(url.searchParams.get('to') ?? '0')
      const items = yearly
        .filter((item) => item.start >= from && item.start < to)
        .map((item) => ({
          key: item.key,
          start_t: item.start.toString(),
          end_t: item.end.toString(),
          // Numbers count from the series' first occurrence, whatever the window.
          number: yearly.indexOf(item) + 1,
          entity_id: item.key === '1' ? 'occ-1' : item.key === '3' ? 'occ-3' : null,
          state: item.key === '1' ? 'modified' : item.key === '3' ? 'referenced' : null,
        }))
      return HttpResponse.json({ items, truncated: false, estimated_count: null })
    }),
    http.post('*/api/v1/vaults/v1/events/festival/occurrences/:key', ({ params }) => {
      materialized.push(String(params.key))
      return HttpResponse.json(
        {
          entity: { id: 'occ-3', name: `Festival ${String(params.key)}` },
          affected: { entities: [], dimensions: [], time_changed: true, search_changed: false },
        },
        { status: 201 },
      )
    }),
  )
  return writes
}

describe('the recurrence editor', () => {
  it('turns an event into a series with a preset, a summary and a preview', async () => {
    const writes = world()
    await renderApp('/v/v1/e/coronation')
    const time = await screen.findByRole('region', { name: 'Time' })
    await userEvent.click(await within(time).findByRole('button', { name: 'Edit time' }))
    const dialog = await screen.findByRole('dialog', { name: 'Edit Coronation' })
    const recurrence = await within(dialog).findByRole('region', { name: 'Recurrence' })
    await userEvent.click(within(recurrence).getByRole('checkbox', { name: 'Repeats' }))
    expect(
      await within(recurrence).findByText('Every year on day 10 of March.'),
    ).toBeInTheDocument()
    const preview = within(recurrence).getByRole('region', { name: 'Next occurrences' })
    await waitFor(() => {
      expect(within(preview).getAllByRole('listitem')).toHaveLength(10)
    })
    expect(within(preview).getAllByRole('listitem')[1]).toHaveTextContent(
      show(yearly[1]?.start ?? 0n),
    )

    // Weekly on two days of the week; then ends after 5 occurrences.
    await userEvent.selectOptions(
      within(recurrence).getByRole('combobox', { name: 'Pattern' }),
      'weekly',
    )
    await userEvent.click(within(recurrence).getByRole('checkbox', { name: 'Friday' }))
    const summary = within(recurrence).getByTestId('recurrence-summary')
    await waitFor(() => {
      expect(summary.textContent).toMatch(/^Every week on \w+ and Friday\.$/)
    })
    await userEvent.selectOptions(
      within(recurrence).getByRole('combobox', { name: 'Ends' }),
      'count',
    )
    expect(summary.textContent).toMatch(/, 10 times\.$/)
    await waitFor(() => {
      expect(within(preview).getAllByRole('listitem')).toHaveLength(10)
    })

    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    await waitFor(() => {
      expect(writes.find((write) => write.method === 'PATCH')).toBeDefined()
    })
    const body = writes.find((write) => write.method === 'PATCH')?.body as {
      ext: { recurrence: RecurrenceRule }
    }
    expect(body.ext.recurrence).toMatchObject({
      kind: 'calendar',
      calendar_id: 'c-greg',
      freq: { cycle: 'week' },
      select: { path: [{ level: 'day', cycle: { id: 'week' } }] },
      limit: { kind: 'count', count: '10' },
    })
    expect(JSON.stringify(body.ext.recurrence)).toContain('"fri"')
  })

  it('shows problems from the engine and edits the rule in advanced mode', async () => {
    world()
    await renderApp('/v/v1/e/festival')
    const time = await screen.findByRole('region', { name: 'Time' })
    await userEvent.click(await within(time).findByRole('button', { name: 'Edit time' }))
    const recurrence = await within(await screen.findByRole('dialog')).findByRole('region', {
      name: 'Recurrence',
    })
    await userEvent.selectOptions(
      within(recurrence).getByRole('combobox', { name: 'Pattern' }),
      'custom',
    )
    await userEvent.selectOptions(
      within(recurrence).getByRole('combobox', { name: 'Period' }),
      'level:month',
    )
    await userEvent.click(within(recurrence).getByRole('button', { name: 'Position' }))
    const values = within(recurrence).getByRole('textbox', { name: 'Position 1 values' })
    await userEvent.clear(values)
    await userEvent.type(values, '0')
    await userEvent.tab()
    expect(
      await within(recurrence).findByRole('list', { name: 'Rule problems' }),
    ).toBeInTheDocument()
    await userEvent.clear(values)
    await userEvent.type(values, '-1')
    await userEvent.tab()
    expect(within(recurrence).getByTestId('recurrence-summary')).toHaveTextContent(
      'Every month on the last day.',
    )
  })
})

describe('reconciliation', () => {
  it('asks how to reconcile customized occurrences when a rule change orphans them', async () => {
    const writes = world()
    const applied: unknown[] = []
    server.use(
      http.patch('*/api/v1/vaults/v1/entities/festival', () =>
        HttpResponse.json(
          {
            type: 'about:blank',
            status: 409,
            code: 'conflict',
            title: 'Conflict',
            detail: '1 materialized occurrence(s) would lose their occurrence.',
            context: { orphaned: ['occ-3'], proposals: '/events/festival/recurrence/proposals' },
          },
          { status: 409, headers: { 'Content-Type': 'application/problem+json' } },
        ),
      ),
      http.post('*/api/v1/vaults/v1/events/festival/recurrence/proposals', () =>
        HttpResponse.json({
          id: 'rp1',
          event_id: 'festival',
          base_revision: 1,
          created_at: '2026-10-12T00:00:00Z',
          expires_at: '2026-10-12T01:00:00Z',
          items: [
            {
              entity_id: 'occ-1',
              name: 'Festival (second)',
              key: '1',
              state: 'modified',
              original_start_t: (yearly[1]?.start ?? 0n).toString(),
              start_t: (yearly[1]?.start ?? 0n).toString(),
              status: 'moved',
              new_start_t: (yearly[2]?.start ?? 0n).toString(),
              rekey_key: '3',
              rekey_start_t: (yearly[3]?.start ?? 0n).toString(),
              rekey_held_by: 'occ-3',
              strategies: ['keep_key', 'rekey', 'detach'],
              default_strategy: 'keep_key',
            },
            {
              entity_id: 'occ-3',
              name: 'Festival (fourth)',
              key: '3',
              state: 'referenced',
              original_start_t: (yearly[3]?.start ?? 0n).toString(),
              start_t: (yearly[3]?.start ?? 0n).toString(),
              status: 'orphaned',
              new_start_t: null,
              rekey_key: null,
              rekey_start_t: null,
              rekey_held_by: null,
              strategies: ['detach', 'trash'],
              default_strategy: 'detach',
            },
          ],
          summary: { unchanged: 0, moved: 1, orphaned: 1 },
        }),
      ),
      http.post(
        '*/api/v1/vaults/v1/events/festival/recurrence/proposals/rp1/apply',
        async ({ request }) => {
          applied.push(await request.json())
          return HttpResponse.json({
            event: { id: 'festival', name: 'Festival', kind: 'event', ext: {} },
            kept: 0,
            rekeyed: 0,
            detached: 1,
            trashed: 1,
            affected: { entities: [], dimensions: [], time_changed: true, search_changed: false },
          })
        },
      ),
    )
    await renderApp('/v/v1/e/festival')
    const time = await screen.findByRole('region', { name: 'Time' })
    await userEvent.click(await within(time).findByRole('button', { name: 'Edit time' }))
    const dialog = await screen.findByRole('dialog', { name: 'Edit Festival' })
    const recurrence = await within(dialog).findByRole('region', { name: 'Recurrence' })
    await userEvent.selectOptions(
      within(recurrence).getByRole('combobox', { name: 'Pattern' }),
      'monthly',
    )
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))

    const review = await screen.findByRole('dialog', { name: 'Review the occurrences' })
    expect(review).toHaveTextContent('1 customized occurrence moves, 1 is no longer an occurrence')
    const moved = within(review).getByRole('row', { name: 'Festival (second)' })
    expect(moved).toHaveTextContent('Moves')
    expect(moved).toHaveTextContent(show(yearly[2]?.start ?? 0n))
    // Re-keying onto the fourth's key while it stays put is a conflict.
    await userEvent.selectOptions(
      within(review).getByRole('combobox', { name: 'Choice for Festival (second)' }),
      'rekey',
    )
    const apply = within(review).getByRole('button', { name: 'Apply the change' })
    // The fourth holds that key: detached, it frees it; in the trash it still holds it.
    expect(within(moved).queryByRole('alert')).not.toBeInTheDocument()
    await userEvent.selectOptions(
      within(review).getByRole('combobox', { name: 'Choice for Festival (fourth)' }),
      'trash',
    )
    expect(within(moved).getByRole('alert')).toHaveTextContent('Another customized occurrence')
    expect(apply).toBeDisabled()
    await userEvent.selectOptions(
      within(review).getByRole('combobox', { name: 'Choice for Festival (fourth)' }),
      'detach',
    )
    expect(apply).toBeEnabled()
    await userEvent.click(apply)
    await waitFor(() => {
      expect(applied).toHaveLength(1)
    })
    expect(applied[0]).toEqual({ strategies: { 'occ-1': 'rekey', 'occ-3': 'detach' } })
    expect(writes.filter((write) => write.method === 'PATCH')).toHaveLength(0)
  })
})

describe('occurrences', () => {
  it('lists occurrences with numbers and states, and acts on them', async () => {
    const writes = world()
    const { router } = await renderApp('/v/v1/e/festival')
    const section = await screen.findByRole('region', { name: 'Occurrences' })
    const list = await within(section).findByRole('list', { name: 'Occurrences' })
    const rows = within(list).getAllByRole('listitem')
    expect(rows.map((item) => item.getAttribute('aria-label'))).toEqual([
      '1st',
      '2nd',
      '3rd',
      '4th',
    ])
    expect(rows[1]).toHaveTextContent('Moved')
    expect(
      within(within(list).getByRole('listitem', { name: '2nd' })).getByRole('link'),
    ).toHaveAttribute('href', '/v/v1/e/occ-1')

    // Cancel a customized one: its event is patched.
    await userEvent.click(within(list).getByRole('button', { name: 'Cancel 2nd' }))
    await waitFor(() => {
      expect(writes.find((write) => write.method === 'PATCH')?.body).toMatchObject({
        ext: { cancelled: true },
      })
    })

    // Opening a computed one materializes it.
    await userEvent.click(
      within(within(list).getByRole('listitem', { name: '3rd' })).getByRole('button', {
        name: 'Open',
      }),
    )
    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/v/v1/e/occ-3')
    })
    expect(materialized).toEqual([yearly[2]?.key])
  })

  it('names the occurrence an anchor points at by its number, not its key (#287)', async () => {
    world()
    await renderApp('/v/v1/e/occ-3')
    const time = await screen.findByRole('region', { name: 'Time' })
    // Key 3 is the 4th occurrence (keys count from 0).
    await waitFor(() => {
      expect(time).toHaveTextContent(
        '86,400 seconds after the start of the 4th occurrence of Festival.',
      )
    })
    expect(time).not.toHaveTextContent('occurrence 3')
  })

  it('heads an occurrence’s page with its number, its series and what it inherits', async () => {
    world()
    await renderApp('/v/v1/e/occ-1')
    const note = await screen.findByRole('note')
    expect(await within(note).findByRole('link', { name: 'Festival' })).toBeInTheDocument()
    expect(note).toHaveTextContent('Occurrence #2 of Festival')
    expect(note).toHaveTextContent('Moved')
    expect(await within(note).findByText('joyful')).toBeInTheDocument()
    const participants = screen.getByRole('region', { name: 'Participants' })
    const fromSeries = within(participants).getByRole('region', { name: 'From the series' })
    expect(await within(fromSeries).findByRole('link', { name: 'Crown' })).toBeInTheDocument()
    expect(within(fromSeries).getByText('host')).toBeInTheDocument()
  })
})
