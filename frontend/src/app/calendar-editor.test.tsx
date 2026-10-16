import { PRESETS } from '@lore/chronology/presets'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { AXE_TIMEOUT, expectAccessible } from '@/test/axe'
import { calendarRow, dimensionRow } from '@/test/calendars'
import { defaultRows, KINDS, kind, serveVault } from '@/test/fake-vault'
import { server } from '@/test/msw'
import { renderApp } from '@/test/render-app'

function vault() {
  return serveVault({
    kinds: [...KINDS, kind('calendar', 'Calendar')],
    rows: [
      ...defaultRows().filter((entity) => entity.id !== 'd1'),
      dimensionRow('d1', 'Aetheria', 'c-greg'),
      calendarRow('c-greg', 'Gregorian', 'gregorian'),
    ],
  })
}

const levels = () => screen.getByRole('region', { name: 'Levels' })
const templates = () => screen.getByRole('region', { name: 'Templates' })

/** The level row whose id is `id`. */
function level(id: string): HTMLElement {
  const row = within(levels())
    .getAllByRole('listitem')
    .find((item) => (within(item).getAllByRole('textbox')[0] as HTMLInputElement).value === id)
  if (row === undefined) throw new Error(`no level ${id}`)
  return row
}

async function replace(input: HTMLElement, text: string) {
  await userEvent.clear(input)
  if (text !== '') await userEvent.type(input, text)
}

/** Fills a level row: id, label, plural, abbreviation (and the first number when given). */
async function describeLevel(
  row: HTMLElement,
  values: { id: string; plural: string; abbr: string; first?: string },
) {
  const [id, label, plural, abbr] = within(row).getAllByRole('textbox')
  if (!id || !label || !plural || !abbr) throw new Error('level inputs')
  await replace(id, values.id)
  await replace(label, values.id)
  await replace(plural, values.plural)
  await replace(abbr, values.abbr)
  if (values.first !== undefined) {
    await replace(within(row).getByRole('textbox', { name: /first number/ }), values.first)
  }
}

/** Adds a template at a level (its fresh id is the level's id) and renames it. */
async function addTemplate(levelId: string, id: string, count?: string) {
  await userEvent.click(
    within(templates()).getByRole('button', { name: `Add a ${levelId} template` }),
  )
  if (id !== levelId) {
    await replace(within(template(levelId)).getByRole('textbox', { name: 'Template id' }), id)
  }
  const card = template(id)
  if (count !== undefined)
    await replace(within(card).getByRole('textbox', { name: 'Count' }), count)
  return card
}

function template(id: string): HTMLElement {
  return within(templates()).getByRole('listitem', { name: `Template ${id}` })
}

/** A year template of three named months. */
async function yearTemplate(id: string, months: [string, string, string, string][]) {
  const card = await addTemplate('year', id)
  await userEvent.selectOptions(within(card).getByRole('combobox', { name: 'Layout' }), 'sequence')
  let missing = months.length
  while (missing-- > 0) {
    await userEvent.click(within(template(id)).getByRole('button', { name: 'Named unit' }))
  }
  // The sequence starts with one numbered run: remove it.
  await userEvent.click(within(template(id)).getByRole('button', { name: 'Remove unit 1' }))
  for (const [index, [slot, name, abbr, child]] of months.entries()) {
    const row = within(template(id)).getByRole('listitem', { name: `Unit ${index + 1}` })
    await replace(within(row).getByRole('textbox', { name: `Unit ${index + 1} id` }), slot)
    await replace(within(row).getByRole('textbox', { name: `Unit ${index + 1} name` }), name)
    await replace(
      within(row).getByRole('textbox', { name: `Unit ${index + 1} abbreviation` }),
      abbr,
    )
    await userEvent.selectOptions(
      within(row).getByRole('combobox', { name: `Unit ${index + 1} template` }),
      child,
    )
  }
}

/** The editor loads lazily, which can take a while under a loaded test run. */
const LOADED = { timeout: 5000 }

describe('calendar editor', () => {
  it('builds the alternating-years calendar from blank, matching the preset', async () => {
    vault()
    await renderApp('/v/v1/calendars/new?dimension=d1')
    expect(await screen.findByRole('heading', { name: 'New calendar' }, LOADED)).toBeInTheDocument()

    // Levels: blank has day and year; add month (below year), then hour, minute, second.
    await userEvent.click(
      within(level('year')).getByRole('button', { name: 'Add a level below year' }),
    )
    await describeLevel(level('level'), { id: 'month', plural: 'months', abbr: 'mo' })
    await userEvent.click(
      within(level('day')).getByRole('button', { name: 'Add a level below day' }),
    )
    await describeLevel(level('level'), { id: 'hour', plural: 'hours', abbr: 'h', first: '0' })
    await userEvent.click(
      within(level('hour')).getByRole('button', { name: 'Add a level below hour' }),
    )
    await describeLevel(level('level'), {
      id: 'minute',
      plural: 'minutes',
      abbr: 'min',
      first: '0',
    })
    await userEvent.click(
      within(level('minute')).getByRole('button', { name: 'Add a level below minute' }),
    )
    await describeLevel(level('level'), { id: 'second', plural: 'seconds', abbr: 's', first: '0' })

    // Templates: the base unit, then minute, hour, day (24 hours), two months, two years.
    await userEvent.click(
      within(template('year')).getByRole('button', { name: 'Remove template year' }),
    )
    await addTemplate('second', 'second')
    await addTemplate('minute', 'minute', '60')
    await addTemplate('hour', 'hour', '60')
    await replace(within(template('day')).getByRole('textbox', { name: 'Count' }), '24')
    await addTemplate('month', 'm30', '30')
    await addTemplate('month', 'm31', '31')
    await yearTemplate('year_odd', [
      ['frostfall', 'Frostfall', 'Fro', 'm30'],
      ['thawing', 'Thawing', 'Tha', 'm31'],
      ['bloom', 'Bloom', 'Blo', 'm30'],
    ])
    await yearTemplate('year_even', [
      ['ember', 'Ember', 'Emb', 'm31'],
      ['ash', 'Ash', 'Ash', 'm30'],
      ['cinder', 'Cinder', 'Cin', 'm31'],
    ])
    for (const id of ['second', 'minute', 'hour']) {
      await userEvent.selectOptions(
        within(level(id)).getByRole('combobox', { name: /default template/ }),
        id,
      )
    }

    // Years: odd and even years alternate from year 1.
    const years = screen.getByRole('region', { name: 'Years' })
    await replace(within(years).getByRole('textbox', { name: 'Rules id' }), 'imperial')
    await replace(within(years).getByRole('textbox', { name: 'Rules name' }), 'Imperial Reckoning')
    await userEvent.selectOptions(
      within(years).getByRole('combobox', { name: 'Year pattern' }),
      'cycle',
    )
    await userEvent.click(within(years).getByRole('button', { name: 'Year in the cycle' }))
    await userEvent.selectOptions(
      within(years).getByRole('combobox', { name: 'Cycle year 2' }),
      'year_even',
    )

    // Alignment: year 1 begins on the first of Frostfall at the inception.
    const alignment = screen.getByRole('region', { name: 'Alignment' })
    await replace(within(alignment).getByRole('textbox', { name: 'Alignment month' }), 'frostfall')
    await replace(within(alignment).getByRole('textbox', { name: 'Alignment day' }), '1')

    // It compiles, the preview shows year 2's months, and the JSON is the preset's.
    const preview = screen.getByRole('complementary', { name: 'Preview' })
    expect(within(preview).getByText('The calendar compiles.')).toBeInTheDocument()
    await replace(within(preview).getByRole('textbox', { name: 'Preview year' }), '2')
    expect(
      within(preview)
        .getAllByRole('row')
        .map((row) => row.textContent),
    ).toEqual(['monthsdays', 'Ember31', 'Ash30', 'Cinder31'])
    await userEvent.click(screen.getByRole('tab', { name: 'JSON' }))
    const text = screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'Definition JSON' }).value
    const json: unknown = JSON.parse(text)
    const preset = structuredClone(PRESETS.get('alternating-years')?.definition)
    if (preset === undefined) throw new Error('no preset')
    delete preset.eras
    delete preset.regimes[0].cycles
    expect(json).toEqual(preset)
  }, 60_000)

  it('shows problems at their fields and focuses them from the list', async () => {
    vault()
    await renderApp('/v/v1/calendars/new?dimension=d1')
    await screen.findByRole('heading', { name: 'New calendar' }, LOADED)
    await replace(within(level('day')).getByRole('textbox', { name: /id$/ }), 'Day!')
    expect(
      within(levels()).getByText('Use lowercase letters, digits and _ (starting with a letter).'),
    ).toBeInTheDocument()
    const preview = screen.getByRole('complementary', { name: 'Preview' })
    const problems = within(preview).getByRole('list', { name: 'Problems' })
    const entry = within(problems).getByRole('button', {
      name: 'Use lowercase letters, digits and _ (starting with a letter).',
    })
    await userEvent.click(entry)
    expect(within(level('Day!')).getByRole('textbox', { name: /id$/ })).toHaveFocus()
    expect(screen.getByRole('button', { name: 'Create calendar' })).toBeDisabled()

    await replace(within(level('Day!')).getByRole('textbox', { name: /id$/ }), 'day')
    // A duplicate slot id is reported in its template.
    await userEvent.selectOptions(
      within(template('year')).getByRole('combobox', { name: 'Layout' }),
      'sequence',
    )
    await userEvent.click(within(template('year')).getByRole('button', { name: 'Named unit' }))
    await userEvent.click(within(template('year')).getByRole('button', { name: 'Named unit' }))
    expect(
      within(template('year')).getByText('Another unit of this template has this id.'),
    ).toBeInTheDocument()
  })

  it('creates a calendar from a preset', async () => {
    const writes = vault()
    const { router } = await renderApp('/v/v1/calendars/new?dimension=d1')
    await userEvent.selectOptions(
      await screen.findByRole('combobox', { name: 'Start from' }),
      '360-day',
    )
    expect(screen.getByRole('textbox', { name: 'Calendar name' })).toHaveValue('360-day')
    expect(screen.getByText('The calendar compiles.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Create calendar' }))
    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/v/v1/calendars/new1/edit')
    })
    expect(writes.find((write) => write.method === 'POST')?.body).toMatchObject({
      kind: 'calendar',
      name: '360-day',
      dimension_id: 'd1',
      ext: { definition: PRESETS.get('simple-360')?.definition },
    })
  })

  it(
    'has no serious accessibility violations',
    async () => {
      vault()
      await renderApp('/v/v1/calendars/c-greg/edit')
      expect(await screen.findByRole('heading', { name: 'Gregorian' })).toBeInTheDocument()
      await expectAccessible()
    },
    AXE_TIMEOUT,
  )

  it('saves an existing calendar nothing depends on through an empty proposal', async () => {
    const calls = proposals({ items: [] })
    vault()
    await renderApp('/v/v1/calendars/c-greg/edit')
    expect(await screen.findByRole('heading', { name: 'Gregorian' })).toBeInTheDocument()
    await replace(within(level('month')).getByRole('textbox', { name: /plural$/ }), 'moons')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => {
      expect(calls.applied).toHaveLength(1)
    })
    const proposed = calls.proposed[0] as {
      definition: { levels: { id: string; plural: string }[] }
    }
    expect(proposed.definition.levels.find((each) => each.id === 'month')?.plural).toBe('moons')
    expect(calls.applied[0]).toEqual({ strategies: {} })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(await screen.findByText('Calendar saved')).toBeInTheDocument()
  })

  it('reviews the impact of a change: a choice per broken date, bulk actions, undo', async () => {
    const calls = proposals({
      items: [
        item('aria', 'Aria', 'start', {
          old: '30 Feb 1000',
          after: '2 Mar 1000',
          pinned: '1 Mar 1000',
        }),
        item('bram', 'Bram', 'start', {
          old: '31 Apr 1001',
          after: null,
          problem: 'The date no longer exists.',
          constrained: '30 Apr 1001',
        }),
      ],
    })
    const writes = serveVault({
      kinds: [...KINDS, kind('calendar', 'Calendar')],
      rows: [
        ...defaultRows().filter((entity) => entity.id !== 'd1'),
        dimensionRow('d1', 'Aetheria', 'c-greg'),
        calendarRow('c-greg', 'Gregorian', 'gregorian'),
      ],
      changesets: [
        {
          id: 'cs1',
          summary: 'Edited the calendar “Gregorian” (2 records affected)',
          entities: [],
          changes: [],
        },
      ],
    })
    await renderApp('/v/v1/calendars/c-greg/edit')
    await screen.findByRole('heading', { name: 'Gregorian' })
    await replace(within(level('month')).getByRole('textbox', { name: /plural$/ }), 'moons')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    const dialog = await screen.findByRole('dialog', { name: 'Review the calendar change' })
    expect(dialog).toHaveTextContent('2 time points change, 1 of them broken.')
    const rows = within(dialog).getAllByRole('row')
    expect(rows.map((each) => each.textContent)).toEqual([
      'RecordNowAfterChoice',
      expect.stringContaining('Aria (start)30 Feb 10002 Mar 1000'),
      expect.stringContaining('Bram (start)31 Apr 1001The date no longer exists.'),
    ])
    const apply = within(dialog).getByRole('button', { name: 'Apply the change' })
    expect(apply).toBeDisabled()
    expect(dialog).toHaveTextContent('1 broken date needs a choice.')

    // "Keep all dates" doesn't decide broken dates; "Keep all moments" does.
    await userEvent.click(within(dialog).getByRole('button', { name: 'Keep all dates' }))
    expect(apply).toBeDisabled()
    await userEvent.selectOptions(
      within(dialog).getByRole('combobox', { name: 'Choice for Bram start' }),
      'constrain',
    )
    expect(within(dialog).getByRole('row', { name: 'Bram start' })).toHaveTextContent('30 Apr 1001')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Keep all moments' }))
    // Keeping the moment shows the date it reads as once the calendar changes.
    expect(within(dialog).getByRole('row', { name: 'Aria start' })).toHaveTextContent(
      '30 Feb 10001 Mar 1000',
    )
    await userEvent.selectOptions(
      within(dialog).getByRole('combobox', { name: 'Choice for Aria start' }),
      'keep_date',
    )
    await userEvent.click(apply)
    await waitFor(() => {
      expect(calls.applied).toHaveLength(1)
    })
    expect(calls.applied[0]).toEqual({
      strategies: { 'time_point/aria/start': 'keep_date', 'time_point/bram/start': 'pin_moment' },
    })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    // The toast undoes the change.
    // Sonner keeps the earlier tests' toasts: the newest is last.
    const toast = (await screen.findAllByText(/^Calendar saved/))
      .at(-1)
      ?.closest('[data-sonner-toast]')
    if (!(toast instanceof HTMLElement)) throw new Error('no toast')
    await userEvent.click(within(toast).getByRole('button', { name: 'Undo' }))
    await waitFor(() => {
      expect(writes.some((write) => write.path.endsWith('/changes/cs1/revert'))).toBe(true)
    })
  })

  it('asks again when the proposal went stale, and shows refused choices', async () => {
    const calls = proposals({
      items: [
        item('bram', 'Bram', 'start', {
          old: '31 Apr 1001',
          after: null,
          problem: 'The date no longer exists.',
        }),
      ],
      refuse: [
        {
          status: 422,
          code: 'proposal_unresolved',
          detail: 'Some records need a strategy.',
          errors: [
            { path: 'strategies.time_point/bram/start', code: 'x', message: 'Pick another one.' },
          ],
        },
        { status: 409, code: 'proposal_stale', detail: 'The calendar changed.' },
      ],
    })
    vault()
    await renderApp('/v/v1/calendars/c-greg/edit')
    await screen.findByRole('heading', { name: 'Gregorian' })
    await replace(within(level('month')).getByRole('textbox', { name: /plural$/ }), 'moons')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.selectOptions(
      within(dialog).getByRole('combobox', { name: 'Choice for Bram start' }),
      'keep_date',
    )
    await userEvent.click(within(dialog).getByRole('button', { name: 'Apply the change' }))
    expect(await within(dialog).findByText('Pick another one.')).toBeInTheDocument()

    await userEvent.click(within(dialog).getByRole('button', { name: 'Apply the change' }))
    expect(await within(dialog).findByRole('button', { name: 'Preview again' })).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Preview again' }))
    await waitFor(() => {
      expect(calls.proposed).toHaveLength(2)
    })
    expect(await screen.findByRole('button', { name: 'Apply the change' })).toBeInTheDocument()
  }, 30_000)

  it('edits reforms, cycles, eras, overlays and formats', async () => {
    vault()
    await renderApp('/v/v1/calendars/new?dimension=d1')
    await userEvent.selectOptions(
      await screen.findByRole('combobox', { name: 'Start from' }),
      'gregorian',
    )
    const preview = screen.getByRole('complementary', { name: 'Preview' })
    expect(within(preview).getByText('The calendar compiles.')).toBeInTheDocument()

    // A reform: a copy of the rules starting at a date of this calendar.
    const reforms = screen.getByRole('region', { name: 'Reforms' })
    await userEvent.click(within(reforms).getByRole('button', { name: /Reform/ }))
    expect(within(reforms).getAllByRole('tab')).toHaveLength(2)
    expect(within(reforms).getAllByRole('tab')[1]).toHaveAttribute('aria-selected', 'true')

    // Overlays: a moon with a period in days.
    const overlays = screen.getByRole('region', { name: 'Overlays' })
    await userEvent.click(within(overlays).getByRole('button', { name: 'Overlay' }))
    expect(within(overlays).getAllByRole('listitem').length).toBeGreaterThan(0)

    // Formats: suggestions while typing a token, an unknown token is an error.
    const formats = screen.getByRole('region', { name: 'Formats' })
    const day = within(formats).getByRole('textbox', { name: 'day format' })
    await userEvent.type(day, '{{ye')
    const tokens = within(formats).getByRole('group', { name: 'day tokens' })
    await userEvent.click(within(tokens).getByRole('button', { name: '{year}' }))
    expect(day).toHaveValue('{year}')
    await userEvent.clear(day)
    await userEvent.type(day, '{{nope}')
    expect(
      await within(formats).findByText('Unknown token: type { to see the tokens.'),
    ).toBeInTheDocument()

    // Renaming a level renames it in cycles, formats and their tokens too.
    await userEvent.clear(day)
    await userEvent.type(day, '{{day}')
    await replace(within(level('day')).getByRole('textbox', { name: /id$/ }), 'sol')
    expect(within(formats).getByRole('textbox', { name: 'day format' })).toHaveValue('{sol}')

    // Cycles of the reform (selected): a second one beside the week.
    const cycles = screen.getByRole('region', { name: 'Cycles' })
    await userEvent.click(within(cycles).getByRole('button', { name: 'Cycle' }))

    // Eras: a third one, after AD.
    const eras = screen.getByRole('region', { name: 'Eras' })
    await userEvent.click(within(eras).getByRole('button', { name: 'Era' }))

    await userEvent.click(screen.getByRole('tab', { name: 'JSON' }))
    const json = JSON.parse(
      screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'Definition JSON' }).value,
    ) as {
      regimes: { cycles?: { id: string; level: string }[] }[]
      eras?: unknown[]
      overlays?: unknown[]
      formats?: Record<string, string>
    }
    expect(json.regimes).toHaveLength(2)
    expect(json.regimes[0]?.cycles?.[0]).toMatchObject({ id: 'week', level: 'sol' })
    expect(json.regimes[0]?.cycles).toHaveLength(1)
    expect(json.regimes[1]?.cycles).toHaveLength(2)
    expect(json.eras).toHaveLength(3)
    // Gregorian has two overlays (the moon and the seasons) and the new one.
    expect(json.overlays).toHaveLength(3)
    expect(json.formats).toEqual({ sol: '{sol}' })
  }, 30_000)
})

interface Answer {
  status: number
  code: string
  detail: string
  errors?: { path: string; code: string; message: string }[]
}

function item(
  id: string,
  name: string,
  slot: string,
  shown: {
    old: string
    after: string | null
    /** The old moment in the edited calendar (keeping the moment). */
    pinned?: string
    problem?: string
    constrained?: string
  },
) {
  return {
    key: `time_point/${id}/${slot}`,
    record_type: 'time_point',
    id,
    slot,
    entity_id: id,
    name,
    old_t: '100',
    old_status: 'ok',
    new_t: shown.after === null ? null : '200',
    status: shown.problem === undefined ? 'ok' : 'invalid_date',
    problem: shown.problem === undefined ? null : { code: 'invalid_date', message: shown.problem },
    old_display: shown.old,
    new_display: shown.after,
    pinned_display: shown.pinned ?? shown.old,
    constrained_t: shown.constrained === undefined ? null : '150',
    constrained_display: shown.constrained ?? null,
    strategies:
      shown.constrained === undefined
        ? ['keep_date', 'pin_moment']
        : ['keep_date', 'pin_moment', 'constrain'],
  }
}

/** Serves the calendar's proposals; `refuse` answers the applies in turn before one succeeds. */
function proposals({ items, refuse = [] }: { items: unknown[]; refuse?: Answer[] }) {
  const calls = { proposed: [] as unknown[], applied: [] as unknown[] }
  const answers = [...refuse]
  const problems = items.filter((each) => (each as { problem: unknown }).problem !== null).length
  server.use(
    http.post('*/api/v1/vaults/v1/calendars/c-greg/proposals', async ({ request }) => {
      const body = (await request.json()) as { definition: unknown }
      calls.proposed.push(body)
      return HttpResponse.json({
        id: `p${calls.proposed.length}`,
        calendar_id: 'c-greg',
        base_revision: 1,
        created_at: '2026-10-11T00:00:00Z',
        expires_at: '2026-10-11T01:00:00Z',
        display_calendar_id: 'c-greg',
        definition: body.definition,
        items,
        series: [],
        summary: {
          affected: items.length,
          changed: items.length,
          problems,
          by_problem: {},
          series: 0,
        },
      })
    }),
    http.post('*/api/v1/vaults/v1/calendars/c-greg/proposals/:id/apply', async ({ request }) => {
      const answer = answers.shift()
      if (answer !== undefined) {
        return HttpResponse.json(
          { type: 'about:blank', title: 'Refused', errors: [], ...answer },
          { status: answer.status, headers: { 'Content-Type': 'application/problem+json' } },
        )
      }
      calls.applied.push(await request.json())
      return HttpResponse.json({
        calendar: {},
        kept: 0,
        pinned: 0,
        constrained: 0,
        accepted: 0,
        backup: null,
        affected: { entities: [], dimensions: [], time_changed: true, search_changed: false },
      })
    }),
  )
  return calls
}
