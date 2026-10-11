import { GlobeIcon, PlusIcon } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useKindRegistry } from '@/core/registry'
import { DimensionWizard } from '@/core/time'
import { useMutations } from '@/data'

import { CreateEntityDialog, creatableKinds } from './create-entity-dialog'

/**
 * The "New…" menu: one item per creatable kind, opening the create dialog, and a dimension
 * (the wizard). Author only.
 */
export function NewEntityMenu({ vault }: { vault: string }) {
  const registry = useKindRegistry(vault)
  const mutations = useMutations()
  const [kind, setKind] = useState<string | null>(null)
  const [dimension, setDimension] = useState(false)
  const kinds = creatableKinds(registry?.kinds ?? [])
  if (mutations === null) return null

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="sm" aria-label="New…">
            <PlusIcon aria-hidden />
            <span className="hidden sm:inline">New</span>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuLabel>New…</DropdownMenuLabel>
          {kinds.map(({ key, label, icon: Icon }) => (
            <DropdownMenuItem
              key={key}
              onSelect={() => {
                setKind(key)
              }}
            >
              <Icon aria-hidden />
              {label}
            </DropdownMenuItem>
          ))}
          {kinds.length > 0 && <DropdownMenuSeparator />}
          <DropdownMenuItem
            onSelect={() => {
              setDimension(true)
            }}
          >
            <GlobeIcon aria-hidden />
            Dimension…
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      {dimension && (
        <DimensionWizard
          vault={vault}
          onClose={() => {
            setDimension(false)
          }}
        />
      )}
      {kind !== null && (
        <CreateEntityDialog
          vault={vault}
          initialKind={kind}
          onClose={() => {
            setKind(null)
          }}
        />
      )}
    </>
  )
}
