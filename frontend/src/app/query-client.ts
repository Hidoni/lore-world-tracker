import { MutationCache, QueryCache, QueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { ApiError } from '@/api'

/** API errors become toasts, unless the query or mutation opts out with `meta: { toast: false }`. */
function toastApiError(error: unknown, meta: { toast?: boolean } | undefined): void {
  if (!(error instanceof ApiError) || meta?.toast === false) return
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
      // A 4xx won't change on retry; network failures and 5xx get the default retries.
      queries: {
        retry: (failures, error) =>
          !(error instanceof ApiError && error.status < 500) && failures < 3,
      },
    },
  })
}
