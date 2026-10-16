import { formatDate, fromFields, type TimePoint } from '@lore/chronology'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { compiledCalendar } from '@/core/time'
import { AXE_TIMEOUT, expectAccessible } from '@/test/axe'
import { calendarRow, dimensionRow, presetCalendar, testDimension } from '@/test/calendars'
import {
  CAPS,
  defaultRows,
  finding,
  kind,
  KINDS,
  linkType,
  row,
  serveVault,
  type LinkRow,
} from '@/test/fake-vault'
import { server } from '@/test/msw'
import { expectNoEditing, settled } from '@/test/reader'
import { renderApp } from '@/test/render-app'

const DAY = 86_400n
const GREGORIAN = compiledCalendar(presetCalendar('c-greg', 'gregorian'), testDimension())
if (GREGORIAN === null) throw new Error('gregorian')
const CALENDAR = GREGORIAN

const date = (year: string, month: string, day: string) =>
  fromFields(CALENDAR, { year, month, day }, 'day')
const CORONATION_START = date('5', 'mar', '10')
const CORONATION_END = date('5', 'may', '10')
const FEAST_START = CORONATION_END + 3n * DAY

const typed = (year: string, month: string, day: string): TimePoint => ({
  anchor: { kind: 'calendar', calendar_id: 'c-greg', fields: { year, month, day } },
  precision: 'day',
})

function eventRow(
  id: string,
  name: string,
  ext: Record<string, unknown>,
  extra: { parent_id?: string } = {},
) {
  return row(id, 'event', name, {
    dimension_id: 'd1',
    ...extra,
    ext: {
      timeline_id: 'd1-prime',
      importance: 3,
      category: null,
      recurrence: null,
      time_status: 'ok',
      ...ext,
    },
  })
}

const EVENT_KIND = kind('event', 'Event', {
  allowed_parents: ['event'],
  capabilities: { ...CAPS, is_time_bound: true, has_existence: false },
})

/** Aetheria (Gregorian), Coronation (10 Mar 5 for two months), Feast (3 days after it ends). */
function world(options: { links?: LinkRow[]; findings?: ReturnType<typeof finding>[] } = {}) {
  const writes = serveVault({
    kinds: [...KINDS, kind('calendar', 'Calendar'), EVENT_KIND],
    rows: [
      ...defaultRows().filter((entity) => entity.id !== 'd1'),
      dimensionRow('d1', 'Aetheria', 'c-greg'),
      calendarRow('c-greg', 'Gregorian', 'gregorian'),
      eventRow('ev-cor', 'Coronation', {
        start: typed('5', 'mar', '10'),
        end: {
          kind: 'duration',
          duration: { kind: 'calendar', calendar_id: 'c-greg', amounts: { month: '2' }, sign: 1 },
        },
        start_t: CORONATION_START.toString(),
        end_t: CORONATION_END.toString(),
        importance: 4,
        category: 'Ceremony',
      }),
      eventRow(
        'ev-feast',
        'Feast',
        {
          start: {
            anchor: {
              kind: 'relative',
              ref: { type: 'event', id: 'ev-cor', slot: 'end' },
              offset: {
                kind: 'calendar',
                calendar_id: 'c-greg',
                amounts: { day: '3' },
                sign: 1,
              },
            },
            precision: 'day',
          },
          end: { kind: 'instant' },
          start_t: FEAST_START.toString(),
          end_t: FEAST_START.toString(),
        },
        { parent_id: 'ev-cor' },
      ),
      row('hero', 'artifact', 'Sceptre', { dimension_id: 'd1' }),
    ],
    linkTypes: [
      linkType('core.causes', 'causes', { inverse_label: 'caused by' }),
      linkType('core.participant', 'participant', { inverse_label: 'participates in' }),
    ],
    links: options.links,
    findings: options.findings,
  })
  server.use(
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
    http.get('*/api/v1/vaults/v1/timelines/d1-prime/event-tree', ({ request }) => {
      const parent = new URL(request.url).searchParams.get('parent')
      const node = (
        id: string,
        name: string,
        start: bigint,
        end: bigint,
        extra: Record<string, unknown> = {},
      ) => ({
        id,
        name,
        visibility: 'public',
        parent_id: null,
        start_t: start.toString(),
        end_t: end.toString(),
        time_status: 'ok',
        importance: 3,
        category: null,
        display: {
          calendar_id: 'c-greg',
          start: formatDate(CALENDAR, start, 'day'),
          end: formatDate(CALENDAR, end, 'day'),
        },
        has_children: false,
        participants: 0,
        ...extra,
      })
      const items =
        parent === null
          ? [
              node('ev-cor', 'Coronation', CORONATION_START, CORONATION_END, {
                has_children: true,
                importance: 4,
                participants: 2,
              }),
              node('ev-later', 'Later', CORONATION_END + 100n * DAY, CORONATION_END + 100n * DAY),
            ]
          : parent === 'ev-cor'
            ? [
                node('ev-feast', 'Feast', FEAST_START, FEAST_START, {
                  parent_id: 'ev-cor',
                }),
              ]
            : []
      return HttpResponse.json({ items, next_cursor: null })
    }),
    http.post('*/api/v1/vaults/v1/time/resolve', async ({ request }) => {
      const body = (await request.json()) as { items: { time_point: TimePoint }[] }
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
        calendar_id: 'c-greg',
        items: body.items.map(({ time_point }) => {
          const t = time_point.anchor.kind === 'absolute' ? time_point.anchor.t : '0'
          return { start: ok(t), end: ok(t) }
        }),
      })
    }),
  )
  return writes
}

const section = (name: string) => screen.getByRole('region', { name })

describe('event pages', () => {
  it('shows the time: dates in every calendar, anchors explained, duration, badges', async () => {
    world()
    await renderApp('/v/v1/e/ev-feast')
    const time = await screen.findByRole('region', { name: 'Time' })
    // Feast starts 3 days after the Coronation ends: linked.
    expect(await within(time).findByText(/3 days after the end of/)).toBeInTheDocument()
    expect(within(time).getByRole('link', { name: 'Coronation' })).toHaveAttribute(
      'href',
      '/v/v1/e/ev-cor',
    )
    expect(within(time).getByText('An instant.')).toBeInTheDocument()
    expect(within(time).getByText('Instant')).toBeInTheDocument()
    expect(await within(time).findByText('Prime')).toBeInTheDocument()
    const table = within(time).getByRole('table', { name: 'In every calendar' })
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows.map((each) => within(each).getAllByRole('cell')[0]?.textContent)).toEqual([
      'Gregorian',
      'Absolute',
    ])
    expect(rows[0]).toHaveTextContent(formatDate(CALENDAR, FEAST_START, 'day'))
  })

  it('shows a typed start, a calendar duration, importance and category', async () => {
    world()
    await renderApp('/v/v1/e/ev-cor')
    const time = await screen.findByRole('region', { name: 'Time' })
    expect(await within(time).findByText('Typed in Gregorian.')).toBeInTheDocument()
    expect(within(time).getByText('Lasts 2 months.')).toBeInTheDocument()
    expect(within(time).getByText('2 months')).toBeInTheDocument()
    expect(within(time).getByText('Importance 4 · High')).toBeInTheDocument()
    expect(within(time).getByText('Ceremony')).toBeInTheDocument()
    // Its sub-event, from the timeline's outline.
    const subEvents = section('Sub-events')
    expect(await within(subEvents).findByRole('link', { name: 'Feast' })).toBeInTheDocument()
  })

  it('edits importance, category and parent through the event dialog', async () => {
    const writes = world()
    await renderApp('/v/v1/e/ev-feast')
    const time = await screen.findByRole('region', { name: 'Time' })
    await userEvent.click(await within(time).findByRole('button', { name: 'Edit time' }))
    const dialog = await screen.findByRole('dialog', { name: 'Edit Feast' })
    expect(within(dialog).getByRole('group', { name: 'Parent event' })).toHaveTextContent(
      'Coronation',
    )
    await userEvent.selectOptions(within(dialog).getByRole('combobox', { name: 'Importance' }), '5')
    await userEvent.type(within(dialog).getByRole('textbox', { name: 'Category' }), 'Banquet')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Remove parent' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    await waitFor(() => {
      expect(writes.find((write) => write.method === 'PATCH')).toBeDefined()
    })
    const body = writes.find((write) => write.method === 'PATCH')?.body as {
      parent_id: string | null
      ext: { importance: number; category: string; start: TimePoint; end: unknown }
    }
    expect(body.parent_id).toBeNull()
    expect(body.ext).toMatchObject({ importance: 5, category: 'Banquet', end: { kind: 'instant' } })
    expect(body.ext.start.anchor.kind).toBe('relative')
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
  })

  it('creates a sub-event with a start and the parent preset', async () => {
    const writes = world()
    await renderApp('/v/v1/e/ev-cor')
    const subEvents = await screen.findByRole('region', { name: 'Sub-events' })
    await userEvent.click(within(subEvents).getByRole('button', { name: 'Create sub-event' }))
    const dialog = await screen.findByRole('dialog', { name: 'New event' })
    await userEvent.type(within(dialog).getByRole('textbox', { name: 'Name' }), 'Toast')
    const create = within(dialog).getByRole('button', { name: 'Create event' })
    expect(create).toBeDisabled() // no start yet
    await userEvent.click(within(dialog).getByRole('tab', { name: 'Absolute' }))
    await userEvent.type(
      within(dialog).getByRole('textbox', { name: 'Moment (seconds)' }),
      CORONATION_START.toString(),
    )
    await waitFor(() => {
      expect(create).toBeEnabled()
    })
    await userEvent.click(create)
    await waitFor(() => {
      expect(writes.find((write) => write.method === 'POST')).toBeDefined()
    })
    expect(writes.find((write) => write.method === 'POST')?.body).toMatchObject({
      kind: 'event',
      name: 'Toast',
      dimension_id: 'd1',
      parent_id: 'ev-cor',
      ext: {
        timeline_id: 'd1-prime',
        start: { anchor: { kind: 'absolute', t: CORONATION_START.toString() } },
        end: { kind: 'instant' },
        importance: 3,
        category: null,
      },
    })
  })

  it('links causes and participants, and flags an effect before its cause', async () => {
    const writes = world({
      links: [
        {
          id: 'l-cause',
          link_type: 'core.causes',
          source_id: 'ev-feast',
          target_id: 'ev-cor',
          data: { description: 'Too much wine' },
        },
      ],
      findings: [
        finding(
          'f1',
          'core.event.effect_before_cause',
          'warning',
          'Coronation starts before its cause',
          [
            { id: 'ev-cor', name: 'Coronation', kind: 'event' },
            { id: 'ev-feast', name: 'Feast', kind: 'event' },
          ],
        ),
      ],
    })
    await renderApp('/v/v1/e/ev-cor')
    const causality = await screen.findByRole('region', { name: 'Causes and effects' })
    const causes = within(causality).getByRole('region', { name: 'Causes' })
    expect(await within(causes).findByRole('link', { name: 'Feast' })).toBeInTheDocument()
    expect(within(causes).getByText('Too much wine')).toBeInTheDocument()
    expect(await within(causes).findByText('Effect before cause')).toBeInTheDocument()
    // The relations panel leaves causes to this section.
    expect(within(section('Relations')).queryByText('Feast')).not.toBeInTheDocument()

    // An effect: search, then a description.
    const effects = within(causality).getByRole('region', { name: 'Effects' })
    await userEvent.type(within(effects).getByRole('textbox', { name: 'Add an effect' }), 'Lat')
    expect(await within(effects).findByText('Create “Lat”')).toBeInTheDocument()

    // A participant with a role.
    const participants = section('Participants')
    await userEvent.type(
      within(participants).getByRole('textbox', { name: 'Add a participant' }),
      'Sce',
    )
    await userEvent.click(await within(participants).findByRole('button', { name: /^Sceptre/ }))
    await userEvent.type(within(participants).getByRole('combobox', { name: 'Role' }), 'regalia')
    await userEvent.click(within(participants).getByRole('button', { name: 'Add' }))
    await waitFor(() => {
      expect(writes.find((write) => write.path === '/links')).toBeDefined()
    })
    expect(writes.find((write) => write.path === '/links')?.body).toEqual({
      link_type: 'core.participant',
      source_id: 'ev-cor',
      target_id: 'hero',
      role: 'regalia',
    })
    expect(await within(participants).findByText('regalia')).toBeInTheDocument()
  })
})

describe('event outline', () => {
  it('lists the timeline’s events by start and expands sub-events lazily', async () => {
    world()
    await renderApp('/v/v1/d/d1/events')
    const grid = await screen.findByRole('treegrid', { name: 'Event outline' })
    const coronation = await within(grid).findByRole('row', { name: 'Coronation' })
    expect(
      within(coronation)
        .getAllByRole('gridcell')
        .map((cell) => cell.textContent),
    ).toEqual([
      'Coronation',
      formatDate(CALENDAR, CORONATION_START, 'day'),
      formatDate(CALENDAR, CORONATION_END, 'day'),
      '2 months',
      '4',
      '2',
    ])
    expect(coronation).toHaveAttribute('aria-expanded', 'false')
    expect(within(grid).queryByRole('row', { name: 'Feast' })).not.toBeInTheDocument()

    // Keyboard: → expands, ↓ moves into the sub-event, ← goes back to the parent.
    coronation.focus()
    await userEvent.keyboard('{ArrowRight}')
    const feast = await within(grid).findByRole('row', { name: 'Feast' })
    expect(coronation).toHaveAttribute('aria-expanded', 'true')
    expect(feast).toHaveAttribute('aria-level', '2')
    await userEvent.keyboard('{ArrowDown}')
    expect(feast).toHaveFocus()
    await userEvent.keyboard('{ArrowLeft}')
    expect(coronation).toHaveFocus()
    await userEvent.keyboard('{ArrowLeft}')
    expect(coronation).toHaveAttribute('aria-expanded', 'false')
    await userEvent.keyboard('{End}')
    expect(within(grid).getByRole('row', { name: 'Later' })).toHaveFocus()
  })

  it('opens the focused event with Enter', async () => {
    world()
    const { router } = await renderApp('/v/v1/d/d1/events')
    const row = await screen.findByRole('row', { name: 'Coronation' })
    row.focus()
    await userEvent.keyboard('{Enter}')
    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/v/v1/e/ev-cor')
    })
  })
})

describe('events pages in reader mode', () => {
  it.each(['/v/v1/e/ev-feast', '/v/v1/e/ev-cor'])(
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

describe('events pages for the author', () => {
  it.each(['/v/v1/e/ev-feast', '/v/v1/e/ev-cor'])(
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
