import { MonitorIcon, MoonIcon, SunIcon } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useReading } from '@/lib/reading'
import { useTheme, type ThemePreference } from '@/lib/theme'

const OPTIONS: { value: ThemePreference; label: string }[] = [
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
  { value: 'system', label: 'System' },
]

function isPreference(value: string): value is ThemePreference {
  return OPTIONS.some((option) => option.value === value)
}

/**
 * Display preferences (frontend.md §11): light, dark or system theme (`@/lib/theme`) and the
 * reading font of rendered bodies (`@/lib/reading`), per browser.
 */
export function ThemeMenu() {
  const preference = useTheme((state) => state.preference)
  const resolved = useTheme((state) => state.resolved)
  const setPreference = useTheme((state) => state.setPreference)
  const font = useReading((state) => state.font)
  const setFont = useReading((state) => state.setFont)
  const Icon = preference === 'system' ? MonitorIcon : resolved === 'dark' ? MoonIcon : SunIcon

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="Display">
          <Icon />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>Theme</DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={preference}
          onValueChange={(value) => {
            if (isPreference(value)) setPreference(value)
          }}
        >
          {OPTIONS.map(({ value, label }) => (
            <DropdownMenuRadioItem key={value} value={value}>
              {label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <DropdownMenuLabel>Reading font</DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={font}
          onValueChange={(value) => {
            setFont(value === 'serif' ? 'serif' : 'sans')
          }}
        >
          <DropdownMenuRadioItem value="sans">Sans-serif</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="serif">Serif</DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
