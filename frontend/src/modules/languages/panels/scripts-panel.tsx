import type { EntityViewProps } from '@/core/modules'
import { useLinks } from '@/data'

import { LinkRows } from './link-rows'

/**
 * A language's writing systems, or the languages a writing system writes (`uses_script` seen
 * from either end).
 */
export function ScriptsPanel({ vault, entityId, kind }: EntityViewProps) {
  const language = kind === 'language'
  const links = useLinks(vault, entityId, {
    type: ['languages.uses_script'],
    direction: language ? 'out' : 'in',
  })
  if (links.isPending) return <p className="text-sm text-muted-foreground">Loading…</p>
  const items = links.data?.items ?? []
  if (items.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        {language ? 'No writing system.' : 'Writes no language yet.'}
      </p>
    )
  }
  return <LinkRows vault={vault} label={language ? 'Scripts' : 'Languages'} items={items} />
}
