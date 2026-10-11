import { CalendarDaysIcon, ChevronDownIcon, GlobeIcon } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useDimensions } from '@/data'

import { useTimeContext } from './time-context'

/** The top bar's dimension switcher (frontend.md §3): the current dimension, and the others. */
export function DimensionSwitcher({ vault }: { vault: string }) {
  const context = useTimeContext(vault)
  const dimensions = useDimensions(vault)
  const items = dimensions.data?.items ?? []
  if (items.length === 0) return null
  const current = items.find((item) => item.id === context.dimensionId)
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="sm" aria-label={`Dimension: ${current?.name ?? 'none'}`}>
          <GlobeIcon aria-hidden />
          <span className="max-w-40 truncate">{current?.name ?? 'Dimension'}</span>
          <ChevronDownIcon aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuRadioGroup
          value={context.dimensionId ?? ''}
          onValueChange={(id) => {
            context.setDimension(id)
          }}
        >
          {items.map((item) => (
            <DropdownMenuRadioItem key={item.id} value={item.id}>
              {item.name}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/**
 * The display-calendar selector (frontend.md §3): every calendar of the current dimension and the
 * Absolute one. The choice goes to the URL (`cal`) and is remembered per vault and dimension.
 */
export function CalendarSelector({ vault }: { vault: string }) {
  const context = useTimeContext(vault)
  if (context.lens === null) return null
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="sm" aria-label={`Display calendar: ${context.lens.name}`}>
          <CalendarDaysIcon aria-hidden />
          <span className="max-w-40 truncate">{context.lens.name}</span>
          <ChevronDownIcon aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuRadioGroup
          value={context.lens.id}
          onValueChange={(id) => {
            context.setCalendar(id)
          }}
        >
          {context.lenses.map((lens) => (
            <DropdownMenuRadioItem key={lens.id} value={lens.id}>
              {lens.name}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
