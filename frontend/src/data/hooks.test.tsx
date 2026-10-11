import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'

import { problem, server } from '@/test/msw'

import { DataProvider, useMutations } from './context'
import { useCreateEntity, useEntity, useUpdateEntity } from './entities'
import { fieldErrors, isRevisionConflict } from './errors'
import { createHttpDataSource, createHttpMutations } from './http'
import type { Mutations } from './source'

const HUGE = '98765432109876543210987654321'

function event(id: string, revision: number, start = HUGE) {
  return {
    id,
    kind: 'event',
    name: `Event ${id}`,
    revision,
    ext: {
      start: { anchor: { kind: 'absolute', t: start }, precision: 'base' },
      start_t: start,
      end_t: start,
    },
  }
}

function wrapper(mutations: Mutations | null = createHttpMutations()) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <DataProvider dataSource={createHttpDataSource()} mutations={mutations}>
          {children}
        </DataProvider>
      </QueryClientProvider>
    )
  }
  return Wrapper
}

describe('data hooks', () => {
  it('read entities with their moments as bigint', async () => {
    server.use(http.get('*/api/v1/vaults/v/entities/e1', () => HttpResponse.json(event('e1', 1))))
    const { result } = renderHook(() => useEntity('v', 'e1'), { wrapper: wrapper() })
    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true)
    })
    const ext = result.current.data?.ext as Record<string, unknown>
    expect(ext.start_t).toBe(BigInt(HUGE))
    expect(ext.start).toEqual({ anchor: { kind: 'absolute', t: HUGE }, precision: 'base' })
  })

  it('refetch what a write affected', async () => {
    let reads = 0
    let revision = 1
    server.use(
      http.get('*/api/v1/vaults/v/entities/e1', () => {
        reads += 1
        return HttpResponse.json(event('e1', revision))
      }),
      http.patch('*/api/v1/vaults/v/entities/e1', () => {
        revision += 1
        return HttpResponse.json({
          entity: event('e1', revision, '7'),
          affected: { entities: ['e1'], dimensions: [], time_changed: true, search_changed: false },
        })
      }),
    )
    const Wrapper = wrapper()
    const { result } = renderHook(
      () => ({ entity: useEntity('v', 'e1'), update: useUpdateEntity('v') }),
      { wrapper: Wrapper },
    )
    await waitFor(() => {
      expect(result.current.entity.data?.revision).toBe(1)
    })
    let written: unknown
    await act(async () => {
      written = await result.current.update.mutateAsync({
        id: 'e1',
        body: { revision: 1, summary: '' },
      })
    })
    expect((written as { entity: { ext: { start_t: bigint } } }).entity.ext.start_t).toBe(7n)
    await waitFor(() => {
      expect(result.current.entity.data?.revision).toBe(2)
    })
    expect(reads).toBe(2)
  })

  it('expose revision conflicts and field errors', async () => {
    server.use(
      http.patch('*/api/v1/vaults/v/entities/e1', () =>
        problem(409, 'revision_conflict', 'Revision conflict', 'Someone saved first.'),
      ),
      http.post('*/api/v1/vaults/v/entities', () =>
        HttpResponse.json(
          {
            status: 422,
            code: 'validation_error',
            title: 'Invalid input',
            detail: 'Bad.',
            errors: [
              { path: 'body.name', code: 'required', message: 'A name is required.' },
              { path: 'body.ext.start', code: 'invalid_date', message: 'No such day.' },
            ],
          },
          { status: 422, headers: { 'Content-Type': 'application/problem+json' } },
        ),
      ),
    )
    const { result } = renderHook(
      () => ({ update: useUpdateEntity('v'), create: useCreateEntity('v') }),
      { wrapper: wrapper() },
    )
    let conflict: unknown
    await act(async () => {
      conflict = await result.current.update
        .mutateAsync({ id: 'e1', body: { revision: 1, summary: '' } })
        .catch((error: unknown) => error)
    })
    expect(isRevisionConflict(conflict)).toBe(true)
    let invalid: unknown
    await act(async () => {
      invalid = await result.current.create
        .mutateAsync({ kind: 'event', name: '', summary: '' })
        .catch((error: unknown) => error)
    })
    expect(isRevisionConflict(invalid)).toBe(false)
    expect(fieldErrors(invalid)).toEqual({
      name: 'A name is required.',
      'ext.start': 'No such day.',
    })
    expect(fieldErrors(new Error('x'))).toEqual({})
  })

  it('refuse writes without Mutations (reader and static contexts)', async () => {
    const { result } = renderHook(
      () => ({ mutations: useMutations(), create: useCreateEntity('v') }),
      { wrapper: wrapper(null) },
    )
    expect(result.current.mutations).toBeNull()
    let error: unknown
    await act(async () => {
      error = await result.current.create
        .mutateAsync({ kind: 'event', name: 'x', summary: '' })
        .catch((caught: unknown) => caught)
    })
    expect(error).toBeInstanceOf(Error)
    expect((error as Error).message).toBe('This view is read-only.')
  })
})

describe('HttpDataSource', () => {
  it('sends moments as decimal strings and maps the window', async () => {
    let seen: URLSearchParams | undefined
    server.use(
      http.get('*/api/v1/vaults/v/timelines/t1/window', ({ request }) => {
        seen = new URL(request.url).searchParams
        return HttpResponse.json({
          items: [{ entity_id: 'e1', start_t: HUGE, end_t: HUGE }],
          buckets: [],
          series_bands: [],
          total: 1,
        })
      }),
    )
    const window = await createHttpDataSource().timelineWindow('v', 't1', {
      from: '0',
      to: HUGE,
      px: 800,
    })
    expect(seen?.get('to')).toBe(HUGE)
    expect(window.items[0]?.start_t).toBe(BigInt(HUGE))
  })
})
