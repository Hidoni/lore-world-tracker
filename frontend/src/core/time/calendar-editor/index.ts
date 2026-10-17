import { lazy } from 'react'

export { blankDefinition } from './model'

// The editor is only on its own routes: it loads with them (frontend.md §12).
export const CalendarEditor = lazy(() =>
  import('./calendar-editor').then((module) => ({ default: module.CalendarEditor })),
)
export const NewCalendar = lazy(() =>
  import('./calendar-editor').then((module) => ({ default: module.NewCalendar })),
)
export const DraftCalendar = lazy(() =>
  import('./calendar-editor').then((module) => ({ default: module.DraftCalendar })),
)
