import { instantiatePreset, PRESETS } from '@lore/chronology/presets'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { blankDefinition } from '@/core/time/calendar-editor'
import { AXE_TIMEOUT, expectAccessible } from '@/test/axe'
import { calendarRow, dimensionRow } from '@/test/calendars'
import { defaultRows, kind, KINDS, row, serveVault } from '@/test/fake-vault'
import { server } from '@/test/msw'
import { renderApp } from '@/test/render-app'

const KINDS_WITH_TIME = [
  ...KINDS,
  kind('calendar', 'Calendar', { capabilities: { ...KINDS[0]?.capabilities, is_system: true } }),
  kind('event', 'Event'),
]

/** The presets, the preview and the wizard endpoints; returns the bodies they received. */
function serveWizard(options: { createProblem?: object } = {}) {
  const seen: { previews: unknown[]; created: unknown[] } = { previews: [], created: [] }
  server.use(
    http.get('*/api/v1/vaults/v1/calendars/presets', () =>
      HttpResponse.json({
        items: [...PRESETS.values()].map((preset) => ({
          id: preset.id,
          name: preset.name,
          description: preset.description,
          origin: preset.origin,
          duration_seconds: preset.requires.duration_seconds,
          definition: preset.definition,
        })),
      }),
    ),
    http.post('*/api/v1/vaults/v1/calendars/preview', async ({ request }) => {
      seen.previews.push(await request.json())
      return HttpResponse.json({
        ok: true,
        errors: [],
        definition: {},
        samples: [
          { t: '0', display: '1 January AD 1, 00:00:00', fields: {} },
          { t: '31536000', display: '1 January AD 2, 00:00:00', fields: {} },
        ],
      })
    }),
    http.post('*/api/v1/vaults/v1/dimensions', async ({ request }) => {
      seen.created.push(await request.json())
      if (options.createProblem !== undefined) {
        return HttpResponse.json(options.createProblem, {
          status: 422,
          headers: { 'Content-Type': 'application/problem+json' },
        })
      }
      const entity = (id: string, kindKey: string, name: string) => ({
        ...row(id, kindKey, name),
        origin_timeline_id: null,
        slug: name.toLowerCase(),
        body_schema_version: null,
        icon: null,
        color: null,
        cover_media_id: null,
        sort_key: null,
        ext: null,
        created_at: '2026-10-11T10:00:00.000000+00:00',
        updated_at: '2026-10-11T10:00:00.000000+00:00',
      })
      return HttpResponse.json(
        {
          dimension: entity('new-d', 'dimension', 'Midgard'),
          prime_timeline: entity('new-t', 'timeline', 'Midgard prime'),
          calendar: entity('new-c', 'calendar', 'Gregorian'),
        },
        { status: 201 },
      )
    }),
  )
  return seen
}

const dialog = () => screen.getByRole('dialog', { name: 'New dimension' })
const next = () => userEvent.click(within(dialog()).getByRole('button', { name: 'Next' }))

/** Steps 1–3 with valid answers, then the preset step. */
async function throughDuration(duration: string) {
  await userEvent.type(within(dialog()).getByLabelText('Name'), 'Midgard')
  await next()
  await next()
  await userEvent.type(within(dialog()).getByLabelText('Duration (seconds)'), duration)
  await next()
}

describe('vault home', () => {
  it('invites to create the first dimension, and lists dimensions', async () => {
    serveVault({ rows: defaultRows().filter((entity) => entity.kind !== 'dimension') })
    await renderApp('/v/v1')
    expect(await screen.findByText(/A dimension is a universe/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Create dimension' })).toBeInTheDocument()
  })

  it('links to each dimension, and readers get no create button', async () => {
    serveVault()
    await renderApp('/v/v1', undefined, { readOnly: true })
    // The page's list, not the sidebar's section of the same name.
    const list = await within(screen.getByRole('main')).findByRole('region', { name: 'Dimensions' })
    expect(await within(list).findByRole('link', { name: 'Aetheria' })).toHaveAttribute(
      'href',
      '/v/v1/d/d1',
    )
    expect(screen.queryByRole('button', { name: 'Create dimension' })).not.toBeInTheDocument()
  })
})

describe('dimension wizard', () => {
  it('walks through every step and creates the dimension', async () => {
    serveVault({ rows: defaultRows().filter((entity) => entity.kind !== 'dimension') })
    const seen = serveWizard()
    const { router } = await renderApp('/v/v1')
    await userEvent.click(await screen.findByRole('button', { name: 'Create dimension' }))

    // 1. Name: required.
    expect(within(dialog()).getByText('Step 1 of 5: Name')).toBeInTheDocument()
    expect(within(dialog()).getByRole('button', { name: 'Next' })).toBeDisabled()
    await userEvent.type(within(dialog()).getByLabelText('Name'), 'Midgard')
    await userEvent.type(within(dialog()).getByLabelText('Description'), 'Where it begins.')
    await next()

    // 2. Base unit: seconds by default, renamable.
    expect(within(dialog()).getByLabelText('Singular')).toHaveValue('second')
    await userEvent.clear(within(dialog()).getByLabelText('Abbreviation'))
    expect(within(dialog()).getByRole('button', { name: 'Next' })).toBeDisabled()
    await userEvent.type(within(dialog()).getByLabelText('Abbreviation'), 's')
    await next()

    // 3. Duration: a lifetime to start from.
    await userEvent.click(
      within(dialog()).getByRole('button', { name: '10^100 years of 365.25 days' }),
    )
    expect(within(dialog()).getByText(/= 3\.156 × 10\^107/)).toBeInTheDocument()
    await next()

    // 4. First calendar: preset, live preview.
    expect(within(dialog()).getByRole('button', { name: 'Next' })).toBeDisabled()
    await userEvent.selectOptions(within(dialog()).getByLabelText('Preset'), 'Gregorian')
    expect(within(dialog()).getByLabelText('Calendar name')).toHaveValue('Gregorian')
    const preview = await within(dialog()).findByRole('region', { name: 'Preview' })
    expect(within(preview).getByText('1 January AD 2, 00:00:00')).toBeInTheDocument()
    expect(seen.previews.at(-1)).toMatchObject({
      time_spec: { base_unit: { singular: 'second', plural: 'seconds', abbr: 's' } },
      source: { preset: { id: 'gregorian', seconds_per_base_unit: { num: '1', den: '1' } } },
    })
    await next()

    // 5. Review, then create.
    expect(within(dialog()).getByText('Midgard')).toBeInTheDocument()
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Create dimension' }))
    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/v/v1/d/new-d')
    })
    expect(seen.created).toEqual([
      {
        name: 'Midgard',
        summary: 'Where it begins.',
        ext: {
          base_unit: { singular: 'second', plural: 'seconds', abbr: 's' },
          duration: (10n ** 100n * 31_557_600n).toString(),
        },
        calendar: {
          name: 'Gregorian',
          source: {
            preset: { id: 'gregorian', seconds_per_base_unit: { num: '1', den: '1' }, origin: '0' },
          },
        },
      },
    ])
  })

  it('says when the duration is too short for the preset', async () => {
    serveVault()
    serveWizard()
    await renderApp('/v/v1')
    await userEvent.click(await screen.findByRole('button', { name: 'Create dimension' }))
    await throughDuration('1000')
    await userEvent.selectOptions(within(dialog()).getByLabelText('Preset'), 'Gregorian')
    expect(within(dialog()).getByRole('alert')).toHaveTextContent(
      'This calendar needs the dimension to last at least 63,089,134,500 seconds',
    )
    expect(within(dialog()).getByRole('button', { name: 'Next' })).toBeDisabled()
    // A calendar without absolute anchors fits any duration.
    await userEvent.selectOptions(within(dialog()).getByLabelText('Preset'), '360-day')
    await within(dialog()).findByRole('region', { name: 'Preview' })
    expect(within(dialog()).getByRole('button', { name: 'Next' })).toBeEnabled()
  })

  it('designs a custom first calendar from scratch and creates the dimension with it', async () => {
    serveVault({ rows: defaultRows().filter((entity) => entity.kind !== 'dimension') })
    const seen = serveWizard()
    const { router } = await renderApp('/v/v1')
    await userEvent.click(await screen.findByRole('button', { name: 'Create dimension' }))
    await throughDuration('1e12')

    await userEvent.click(within(dialog()).getByLabelText('Custom calendar'))
    expect(within(dialog()).queryByLabelText('Preset')).not.toBeInTheDocument()
    expect(within(dialog()).getByRole('button', { name: 'Next' })).toBeDisabled()
    await userEvent.type(within(dialog()).getByLabelText('Calendar name'), 'Moonfall Reckoning')
    expect(within(dialog()).getByLabelText('Begin with')).toHaveValue('')
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Design calendar…' }))

    // The calendar editor, on the wizard's base unit; Cancel keeps nothing.
    await within(dialog()).findByRole('heading', { name: 'Design the first calendar' })
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Cancel' }))
    expect(within(dialog()).getByRole('button', { name: 'Design calendar…' })).toBeInTheDocument()
    expect(seen.previews).toEqual([])

    await userEvent.click(within(dialog()).getByRole('button', { name: 'Design calendar…' }))
    await userEvent.click(
      await within(dialog()).findByRole('button', { name: 'Use this calendar' }),
    )
    expect(within(dialog()).getByRole('button', { name: 'Edit calendar…' })).toBeInTheDocument()
    await within(dialog()).findByRole('region', { name: 'Preview' })
    expect(seen.previews.at(-1)).toEqual({
      time_spec: {
        base_unit: { singular: 'second', plural: 'seconds', abbr: 's' },
        duration: '1000000000000',
      },
      source: { definition: blankDefinition() },
    })
    await next()

    expect(within(dialog()).getByText('Moonfall Reckoning (custom calendar)')).toBeInTheDocument()
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Create dimension' }))
    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/v/v1/d/new-d')
    })
    expect(seen.created).toEqual([
      expect.objectContaining({
        calendar: { name: 'Moonfall Reckoning', source: { definition: blankDefinition() } },
      }),
    ])
  })

  it('starts a custom calendar from a preset scaled to the base unit', async () => {
    serveVault()
    const seen = serveWizard()
    await renderApp('/v/v1')
    await userEvent.click(await screen.findByRole('button', { name: 'Create dimension' }))
    await userEvent.type(within(dialog()).getByLabelText('Name'), 'Midgard')
    await next()
    await userEvent.clear(within(dialog()).getByLabelText('Divided by'))
    await userEvent.type(within(dialog()).getByLabelText('Divided by'), '1000')
    await next()
    await userEvent.type(within(dialog()).getByLabelText('Duration (seconds)'), '1e20')
    await next()

    await userEvent.click(within(dialog()).getByLabelText('Custom calendar'))
    await userEvent.selectOptions(within(dialog()).getByLabelText('Begin with'), 'Shire Reckoning')
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Design calendar…' }))
    await userEvent.click(
      await within(dialog()).findByRole('button', { name: 'Use this calendar' }),
    )
    await within(dialog()).findByRole('region', { name: 'Preview' })
    const shire = PRESETS.get('shire-reckoning')
    expect(shire).toBeDefined()
    if (shire === undefined) return
    expect(seen.previews.at(-1)).toMatchObject({
      source: { definition: instantiatePreset(shire, { num: 1n, den: 1000n }) },
    })

    // Start over goes back to choosing where to begin.
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Start over' }))
    expect(within(dialog()).getByRole('button', { name: 'Design calendar…' })).toBeInTheDocument()
    expect(within(dialog()).getByRole('button', { name: 'Next' })).toBeDisabled()
  })

  it('shows the server’s problems with a way back to their step', async () => {
    serveVault()
    serveWizard({
      createProblem: {
        type: 'about:blank',
        status: 422,
        code: 'validation_error',
        title: 'Invalid input',
        detail: 'Invalid input.',
        errors: [{ path: 'ext.duration', code: 'invalid_value', message: 'Too long.' }],
      },
    })
    await renderApp('/v/v1')
    await userEvent.click(await screen.findByRole('button', { name: 'Create dimension' }))
    await throughDuration('1e30')
    await userEvent.selectOptions(within(dialog()).getByLabelText('Preset'), '360-day')
    await within(dialog()).findByRole('region', { name: 'Preview' })
    await next()
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Create dimension' }))
    const alert = await within(dialog()).findByRole('alert')
    expect(alert).toHaveTextContent('Too long.')
    await userEvent.click(within(alert).getByRole('button', { name: 'Go to Duration' }))
    expect(within(dialog()).getByText('Step 3 of 5: Duration')).toBeInTheDocument()
  })
})

describe('dimension overview', () => {
  function vault() {
    return serveVault({
      kinds: KINDS_WITH_TIME,
      rows: [
        ...defaultRows().filter((entity) => entity.id !== 'd1'),
        dimensionRow('d1', 'Aetheria', 'c-greg', { duration: 10n ** 30n }),
        calendarRow('c-greg', 'Gregorian', 'gregorian'),
        calendarRow('c-360', 'Simple 360', 'simple-360'),
        row('e1', 'event', 'Coronation'),
      ],
    })
  }

  it('shows the time spec, calendars, timelines, counts and recent events', async () => {
    vault()
    await renderApp('/v/v1/d/d1')
    expect(await screen.findByRole('heading', { name: 'Aetheria', level: 1 })).toBeInTheDocument()
    const time = screen.getByRole('region', { name: 'Time' })
    expect(within(time).getByText('t = 1 × 10^30 s')).toBeInTheDocument()
    expect(within(time).getByText('Not set (all time is shown)')).toBeInTheDocument()
    const calendars = screen.getByRole('region', { name: 'Calendars' })
    await within(calendars).findByRole('link', { name: 'Simple 360' })
    expect(within(calendars).getAllByRole('listitem')[0]).toHaveTextContent('GregorianDefault')
    const stats = screen.getByRole('region', { name: 'Statistics' })
    await waitFor(() => {
      expect(stats).toHaveTextContent('Events1')
    })
    expect(
      await within(screen.getByRole('region', { name: 'Recent events' })).findByRole('link', {
        name: 'Coronation',
      }),
    ).toBeInTheDocument()
  })

  it(
    'has no serious accessibility violations',
    async () => {
      vault()
      await renderApp('/v/v1/d/d1')
      expect(await screen.findByRole('heading', { name: 'Aetheria', level: 1 })).toBeInTheDocument()
      await screen.findByRole('region', { name: 'Calendars' })
      await expectAccessible()
    },
    AXE_TIMEOUT,
  )

  it('switches the default calendar', async () => {
    const writes = vault()
    await renderApp('/v/v1/d/d1')
    const calendars = await screen.findByRole('region', { name: 'Calendars' })
    await userEvent.click(await within(calendars).findByRole('button', { name: 'Make default' }))
    await waitFor(() => {
      expect(writes.find((write) => write.method === 'PATCH')?.body).toMatchObject({
        ext: { default_calendar_id: 'c-360' },
      })
    })
  })

  it('explains why the duration can’t shrink, naming the records in the way', async () => {
    vault()
    server.use(
      http.patch('*/api/v1/vaults/v1/entities/d1', () =>
        HttpResponse.json(
          {
            type: 'about:blank',
            status: 422,
            code: 'time_constraint',
            title: 'Time constraint',
            detail: '1 time slot resolves after the new duration: move it first.',
            errors: [{ path: 'ext.duration', code: 'out_of_bounds', message: 'event e1: after.' }],
            context: { records: [{ record_type: 'event', id: 'e1', slot: 'start', t: '5000' }] },
          },
          { status: 422, headers: { 'Content-Type': 'application/problem+json' } },
        ),
      ),
    )
    await renderApp('/v/v1/d/d1')
    const time = await screen.findByRole('region', { name: 'Time' })
    await userEvent.click(within(time).getByRole('button', { name: 'Change' }))
    const input = within(time).getByRole('textbox', { name: 'Duration (seconds)' })
    await userEvent.clear(input)
    await userEvent.type(input, '1000')
    await userEvent.click(within(time).getByRole('button', { name: 'Save' }))
    const alert = await within(time).findByRole('alert')
    expect(alert).toHaveTextContent('1 time slot resolves after the new duration')
    expect(await within(alert).findByRole('link', { name: 'Coronation' })).toHaveAttribute(
      'href',
      '/v/v1/e/e1',
    )
  })
})
