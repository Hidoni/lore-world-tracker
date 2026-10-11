import type { ReactNode } from 'react'

/** A route that exists in the tree (frontend.md §4) before its page is built. */
export function PlaceholderPage({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-2 p-8">
      <h1 className="text-2xl font-semibold">{title}</h1>
      <p className="text-muted-foreground">{children ?? 'This page is not built yet.'}</p>
    </div>
  )
}
