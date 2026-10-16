import { Outlet } from '@tanstack/react-router'
import { useEffect } from 'react'

import { usePreloadModules } from '@/core/modules'
import { useMutations } from '@/data'
import { LazyRichTextEditor } from '@/editor'

import { rememberVault } from './last-vault'

const EDITOR = [LazyRichTextEditor.preload]
const NOTHING: readonly (() => unknown)[] = []

/**
 * Wraps every `/v/$vault` route: remembers the vault for the picker's redirect, and loads the
 * code of its modules (and, for authors, the editor) ahead when the browser is idle.
 */
export function VaultScope({ vault }: { vault: string }) {
  useEffect(() => {
    rememberVault(vault)
  }, [vault])
  usePreloadModules(vault, useMutations() === null ? NOTHING : EDITOR)
  return <Outlet />
}
