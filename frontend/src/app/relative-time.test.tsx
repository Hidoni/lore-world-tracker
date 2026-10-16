import type { EndSpec, TimePoint } from '@lore/chronology'
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from '@tanstack/react-router'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { useState, type ReactNode } from 'react'
import { describe, expect, it } from 'vitest'

import { ApiError } from '@/api'
import { AppProviders } from '@/app/providers'
import { prefetchMeta } from '@/test/render-app'
import { createQueryClient } from '@/app/query-client'
import { globalSearchSchema, parseSearch, stringifySearch } from '@/app/search'
import { EndSpecPicker, TimePointPicker, timeWriteProblem } from '@/core/time'
import { presetLenses } from '@/test/calendars'
import { defaultRows, kind, KINDS, row, serveVault } from '@/test/fake-vault'
import { server } from '@/test/msw'

const START = 63_839_000_000n

interface ResolveBody {
  items: { time_point: TimePoint; end?: EndSpec | null }[]
}

/** A fake `/time/resolve`: events e1 (ok), e2 (a series), e3 (unset), e4 (in a cycle). */
function serveResolve() {
  const bodies: ResolveBody[] = []
  server.use(
    http.post('*/api/v1/vaults/v1/time/resolve', async ({ request }) => {
      const body = (await request.json()) as ResolveBody
      bodies.push(body)
      return HttpResponse.json({
        calendar_id: 'gregorian',
        items: body.items.map(({ time_point, end }) => {
          const anchor = time_point.anchor
          const target = anchor.kind === 'relative' ? anchor.ref.id : null
          const offset =
            anchor.kind === 'relative' && anchor.offset.kind === 'base'
              ? BigInt(anchor.offset.units)
              : 0n
          const t = START + offset
          const ok = (at: bigint, precision: string, display: string) => ({
            t: at.toString(),
            status: 'ok',
            extent: { lo: at.toString(), hi: (at + 1n).toString() },
            precision,
            approximate: false,
            display,
            error: null,
            default_precision: target === null ? null : 'day',
          })
          const failed = (status: string, code: string) => ({
            t: null,
            status,
            extent: null,
            precision: null,
            approximate: false,
            display: null,
            error: { code, message: code, path: 'anchor.ref' },
            default_precision: null,
          })
          const start =
            target === 'e3'
              ? failed('unresolved_ref', 'unresolved_ref')
              : target === 'e4'
                ? failed('cycle', 'time_cycle')
                : ok(t, time_point.precision, `24 December AD 2023${offset ? ' (+1 h)' : ''}`)
          const endT =
            end?.kind === 'duration' && end.duration.kind === 'base'
              ? START + BigInt(end.duration.units)
              : end?.kind === 'end_of_time'
                ? 10n ** 40n
                : START
          return {
            start,
            end: end === undefined || end === null ? null : ok(endT, 'base', `t = ${endT}`),
          }
        }),
      })
    }),
  )
  return bodies
}

function vault() {
  serveVault({
    kinds: [...KINDS, kind('event', 'Event')],
    rows: [
      ...defaultRows(),
      row('e1', 'event', 'Coronation', { ext: { recurrence: null } }),
      row('e2', 'event', 'Harvest festival', { ext: { recurrence: { freq: 'yearly' } } }),
      row('e3', 'event', 'Unset day', { ext: { recurrence: null } }),
      row('e4', 'event', 'Loop', { ext: { recurrence: null } }),
    ],
  })
  return serveResolve()
}

async function renderWithRouter(element: ReactNode) {
  const root = createRootRoute({
    validateSearch: (search) => globalSearchSchema.parse(search),
    component: () => <>{element}</>,
  })
  const router = createRouter({
    routeTree: root,
    history: createMemoryHistory({ initialEntries: ['/'] }),
    parseSearch,
    stringifySearch,
  })
  const queryClient = createQueryClient()
  queryClient.setDefaultOptions({ queries: { retry: false } })
  await prefetchMeta(queryClient)
  render(
    <AppProviders queryClient={queryClient}>
      <RouterProvider router={router} />
    </AppProviders>,
  )
  await act(() => router.load())
}

function Picker() {
  const { dimension, lenses } = presetLenses('gregorian')
  const [value, setValue] = useState<TimePoint | null>(null)
  return (
    <>
      <TimePointPicker
        vault="v1"
        dimension={dimension}
        lenses={lenses}
        value={null}
        onChange={setValue}
        owner={{ type: 'event', id: 'e9', slot: 'start' }}
      />
      <pre data-testid="value">{JSON.stringify(value)}</pre>
    </>
  )
}

const emitted = () => JSON.parse(screen.getByTestId('value').textContent) as TimePoint | null

async function pickTarget(name: string) {
  await userEvent.click(await screen.findByRole('tab', { name: 'Relative' }))
  await userEvent.type(
    await screen.findByRole('textbox', { name: 'Find the target' }),
    name.slice(0, 3),
  )
  const list = await screen.findByRole('list', { name: 'Targets' })
  await userEvent.click(within(list).getByRole('button', { name }))
}

describe('relative anchors', () => {
  it('anchors to an event’s edge with an offset, at the default precision', async () => {
    const bodies = vault()
    await renderWithRouter(<Picker />)
    await pickTarget('Coronation')
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Edge' }), 'End')
    await userEvent.type(screen.getByRole('textbox', { name: 'Offset in seconds' }), '3,600')
    await waitFor(() => {
      expect(emitted()).toEqual({
        anchor: {
          kind: 'relative',
          ref: { type: 'event', id: 'e1', slot: 'end' },
          offset: { kind: 'base', units: '3600' },
        },
        precision: 'day',
        approximate: false,
      })
    })
    expect(screen.getByTestId('relative-resolution')).toHaveTextContent(
      '24 December AD 2023 (+1 h) · precision day (default)',
    )
    expect(screen.getByRole('option', { name: 'Default (day)' })).toBeInTheDocument()
    // A probe at an explicit precision learns the default; the final point is then resolved.
    const asked = bodies.map((body) => body.items[0]?.time_point.precision)
    expect(asked).toContain('base')
    expect(asked.at(-1)).toBe('day')
    // No occurrence key for a one-off event.
    expect(screen.queryByRole('textbox', { name: 'Occurrence key' })).not.toBeInTheDocument()

    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Precision' }), 'hour')
    await waitFor(() => {
      expect(emitted()?.precision).toBe('hour')
    })
  })

  it('takes an occurrence key for a recurring event', async () => {
    vault()
    await renderWithRouter(<Picker />)
    await pickTarget('Harvest festival')
    await userEvent.type(await screen.findByRole('textbox', { name: 'Occurrence key' }), '12')
    await waitFor(() => {
      expect(emitted()?.anchor).toMatchObject({
        ref: { type: 'event', id: 'e2', slot: 'start', occurrence: '12' },
      })
    })
  })

  it('shows unresolvable targets, cycles and self references inline', async () => {
    vault()
    await renderWithRouter(<Picker />)
    await pickTarget('Unset day')
    expect(await screen.findByRole('alert')).toHaveTextContent('The target has no moment')
    expect(emitted()).toBeNull()

    await userEvent.click(screen.getByRole('button', { name: 'Change' }))
    await userEvent.type(screen.getByRole('textbox', { name: 'Find the target' }), 'Lo')
    await userEvent.click(
      within(await screen.findByRole('list', { name: 'Targets' })).getByRole('button', {
        name: /Loop/,
      }),
    )
    expect(await screen.findByRole('alert')).toHaveTextContent('This would make a cycle')
    expect(emitted()).toBeNull()
  })

  it('refuses a relative anchor to its own slot', async () => {
    vault()
    function Own() {
      const { dimension, lenses } = presetLenses('gregorian')
      return (
        <TimePointPicker
          vault="v1"
          dimension={dimension}
          lenses={lenses}
          value={null}
          onChange={() => undefined}
          owner={{ type: 'event', id: 'e1', slot: 'start' }}
        />
      )
    }
    await renderWithRouter(<Own />)
    await pickTarget('Coronation')
    expect(await screen.findByRole('alert')).toHaveTextContent('can’t be relative to itself')
  })
})

describe('EndSpecPicker', () => {
  const start: TimePoint = {
    anchor: { kind: 'absolute', t: START.toString() },
    precision: 'base',
    approximate: false,
  }
  function Ends() {
    const { dimension, lenses } = presetLenses('gregorian')
    const [value, setValue] = useState<EndSpec | null>(null)
    return (
      <>
        <EndSpecPicker
          vault="v1"
          dimension={dimension}
          lenses={lenses}
          start={start}
          value={null}
          onChange={setValue}
        />
        <pre data-testid="end">{JSON.stringify(value)}</pre>
      </>
    )
  }
  const end = () => JSON.parse(screen.getByTestId('end').textContent) as EndSpec | null

  it('refuses an end before the start and takes the other kinds', async () => {
    vault()
    await renderWithRouter(<Ends />)
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'End kind' }), 'A duration')
    await userEvent.selectOptions(
      screen.getByRole('combobox', { name: 'End after the start sign' }),
      '− earlier',
    )
    await userEvent.type(
      screen.getByRole('textbox', { name: 'End after the start in seconds' }),
      '10',
    )
    expect(await screen.findByRole('alert')).toHaveTextContent('The end comes before the start.')
    expect(end()).toBeNull()

    await userEvent.selectOptions(
      screen.getByRole('combobox', { name: 'End after the start sign' }),
      '+ later',
    )
    await waitFor(() => {
      expect(end()).toEqual({ kind: 'duration', duration: { kind: 'base', units: '10' } })
    })
    await userEvent.selectOptions(
      screen.getByRole('combobox', { name: 'End kind' }),
      'Until the end of time',
    )
    await waitFor(() => {
      expect(end()).toEqual({ kind: 'end_of_time' })
    })
  })
})

describe('timeWriteProblem', () => {
  it('explains cycles and broken constraints', () => {
    const cycle = new ApiError({
      status: 409,
      code: 'time_cycle',
      title: 'Cycle',
      detail: 'A cycle.',
      context: { path: ['event a start', 'event b end', 'event a start'] },
    })
    expect(timeWriteProblem(cycle)).toBe(
      'This would make a cycle: event a start → event b end → event a start.',
    )
    const constraint = new ApiError({
      status: 422,
      code: 'time_constraint',
      title: 'Constraint',
      detail: 'Broken.',
      context: {
        records: [{ record_type: 'event', id: 'x', slot: 'end', code: 'end_before_start' }],
      },
    })
    expect(timeWriteProblem(constraint)).toBe('The end would come before the start.')
    expect(timeWriteProblem(new Error('other'))).toBeNull()
  })
})
