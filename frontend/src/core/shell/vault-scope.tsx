import { Outlet } from '@tanstack/react-router'
import { useEffect } from 'react'

import { rememberVault } from './last-vault'

/** Wraps every `/v/$vault` route: remembers the vault for the picker's redirect. */
export function VaultScope({ vault }: { vault: string }) {
  useEffect(() => {
    rememberVault(vault)
  }, [vault])
  return <Outlet />
}
