import { Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { useReaderMode } from '@/data'

import { PlaceholderPage } from './placeholder-page'

/**
 * A page only authors get (history, trash, findings, settings, calendar editing): readers (a
 * read-only server, or the author's preview) see a note with a way home instead.
 */
export function AuthorOnly({ vault, children }: { vault: string; children: ReactNode }) {
  if (!useReaderMode().active) return children
  return (
    <PlaceholderPage title="For authors">
      This page is part of editing the vault, so readers don’t get it.{' '}
      <Button variant="link" className="h-auto p-0" asChild>
        <Link to="/v/$vault" params={{ vault }}>
          Back to the vault
        </Link>
      </Button>
    </PlaceholderPage>
  )
}
