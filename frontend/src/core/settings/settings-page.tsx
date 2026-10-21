import { Link } from '@tanstack/react-router'
import { Suspense, type ComponentType } from 'react'

import { ConsistencySettings } from '@/core/consistency'
import { useExtensionList } from '@/core/modules'
import { cn } from '@/lib/utils'

import { BackupsSettings } from './backups'
import { GeneralSettings } from './general'
import { LinkTypesSettings } from './link-types'
import { ModulesSettings } from './modules'
import { PublishSettings } from './publish'

const CORE_PAGES: { id: string; title: string; component: ComponentType<{ vault: string }> }[] = [
  { id: '', title: 'General', component: GeneralSettings },
  { id: 'modules', title: 'Modules', component: ModulesSettings },
  { id: 'link-types', title: 'Link types', component: LinkTypesSettings },
  { id: 'consistency', title: 'Consistency', component: ConsistencySettings },
  { id: 'backups', title: 'Backups', component: BackupsSettings },
  { id: 'publishing', title: 'Publishing', component: PublishSettings },
]

/**
 * Vault settings (`/v/$vault/settings/*`, frontend.md §4): general, modules, link types,
 * consistency rules, backups, publishing,
 * then the active modules' pages (`settingsPages`, at `settings/<id>`).
 */
export function SettingsPage({ vault, page }: { vault: string; page: string }) {
  const modulePages = useExtensionList('settingsPages', vault)
  const pages = [...CORE_PAGES, ...modulePages]
  const current = pages.find((candidate) => candidate.id === page)
  const Page = current?.component
  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6 p-6 md:flex-row">
      <nav aria-label="Settings" className="flex shrink-0 flex-col gap-0.5 md:w-48">
        <h1 className="mb-2 px-2 text-2xl font-semibold">Settings</h1>
        {pages.map((candidate) => (
          <Link
            key={candidate.id}
            to="/v/$vault/settings/$"
            params={{ vault, _splat: candidate.id }}
            // Only the page itself: General's `settings/` is a prefix of every other page.
            activeOptions={{ exact: true }}
            aria-current={candidate.id === page ? 'page' : undefined}
            className={cn(
              'rounded-md px-2 py-1.5 text-sm hover:bg-accent',
              candidate.id === page && 'bg-accent font-medium',
            )}
          >
            {candidate.title}
          </Link>
        ))}
      </nav>
      <div className="min-w-0 flex-1">
        {Page ? (
          <>
            <h2 className="sr-only">{current.title}</h2>
            <Suspense fallback={<p className="text-sm text-muted-foreground">Loading…</p>}>
              <Page vault={vault} />
            </Suspense>
          </>
        ) : (
          <p className="text-muted-foreground">No settings page “{page}”.</p>
        )}
      </div>
    </div>
  )
}
