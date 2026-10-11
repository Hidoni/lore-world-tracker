import { create } from 'zustand'

interface PaletteState {
  open: boolean
  shortcutsOpen: boolean
  setOpen: (open: boolean) => void
  setShortcutsOpen: (open: boolean) => void
}

/** Whether the command palette and the shortcuts sheet are open. */
export const usePalette = create<PaletteState>((set) => ({
  open: false,
  shortcutsOpen: false,
  setOpen: (open) => {
    set({ open })
  },
  setShortcutsOpen: (shortcutsOpen) => {
    set({ shortcutsOpen })
  },
}))

/** Whether a key press happens while typing (inputs, the editor), where shortcuts stay off. */
export function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return (
    target.isContentEditable ||
    ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) ||
    target.closest('[contenteditable="true"]') !== null
  )
}

/** The keyboard shortcuts (frontend.md §3), shown by `?`. */
export const SHORTCUTS: readonly { keys: string; action: string }[] = [
  { keys: 'Ctrl/⌘ K', action: 'Open the command palette (switch to an entity, run a command)' },
  { keys: '?', action: 'Show these shortcuts' },
  { keys: 'Esc', action: 'Close a dialog, menu or suggestion' },
  { keys: '[[ or @', action: 'Link an entity while writing' },
  { keys: '/', action: 'Insert a block while writing' },
  { keys: 'Ctrl/⌘ Enter', action: 'Save a multi-line field' },
  { keys: 'Space, arrows', action: 'Move an entity in the sidebar tree (then Space or Enter)' },
]
