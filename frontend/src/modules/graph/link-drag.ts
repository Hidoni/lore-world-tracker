/**
 * `Alt`+drag from one node to another (visual linking, docs/modules/graph.md): the gesture, kept
 * apart from the renderer. `down` starts it on a node pressed with `Alt`, `up` ends it, giving
 * both ends when it ends on another node.
 */
export class LinkDrag {
  source: string | null = null

  get active(): boolean {
    return this.source !== null
  }

  /** Starts a link from `node` when `Alt` is held; whether it did. */
  down(node: string, alt: boolean): boolean {
    this.source = alt ? node : null
    return this.source !== null
  }

  /** Ends the gesture (released over `node`, or elsewhere): the link's ends, if any. */
  up(node: string | null): [string, string] | null {
    const source = this.source
    this.source = null
    return source !== null && node !== null && node !== source ? [source, node] : null
  }
}

/**
 * Whether the mouse was just dragging (panning, or an `Alt`+drag), so that a "double click" made of
 * two quick drag releases doesn't open the node under the cursor: sigma counts every release on
 * the canvas as a click, drags included.
 */
export class RecentDrag {
  private at = Number.NEGATIVE_INFINITY

  constructor(private readonly windowMs = 500) {}

  /** A mouse move: `pressed` while a button is held. */
  move(pressed: boolean, now: number): void {
    if (pressed) this.at = now
  }

  /** Whether a drag happened within the window before `now`. */
  dragged(now: number): boolean {
    return now - this.at < this.windowMs
  }
}
