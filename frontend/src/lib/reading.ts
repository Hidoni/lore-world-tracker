import { create } from 'zustand'

/** The font of rendered bodies (frontend.md §11: an optional serif reading font). */
export type ReadingFont = 'sans' | 'serif'

const STORAGE_KEY = 'lore.readingFont'

function readStored(): ReadingFont {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'serif' ? 'serif' : 'sans'
  } catch {
    return 'sans'
  }
}

interface ReadingState {
  font: ReadingFont
  setFont: (font: ReadingFont) => void
}

/** The reading font, per browser (`lore.readingFont`). */
export const useReading = create<ReadingState>()((set) => ({
  font: readStored(),
  setFont: (font) => {
    try {
      localStorage.setItem(STORAGE_KEY, font)
    } catch {
      // Not persisting the preference is acceptable.
    }
    set({ font })
  },
}))
