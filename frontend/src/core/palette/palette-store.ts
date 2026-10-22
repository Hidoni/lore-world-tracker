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

export interface Shortcut {
  keys: string
  action: string
}

/** The keyboard shortcut sheet (`?`, frontend.md §11): every shortcut the app has, by where it works. */
export const SHORTCUT_GROUPS: readonly { title: string; shortcuts: readonly Shortcut[] }[] = [
  {
    title: 'Anywhere',
    shortcuts: [
      { keys: 'Ctrl/⌘ K', action: 'Open the command palette (switch to an entity, run a command)' },
      { keys: '?', action: 'Show these shortcuts' },
      { keys: 'Esc', action: 'Close a dialog, menu or suggestion' },
      { keys: 'Tab, Shift Tab', action: 'Move between controls ("Skip to content" comes first)' },
    ],
  },
  {
    title: 'Tabs and panes',
    shortcuts: [
      { keys: 'Alt click a link', action: 'Open it in a new tab' },
      { keys: 'Alt Shift click a link', action: 'Open it in a pane to the right' },
      { keys: 'Middle click a tab', action: 'Close it' },
      { keys: '← → on a pane border', action: 'Resize the panes' },
    ],
  },
  {
    title: 'Writing',
    shortcuts: [
      { keys: '[[ or @', action: 'Link an entity' },
      { keys: '/', action: 'Insert a block' },
      { keys: '↑ ↓, then Enter or Tab', action: 'Pick a suggestion' },
      { keys: 'Ctrl/⌘ B, Ctrl/⌘ I', action: 'Bold, italic' },
      { keys: 'Ctrl/⌘ Z, Ctrl/⌘ Shift Z', action: 'Undo, redo' },
      { keys: 'Enter, Esc', action: 'Save or cancel a field or a name being edited' },
      { keys: 'Ctrl/⌘ Enter', action: 'Save a multi-line field' },
    ],
  },
  {
    title: 'Timeline (when focused)',
    shortcuts: [
      { keys: '↑ ↓', action: 'Select the previous or next item' },
      { keys: 'Enter, Esc', action: 'Open the selected item, clear the selection' },
      { keys: 'E', action: 'Show or hide the sub-events of the selected event' },
      { keys: '+ −', action: 'Zoom in, out' },
      { keys: '← →', action: 'Pan (with Shift, further)' },
      { keys: 'Home', action: 'Show the whole dimension' },
      { keys: 'G', action: 'Go to a date' },
      { keys: 'Ctrl/⌘ wheel', action: "Zoom (or the wheel alone: the timeline's Wheel setting)" },
      { keys: '← → on the time cursor', action: 'Move the cursor by one unit' },
      { keys: '← →, Home, End on the minimap', action: 'Move by a view, go to either end' },
    ],
  },
  {
    title: 'Event outline',
    shortcuts: [
      { keys: '↑ ↓, Home, End', action: 'Move between rows' },
      { keys: '→ ←', action: 'Expand (or go into), collapse (or go to the parent)' },
      { keys: 'Enter', action: 'Open the event' },
    ],
  },
  {
    title: 'Sidebar',
    shortcuts: [
      {
        keys: 'Space, arrows',
        action: 'Move an entity in a tree (then Space or Enter, Esc to cancel)',
      },
      { keys: '← →, Home, End, Enter', action: 'Resize from its edge (Enter: the default width)' },
    ],
  },
  {
    title: 'Graph and maps',
    shortcuts: [
      { keys: 'Alt drag', action: 'Link two entities in a graph' },
      { keys: 'Enter in the graph search', action: 'Select the first match' },
      { keys: 'Arrows, + −', action: 'Pan and zoom a focused map' },
      { keys: 'Tab, Enter', action: 'Reach a map pin, open it' },
      { keys: '"As a list"', action: 'Every diagram, map and graph also reads as a list' },
    ],
  },
]

/** Every shortcut, in sheet order. */
export const SHORTCUTS: readonly Shortcut[] = SHORTCUT_GROUPS.flatMap((group) => group.shortcuts)
