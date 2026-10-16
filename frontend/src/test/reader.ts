import { screen, waitFor } from '@testing-library/react'

/**
 * Names of controls that change the vault (frontend.md §13: readers get none). Reading controls
 * (search, filters, the time cursor, expand, zoom, pin, reveal a spoiler, download) don't match.
 */
const EDITING =
  /^(new|add|create|edit|rename|delete|remove|move to trash|trash|restore|upload|replace|save|duplicate|archive|unarchive|convert|change|set|reorder|split|merge|link|unlink|place|publish|back up|import|mark|resolve|suppress|undo|redo|revert|record|travel)\b/i

/** Reading conveniences whose names look like edits (kept in this browser only). */
const READER_CONVENIENCES = new Set(['Save view', 'Forget views', 'Add dimension lane'])

function describe(element: Element): string {
  const name = element.getAttribute('aria-label') ?? element.textContent.trim().replace(/\s+/g, ' ')
  return `${element.getAttribute('role') ?? element.tagName.toLowerCase()} "${name}"`
}

/**
 * The editing affordances on screen: buttons and menu items named like edits, editable text
 * (`contenteditable`), drag handles and file inputs. A reader-mode page test expects none.
 */
export function editingControls(root: HTMLElement = document.body): string[] {
  const found: string[] = []
  const actions = [
    ...screen.queryAllByRole('button', { hidden: false }),
    ...screen.queryAllByRole('menuitem', { hidden: false }),
  ].filter((element) => root.contains(element))
  for (const element of actions) {
    const name = (element.getAttribute('aria-label') ?? element.textContent).trim()
    if (EDITING.test(name) && !READER_CONVENIENCES.has(name)) found.push(describe(element))
  }
  for (const element of root.querySelectorAll('[contenteditable="true"]')) {
    found.push(`editable text in ${describe(element.parentElement ?? element)}`)
  }
  for (const element of root.querySelectorAll(
    '[aria-roledescription="sortable"], [aria-roledescription="draggable"], [draggable="true"]',
  )) {
    found.push(`drag handle ${describe(element)}`)
  }
  for (const element of root.querySelectorAll('input[type="file"]')) {
    found.push(`file input ${describe(element)}`)
  }
  return found
}

/**
 * Waits for a page to load: its main heading shown, then (for up to 3 s: lazy views such as the
 * causality graph may take longer in jsdom) nothing left "Loading…".
 */
export async function settled(): Promise<void> {
  await screen.findAllByRole('heading', { level: 1 }, { timeout: 3000 })
  await waitFor(
    () => {
      if (screen.queryAllByText(/^Loading/).length > 0) throw new Error('still loading')
    },
    { timeout: 3000 },
  ).catch(() => undefined)
}

/** The page shows no editing affordances (the error lists the ones it found). */
export function expectNoEditing(): void {
  const found = editingControls()
  if (found.length > 0) throw new Error(`editing controls in reader mode: ${found.join(', ')}`)
}
