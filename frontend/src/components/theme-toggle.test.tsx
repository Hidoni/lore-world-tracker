import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'

import { useTheme } from '@/lib/theme'

import { ThemeMenu } from './theme-toggle'

describe('ThemeMenu', () => {
  afterEach(() => {
    useTheme.getState().setPreference('system')
  })

  it('picks light, dark or system with the keyboard and persists the choice', async () => {
    const user = userEvent.setup()
    render(<ThemeMenu />)
    screen.getByRole('button', { name: 'Theme' }).focus()
    await user.keyboard('{Enter}')
    expect(await screen.findByRole('menuitemradio', { name: 'System' })).toHaveAttribute(
      'aria-checked',
      'true',
    )
    await user.click(screen.getByRole('menuitemradio', { name: 'Dark' }))
    expect(useTheme.getState()).toMatchObject({ preference: 'dark', resolved: 'dark' })
    expect(localStorage.getItem('lore.theme')).toBe('dark')
  })
})
