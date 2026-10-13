import { useQuery } from '@tanstack/react-query'

import type { components } from '@/api'

import { useDataSource } from './context'
import type { Domain } from './domain'
import { keys } from './keys'

type Schemas = components['schemas']

export type Membership = Domain<Schemas['Membership']>
export type Leadership = Domain<Schemas['Leadership']>
export type OrgChart = Domain<Schemas['OrgChart']>

/** A group's org chart: sub-groups and parts with leaders and member counts, as of `at`. */
export function useGroupOrgChart(
  vault: string,
  group: string,
  query: { depth: number; timeline?: string; at?: string },
) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.groupOrgChart(vault, group, query),
    queryFn: () => source.groupOrgChart(vault, group, query),
    placeholderData: (previous) => previous,
  })
}

/** Members of a group (and of its sub-groups), at any time. */
export function useGroupMembers(vault: string, group: string, includeSubgroups: boolean) {
  const source = useDataSource()
  const query = { include_subgroups: includeSubgroups }
  return useQuery({
    queryKey: keys.groupMembers(vault, group, query),
    queryFn: () => source.groupMembers(vault, group, query),
    placeholderData: (previous) => previous,
  })
}

/** The leadership succession of a group. */
export function useGroupLeaders(vault: string, group: string) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.groupLeaders(vault, group),
    queryFn: () => source.groupLeaders(vault, group),
  })
}

/** The locations a group controls. */
export function useGroupTerritory(vault: string, group: string) {
  const source = useDataSource()
  return useQuery({
    queryKey: keys.groupTerritory(vault, group),
    queryFn: () => source.groupTerritory(vault, group),
  })
}
