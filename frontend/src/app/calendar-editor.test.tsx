import { PRESETS } from '@lore/chronology/presets'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

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

describe('calendar editor', () => {
  it('builds the alternating-years calendar from blank, matching the preset', async () => {
    vault()
    await renderApp('/v/v1/calendars/new?dimension=d1')
    expect(await screen.findByRole('heading', { name: 'New calendar' })).toBeInTheDocument()

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
    await screen.findByRole('heading', { name: 'New calendar' })
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

  it('saves an existing calendar, and explains when a proposal is needed', async () => {
    const writes = vault()
    await renderApp('/v/v1/calendars/c-greg/edit')
    expect(await screen.findByRole('heading', { name: 'Gregorian' })).toBeInTheDocument()
    await replace(within(level('month')).getByRole('textbox', { name: /plural$/ }), 'moons')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => {
      expect(writes.find((write) => write.method === 'PATCH')).toBeDefined()
    })
    const saved = writes.find((write) => write.method === 'PATCH')?.body as {
      ext: { definition: { levels: { id: string; plural: string }[] } }
    }
    expect(saved.ext.definition.levels.find((each) => each.id === 'month')?.plural).toBe('moons')

    server.use(
      http.patch('*/api/v1/vaults/v1/entities/c-greg', () =>
        HttpResponse.json(
          {
            type: 'about:blank',
            status: 409,
            code: 'conflict',
            title: 'Conflict',
            detail: 'The calendar has dependents.',
            context: { dependents: 3, proposals: '/calendars/c-greg/proposals' },
          },
          { status: 409, headers: { 'Content-Type': 'application/problem+json' } },
        ),
      ),
    )
    await replace(within(level('month')).getByRole('textbox', { name: /plural$/ }), 'lunas')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      '3 time points depend on this calendar: changing it goes through a proposal',
    )
  })
})
