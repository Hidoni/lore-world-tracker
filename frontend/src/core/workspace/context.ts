import type { AnyRouter, RouterHistory } from '@tanstack/react-router'
import { createContext, useContext } from 'react'

/** Creates the router of a pane beside the main one, at `href`, with its history (`app/` passes
 * it: core never imports `app/`). */
export type PaneRouterFactory = (href: string) => { router: AnyRouter; history: RouterHistory }

export const PaneRouterContext = createContext<PaneRouterFactory | null>(null)

/** The pane a component renders in: `null` in the main pane and the shell around it. */
export const PaneContext = createContext<string | null>(null)

/** Whether this renders in a pane beside the main one (its routes render without the shell). */
export function useInPane(): boolean {
  return useContext(PaneContext) !== null
}
