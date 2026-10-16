import { EyeIcon } from 'lucide-react'
import { useState, type ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { useReaderMode } from '@/data'

/**
 * Spoiler content (visibility-and-sharing.md §1): readers get it folded behind a click; authors
 * see it as is (their pages mark it). `label` names what is folded ("Allegiance").
 */
export function Spoiler({
  spoiler = true,
  label,
  children,
}: {
  /** Whether the content is a spoiler at all (convenient for callers with a visibility). */
  spoiler?: boolean
  label?: string
  children: ReactNode
}) {
  const reading = useReaderMode().active
  const [shown, setShown] = useState(false)
  if (!spoiler || !reading || shown) return children
  return (
    <button
      type="button"
      className="inline-flex items-center gap-1 rounded-sm bg-muted px-1.5 py-0.5 text-xs font-medium text-muted-foreground hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      aria-label={label === undefined ? 'Show spoiler' : `Show spoiler: ${label}`}
      aria-expanded={false}
      onClick={() => {
        setShown(true)
      }}
    >
      <EyeIcon className="size-3" aria-hidden />
      Spoiler
    </button>
  )
}

/**
 * A whole page that is a spoiler (an entity marked spoiler): readers first get a notice and choose
 * to read on.
 */
export function SpoilerGate({
  spoiler,
  name,
  children,
}: {
  spoiler: boolean
  name: string
  children: ReactNode
}) {
  const reading = useReaderMode().active
  const [shown, setShown] = useState(false)
  if (!spoiler || !reading || shown) return children
  return (
    <section
      aria-label="Spoiler warning"
      className="flex flex-col items-start gap-3 rounded-lg border border-dashed p-6"
    >
      <p className="text-sm text-muted-foreground">
        {name} is marked as a spoiler: reading on may reveal what the story hasn’t yet.
      </p>
      <Button
        variant="outline"
        onClick={() => {
          setShown(true)
        }}
      >
        <EyeIcon aria-hidden />
        Show spoilers
      </Button>
    </section>
  )
}
