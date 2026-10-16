import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'

import { useReading } from '@/lib/reading'
import { useTheme } from '@/lib/theme'

import { ThemeMenu } from './theme-toggle'

describe('ThemeMenu', () => {
  afterEach(() => {
    useTheme.getState().setPreference('system')
    useReading.getState().setFont('sans')
  })

  it('picks light, dark or system with the keyboard and persists the choice', async () => {
    const user = userEvent.setup()
    render(<ThemeMenu />)
    screen.getByRole('button', { name: 'Display' }).focus()
    await user.keyboard('{Enter}')
    expect(await screen.findByRole('menuitemradio', { name: 'System' })).toHaveAttribute(
      'aria-checked',
      'true',
    )
    await user.click(screen.getByRole('menuitemradio', { name: 'Dark' }))
    expect(useTheme.getState()).toMatchObject({ preference: 'dark', resolved: 'dark' })
    expect(localStorage.getItem('lore.theme')).toBe('dark')
  })

  it('picks the reading font of rendered bodies', async () => {
    const user = userEvent.setup()
    render(<ThemeMenu />)
    await user.click(screen.getByRole('button', { name: 'Display' }))
    await user.click(await screen.findByRole('menuitemradio', { name: 'Serif' }))
    expect(useReading.getState().font).toBe('serif')
    expect(localStorage.getItem('lore.readingFont')).toBe('serif')
  })
})
