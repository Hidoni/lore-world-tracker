import { ENGINE_VERSION } from '@lore/chronology'

import { Badge } from '@/components/ui/badge'
import { useMeta } from '@/data'

/** Placeholder landing page: proves the API proxy and the chronology workspace link work. */
export function HomePage() {
  const meta = useMeta()

  return (
    <div className="mx-auto flex max-w-xl flex-col gap-4 p-8">
      <h1 className="text-2xl font-semibold">Welcome</h1>
      <p className="text-muted-foreground">
        A living wiki for fictional worlds with exact in-world time.
      </p>
      <dl className="grid grid-cols-[auto_1fr] items-center gap-x-4 gap-y-2 text-sm">
        <dt className="text-muted-foreground">Server version</dt>
        <dd data-testid="server-version">
          {meta.isPending && 'Connecting…'}
          {meta.isError && <Badge variant="destructive">Backend unreachable</Badge>}
          {meta.isSuccess && (
            <>
              {meta.data.app_version}{' '}
              {meta.data.read_only && <Badge variant="secondary">Read-only</Badge>}
            </>
          )}
        </dd>
        <dt className="text-muted-foreground">Chronology engine</dt>
        <dd>{ENGINE_VERSION}</dd>
      </dl>
    </div>
  )
}
