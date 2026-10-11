import type { Range } from '@tiptap/core'

/** An open `[[` or `@` suggestion: what was typed and where (to replace it). */
export interface SuggestionState {
  trigger: '[[' | '@'
  query: string
  range: Range
  /** Where to place the menu (viewport coordinates). */
  rect: { left: number; bottom: number } | null
}

/**
 * Connects the suggestion plugins (outside React) with the menu (inside): the plugins publish the
 * open suggestion and forward key presses to the menu's handler.
 */
export class SuggestionBridge {
  state: SuggestionState | null = null
  keyHandler: ((event: KeyboardEvent) => boolean) | null = null
  private listeners = new Set<() => void>()

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener)
    return () => {
      this.listeners.delete(listener)
    }
  }

  snapshot = (): SuggestionState | null => this.state

  /** The menu's key handler (`null`: no menu). */
  handleKeys(handler: ((event: KeyboardEvent) => boolean) | null): void {
    this.keyHandler = handler
  }

  publish(state: SuggestionState | null): void {
    this.state = state
    for (const listener of this.listeners) listener()
  }
}
