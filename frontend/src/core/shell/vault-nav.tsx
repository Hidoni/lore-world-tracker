import { Link, useParams } from '@tanstack/react-router'
import {
  AlertTriangleIcon,
  HistoryIcon,
  HomeIcon,
  LibraryIcon,
  SearchIcon,
  SettingsIcon,
  Trash2Icon,
} from 'lucide-react'
import type { ComponentType } from 'react'

interface NavItem {
  to:
    | '/v/$vault'
    | '/v/$vault/search'
    | '/v/$vault/changes'
    | '/v/$vault/trash'
    | '/v/$vault/consistency'
    | '/v/$vault/settings'
  label: string
  icon: ComponentType<{ className?: string }>
}

const ITEMS: NavItem[] = [
  { to: '/v/$vault', label: 'Home', icon: HomeIcon },
  { to: '/v/$vault/search', label: 'Search', icon: SearchIcon },
  { to: '/v/$vault/changes', label: 'Recent changes', icon: HistoryIcon },
  { to: '/v/$vault/consistency', label: 'Consistency', icon: AlertTriangleIcon },
  { to: '/v/$vault/trash', label: 'Trash', icon: Trash2Icon },
  { to: '/v/$vault/settings', label: 'Settings', icon: SettingsIcon },
]

const LINK_CLASS =
  'flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none data-[status=active]:bg-accent data-[status=active]:font-medium'

/**
 * Sidebar navigation. Registry sections, trees, pinned and recent arrive with #65; until then
 * the vault's own pages.
 */
export function VaultNav({ onNavigate }: { onNavigate?: () => void }) {
  const { vault } = useParams({ strict: false })

  return (
    <nav aria-label="Vault" className="flex flex-col gap-0.5 p-2">
      {vault === undefined ? (
        <Link to="/" search={{ pick: true }} className={LINK_CLASS} onClick={onNavigate}>
          <LibraryIcon className="size-4" aria-hidden />
          Vaults
        </Link>
      ) : (
        ITEMS.map(({ to, label, icon: Icon }) => (
          <Link
            key={to}
            to={to}
            params={{ vault }}
            activeOptions={{ exact: to === '/v/$vault' }}
            className={LINK_CLASS}
            onClick={onNavigate}
          >
            <Icon className="size-4" aria-hidden />
            {label}
          </Link>
        ))
      )}
    </nav>
  )
}
