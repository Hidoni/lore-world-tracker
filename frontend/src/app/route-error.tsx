import { Link, useRouter, type ErrorComponentProps } from '@tanstack/react-router'

import { ApiError } from '@/api'
import { Button } from '@/components/ui/button'

/** Every route's error boundary: the error, and a retry that reloads the route. */
export function RouteError({ error, reset }: ErrorComponentProps) {
  const router = useRouter()
  const apiError = error instanceof ApiError ? error : null

  return (
    <div role="alert" className="mx-auto flex max-w-xl flex-col gap-3 p-8">
      <h1 className="text-xl font-semibold">{apiError?.title ?? 'Something went wrong'}</h1>
      <p className="text-muted-foreground">
        {error instanceof Error ? error.message : String(error)}
      </p>
      {apiError !== null && (
        <p className="font-mono text-xs text-muted-foreground">
          {apiError.status} · {apiError.code}
        </p>
      )}
      <div className="flex gap-2">
        <Button
          onClick={() => {
            reset()
            void router.invalidate()
          }}
        >
          Try again
        </Button>
        <Button variant="outline" asChild>
          <Link to="/" search={{ pick: true }}>
            All vaults
          </Link>
        </Button>
      </div>
    </div>
  )
}

export function NotFoundPage() {
  return (
    <div className="mx-auto flex max-w-xl flex-col gap-3 p-8">
      <h1 className="text-xl font-semibold">Page not found</h1>
      <p className="text-muted-foreground">There is no page at this address.</p>
      <div>
        <Button variant="outline" asChild>
          <Link to="/" search={{ pick: true }}>
            All vaults
          </Link>
        </Button>
      </div>
    </div>
  )
}
