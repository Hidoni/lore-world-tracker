import { lazy, Suspense, type ComponentProps } from 'react'

// The recurrence engine and editor load with the first recurring event (frontend.md §12).
const Editor = lazy(() =>
  import('./recurrence-editor').then((module) => ({ default: module.RecurrenceEditor })),
)
const Occurrences = lazy(() =>
  import('./occurrences').then((module) => ({ default: module.OccurrencesSection })),
)

const OccurrenceRef = lazy(() =>
  import('./occurrence-ref').then((module) => ({ default: module.OccurrenceRefLabel })),
)

function Loading() {
  return <p className="text-sm text-muted-foreground">Loading…</p>
}

export function RecurrenceEditor(props: ComponentProps<typeof Editor>) {
  return (
    <Suspense fallback={<Loading />}>
      <Editor {...props} />
    </Suspense>
  )
}

export function OccurrencesSection(props: ComponentProps<typeof Occurrences>) {
  return (
    <Suspense fallback={<Loading />}>
      <Occurrences {...props} />
    </Suspense>
  )
}

/** "the 3rd occurrence of" (loads the recurrence engine to find the occurrence). */
export function OccurrenceRefLabel(props: ComponentProps<typeof OccurrenceRef>) {
  return (
    <Suspense fallback={<>an occurrence of</>}>
      <OccurrenceRef {...props} />
    </Suspense>
  )
}
