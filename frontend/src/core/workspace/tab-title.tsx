import { useKind } from '@/core/registry'
import { useEntity } from '@/data'

const PAGES: Readonly<Record<string, string>> = {
  search: 'Search',
  changes: 'Recent changes',
  trash: 'Trash',
  consistency: 'Consistency',
  settings: 'Settings',
}

const VIEWS: Readonly<Record<string, string>> = {
  timeline: 'Timeline',
  events: 'Events',
  causality: 'Causality',
}

const titleCase = (text: string) => text.charAt(0).toUpperCase() + text.slice(1).replace(/-/g, ' ')

function EntityTitle({ vault, id, view }: { vault: string; id: string; view?: string }) {
  const entity = useEntity(vault, id, {}, { toast: false })
  const name = entity.data?.name ?? (entity.isError ? 'Not found' : '…')
  return <>{view === undefined ? name : `${name} · ${view}`}</>
}

function KindTitle({ vault, kind }: { vault: string; kind: string }) {
  return <>{useKind(kind, vault)?.plural ?? titleCase(kind)}</>
}

/** A tab's title, from its route: the entity's name, the kind's plural, the page's name. */
export function TabTitle({ vault, href }: { vault: string; href: string }) {
  const path = href.split(/[?#]/)[0] ?? ''
  const [section, id, view] = path
    .slice(`/v/${vault}`.length)
    .split('/')
    .filter((part) => part !== '')
    .map(decodeURIComponent)
  if (section === undefined) return <>Home</>
  if ((section === 'e' || section === 'd') && id !== undefined) {
    return (
      <EntityTitle
        vault={vault}
        id={id}
        {...(view !== undefined ? { view: VIEWS[view] ?? titleCase(view) } : {})}
      />
    )
  }
  if (section === 'k' && id !== undefined) return <KindTitle vault={vault} kind={id} />
  if (section === 'calendars') return <>{id === 'new' ? 'New calendar' : 'Calendar'}</>
  if (section === 'm' && id !== undefined) return <>{titleCase(id)}</>
  return <>{PAGES[section] ?? titleCase(section)}</>
}
