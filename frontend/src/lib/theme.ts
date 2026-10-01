import { create } from 'zustand'

/** The user's choice. `system` follows `prefers-color-scheme` (frontend.md §11). */
export type ThemePreference = 'light' | 'dark' | 'system'
export type ResolvedTheme = 'light' | 'dark'

const STORAGE_KEY = 'lore.theme'
const DARK_QUERY = '(prefers-color-scheme: dark)'

function readStoredPreference(): ThemePreference {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    if (value === 'light' || value === 'dark' || value === 'system') return value
  } catch {
    // Storage may be unavailable (private mode, blocked site data): fall back to the default.
  }
  return 'system'
}

function writeStoredPreference(preference: ThemePreference): void {
  try {
    localStorage.setItem(STORAGE_KEY, preference)
  } catch {
    // Not persisting the preference is acceptable.
  }
}

function systemPrefersDark(): boolean {
  return typeof window.matchMedia === 'function' && window.matchMedia(DARK_QUERY).matches
}

export function resolveTheme(preference: ThemePreference): ResolvedTheme {
  if (preference === 'system') return systemPrefersDark() ? 'dark' : 'light'
  return preference
}

function applyTheme(theme: ResolvedTheme): void {
  document.documentElement.classList.toggle('dark', theme === 'dark')
  document.documentElement.style.colorScheme = theme
}

interface ThemeState {
  preference: ThemePreference
  resolved: ResolvedTheme
  setPreference: (preference: ThemePreference) => void
  /** Flips between light and dark, pinning an explicit preference. */
  toggle: () => void
}

export const useTheme = create<ThemeState>()((set, get) => {
  const preference = readStoredPreference()
  return {
    preference,
    resolved: resolveTheme(preference),
    setPreference: (next) => {
      writeStoredPreference(next)
      set({ preference: next, resolved: resolveTheme(next) })
    },
    toggle: () => {
      get().setPreference(get().resolved === 'dark' ? 'light' : 'dark')
    },
  }
})

/** Keeps `<html class="dark">` in sync with the store and the OS setting. Call once at startup. */
export function initTheme(): () => void {
  applyTheme(useTheme.getState().resolved)
  const unsubscribe = useTheme.subscribe((state) => {
    applyTheme(state.resolved)
  })
  if (typeof window.matchMedia !== 'function') return unsubscribe

  const media = window.matchMedia(DARK_QUERY)
  const onSystemChange = (): void => {
    const { preference } = useTheme.getState()
    if (preference === 'system') useTheme.setState({ resolved: resolveTheme(preference) })
  }
  media.addEventListener('change', onSystemChange)
  return () => {
    unsubscribe()
    media.removeEventListener('change', onSystemChange)
  }
}
