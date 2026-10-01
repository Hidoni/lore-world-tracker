import { MoonIcon, SunIcon } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { useTheme } from '@/lib/theme'

export function ThemeToggle() {
  const resolved = useTheme((state) => state.resolved)
  const toggle = useTheme((state) => state.toggle)
  const label = resolved === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'

  return (
    <Button variant="ghost" size="icon" onClick={toggle} aria-label={label} title={label}>
      {resolved === 'dark' ? <SunIcon /> : <MoonIcon />}
    </Button>
  )
}
