/**
 * `localStorage` that never throws: storage can be unavailable (private mode, blocked site data),
 * and losing a remembered preference is acceptable (frontend.md §4).
 */
export function readStored(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

export function writeStored(key: string, value: string | null): void {
  try {
    if (value === null) localStorage.removeItem(key)
    else localStorage.setItem(key, value)
  } catch {
    // Not persisting is acceptable.
  }
}
