import { XIcon } from 'lucide-react'
import { useState, type ComponentProps } from 'react'

import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'

/**
 * A list of short strings (aliases, tags) as chips: Enter adds, × removes. `onChange` gets the
 * whole new list; without it (reader mode) the chips are read-only.
 */
export function ListEditor({
  label,
  values,
  onChange,
  disabled,
}: {
  label: string
  values: readonly string[]
  onChange?: (values: string[]) => void
  disabled?: boolean
}) {
  const [draft, setDraft] = useState('')
  const add: NonNullable<ComponentProps<'input'>['onKeyDown']> = (event) => {
    if (event.key !== 'Enter' || onChange === undefined) return
    event.preventDefault()
    const value = draft.trim()
    if (value && !values.includes(value)) onChange([...values, value])
    setDraft('')
  }

  return (
    <div className="flex flex-wrap items-center gap-1" role="group" aria-label={label}>
      {values.map((value) => (
        <Badge key={value} variant="secondary" className="gap-1">
          {value}
          {onChange !== undefined && (
            <button
              type="button"
              className="rounded-full hover:bg-muted-foreground/20 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              aria-label={`Remove ${value}`}
              disabled={disabled}
              onClick={() => {
                onChange(values.filter((other) => other !== value))
              }}
            >
              <XIcon className="size-3" aria-hidden />
            </button>
          )}
        </Badge>
      ))}
      {onChange !== undefined && (
        <Input
          aria-label={`Add ${label.toLowerCase()}`}
          placeholder={`Add ${label.toLowerCase()}…`}
          value={draft}
          disabled={disabled}
          className="h-7 w-36"
          onChange={(event) => {
            setDraft(event.target.value)
          }}
          onKeyDown={add}
        />
      )}
    </div>
  )
}
