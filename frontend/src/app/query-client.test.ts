import { toast } from 'sonner'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api'

import { createQueryClient } from './query-client'

vi.mock('sonner', () => ({ toast: { error: vi.fn() } }))

function apiError(code: string): ApiError {
  return new ApiError({ status: 409, code, title: code, detail: `${code} detail` })
}

async function failMutation(error: Error, meta?: { toast?: boolean }): Promise<void> {
  const client = createQueryClient()
  const mutation = client.getMutationCache().build(client, {
    mutationFn: () => Promise.reject(error),
    meta,
  })
  await mutation.execute(undefined).catch(() => undefined)
}

describe('createQueryClient', () => {
  afterEach(() => {
    vi.mocked(toast.error).mockClear()
  })

  it('toasts API errors', async () => {
    await failMutation(apiError('conflict'))
    expect(toast.error).toHaveBeenCalledWith(
      'conflict',
      expect.objectContaining({ description: 'conflict detail' }),
    )
  })

  it('leaves revision conflicts, opted-out calls and other errors alone', async () => {
    await failMutation(apiError('revision_conflict'))
    await failMutation(apiError('conflict'), { toast: false })
    await failMutation(new Error('network down'))
    expect(toast.error).not.toHaveBeenCalled()
  })
})
