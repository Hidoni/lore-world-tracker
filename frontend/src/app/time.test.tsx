import type { CalendarDefinition } from '@lore/chronology'
import { absoluteMoments, instantiatePreset, PRESETS } from '@lore/chronology/presets'
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from '@tanstack/react-router'
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'

import { AppProviders } from '@/app/providers'
import { createQueryClient } from '@/app/query-client'
import { globalSearchSchema, parseSearch, stringifySearch } from '@/app/search'
import { defaultRows, row, serveVault } from '@/test/fake-vault'

import { CalendarSelector, DimensionSwitcher, MomentDisplay, SpanDisplay } from '@/core/time'

const SECOND = { singular: 'second', plural: 'seconds', abbr: 's' }

function preset(id: string): CalendarDefinition {
  const found = PRESETS.get(id)
  if (found === undefined) throw new Error(`no preset ${id}`)
  return instantiatePreset(found, { num: 1n, den: 1n })
}

function calendar(id: string, name: string, presetId: string, dimension = 'd1') {
  const definition = preset(presetId)
  return row(id, 'calendar', name, {
    dimension_id: dimension,
    ext: {
      dimension_id: dimension,
      definition,
      definition_revision: 1,
      resolved_anchors: absoluteMoments(definition),
      compile_status: 'ok',
      compile_errors: [],
    },
  })
}

function dimension(id: string, name: string, defaultCalendar: string, present: bigint | null) {
  return row(id, 'dimension', name, {
    ext: {
      base_unit: SECOND,
      duration: (10n ** 40n).toString(),
      default_calendar_id: defaultCalendar,
      present: null,
      present_t: present === null ? null : present.toString(),
      time_status: 'ok',
      prime_timeline_id: `${id}-prime`,
    },
  })
}

/** 24 December AD 2023 in the Gregorian preset (seconds since 1 January AD 1). */
const DEC_2023 = 63_839_000_000n

function vault() {
  serveVault({
    rows: [
      ...defaultRows().filter((entity) => entity.id !== 'd1'),
      dimension('d1', 'Aetheria', 'c-greg', DEC_2023 + 800n * 86_400n),
      calendar('c-greg', 'Gregorian', 'gregorian'),
      calendar('c-360', 'Simple 360', 'simple-360'),
      dimension('d2', 'Shire', 'c-shire', null),
      calendar('c-shire', 'Shire Reckoning', 'shire-reckoning', 'd2'),
    ],
  })
}

/** Renders `element` under a router that has the global search params (`app/search.ts`). */
async function renderTime(element: ReactNode, path = '/') {
  const root = createRootRoute({
    validateSearch: (search) => globalSearchSchema.parse(search),
    component: () => <>{element}</>,
  })
  const router = createRouter({
    routeTree: root,
    history: createMemoryHistory({ initialEntries: [path] }),
    parseSearch,
    stringifySearch,
  })
  const queryClient = createQueryClient()
  queryClient.setDefaultOptions({ queries: { retry: false } })
  const utils = render(
    <AppProviders queryClient={queryClient}>
      <RouterProvider router={router} />
    </AppProviders>,
  )
  await act(() => router.load())
  return { ...utils, router }
}

async function pickCalendar(name: string) {
  await userEvent.click(await screen.findByRole('button', { name: /^Display calendar:/ }))
  await userEvent.click(await screen.findByRole('menuitemradio', { name }))
}

describe('time display', () => {
  it('formats moments in the display calendar, re-rendering when it changes', async () => {
    vault()
    const { router } = await renderTime(
      <>
        <CalendarSelector vault="v1" />
        <MomentDisplay vault="v1" dimension="d1" moment={{ t: DEC_2023, precision: 'day' }} />
        <SpanDisplay
          vault="v1"
          dimension="d1"
          start={{ t: DEC_2023, precision: 'day' }}
          end={{ t: DEC_2023 + 400_000n, precision: 'day' }}
        />
      </>,
    )
    expect(await screen.findByRole('button', { name: '24 December AD 2023' })).toBeInTheDocument()
    expect(screen.getByText('24 – 28 December AD 2023')).toBeInTheDocument()

    await pickCalendar('Simple 360')
    expect(await screen.findByRole('button', { name: '2053-06-08' })).toBeInTheDocument()
    expect(screen.getByText('2053-06-08 – 12')).toBeInTheDocument()
    expect(router.state.location.search).toMatchObject({ cal: 'c-360' })

    await pickCalendar('Absolute')
    expect(await screen.findByRole('button', { name: 't = 63,839,000,000 s' })).toBeInTheDocument()
  })

  it('shows huge years in scientific notation, and circa', async () => {
    vault()
    await renderTime(
      <>
        <MomentDisplay vault="v1" dimension="d1" moment={{ t: 10n ** 39n, precision: 'year' }} />
        <MomentDisplay
          vault="v1"
          dimension="d1"
          moment={{ t: DEC_2023, precision: 'month', approximate: true }}
        />
      </>,
    )
    expect(await screen.findByRole('button', { name: 'AD 3.169 × 10^31' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'c. December AD 2023' })).toBeInTheDocument()
  })

  it('lists the moment in every calendar of the dimension in its tooltip', async () => {
    vault()
    await renderTime(
      <MomentDisplay vault="v1" dimension="d1" moment={{ t: DEC_2023, precision: 'day' }} />,
    )
    await userEvent.hover(await screen.findByRole('button', { name: '24 December AD 2023' }))
    const tooltip = await screen.findByRole('tooltip')
    expect(within(tooltip).getByText('Gregorian').nextSibling).toHaveTextContent(
      '24 December AD 2023',
    )
    expect(within(tooltip).getByText('Simple 360').nextSibling).toHaveTextContent('2053-06-08')
    expect(within(tooltip).getByText('Absolute').nextSibling).toHaveTextContent(
      't = 63,839,000,000 s',
    )
    expect(within(tooltip).getByText('2 years before present')).toBeInTheDocument()
  })

  it('takes the calendar from the URL and remembers it per dimension', async () => {
    vault()
    const first = await renderTime(
      <MomentDisplay vault="v1" dimension="d1" moment={{ t: DEC_2023, precision: 'day' }} />,
      '/?cal=c-360',
    )
    expect(await screen.findByRole('button', { name: '2053-06-08' })).toBeInTheDocument()
    first.unmount()

    const second = await renderTime(
      <>
        <CalendarSelector vault="v1" />
        <MomentDisplay vault="v1" dimension="d1" moment={{ t: DEC_2023, precision: 'day' }} />
      </>,
    )
    expect(await screen.findByRole('button', { name: '24 December AD 2023' })).toBeInTheDocument()
    await pickCalendar('Simple 360')
    second.unmount()

    await renderTime(
      <MomentDisplay vault="v1" dimension="d1" moment={{ t: DEC_2023, precision: 'day' }} />,
    )
    expect(await screen.findByRole('button', { name: '2053-06-08' })).toBeInTheDocument()
  })

  it('switches the dimension, and with it the calendars offered', async () => {
    vault()
    await renderTime(
      <>
        <DimensionSwitcher vault="v1" />
        <CalendarSelector vault="v1" />
      </>,
    )
    expect(
      await screen.findByRole('button', { name: 'Display calendar: Gregorian' }),
    ).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Dimension: Aetheria' }))
    await userEvent.click(await screen.findByRole('menuitemradio', { name: 'Shire' }))
    expect(
      await screen.findByRole('button', { name: 'Display calendar: Shire Reckoning' }),
    ).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Display calendar: Shire Reckoning' }))
    const options = await screen.findAllByRole('menuitemradio')
    expect(options.map((option) => option.textContent)).toEqual(['Shire Reckoning', 'Absolute'])
  })
})
