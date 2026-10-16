import { MutationCache, QueryCache, QueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { ApiError } from '@/api'

/**
 * API errors become toasts, unless the query or mutation opts out with `meta: { toast: false }`.
 * `409 revision_conflict` and `422 consistency_error` never do: the conflict dialog (#62) and the
 * save-anyway dialog (#85) handle them.
 */
function toastApiError(error: unknown, meta: { toast?: boolean } | undefined): void {
  if (!(error instanceof ApiError) || meta?.toast === false) return
  if (error.code === 'revision_conflict' || error.code === 'consistency_error') return
  toast.error(error.title, { description: error.detail, id: `${error.code}:${error.detail}` })
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    queryCache: new QueryCache({
      onError: (error, query) => {
        toastApiError(error, query.meta)
      },
    }),
    mutationCache: new MutationCache({
      onError: (error, _variables, _context, mutation) => {
        toastApiError(error, mutation.meta)
      },
    }),
    defaultOptions: {
      queries: {
        // Writes invalidate what they change (data/invalidate.ts), so a read just made is still
        // good: the panels of a page that mount one after another share it instead of each
        // fetching it again.
        staleTime: 2_000,
        // A 4xx won't change on retry; network failures and 5xx get the default retries.
        retry: (failures, error) =>
          !(error instanceof ApiError && error.status < 500) && failures < 3,
      },
    },
  })
}
