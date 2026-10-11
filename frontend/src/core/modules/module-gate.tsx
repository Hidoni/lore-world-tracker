import { Outlet } from '@tanstack/react-router'
import type { ReactNode } from 'react'

import { useActiveModules } from './context'

/**
 * The parent of a module's routes (`/v/$vault/m/<id>`): its pages while the module is active in
 * the vault, `notFound` otherwise.
 */
export function ModuleGate({ module, notFound }: { module: string; notFound: ReactNode }) {
  const { modules, isPending } = useActiveModules()
  if (isPending) return null
  return modules.some((definition) => definition.id === module) ? <Outlet /> : notFound
}
