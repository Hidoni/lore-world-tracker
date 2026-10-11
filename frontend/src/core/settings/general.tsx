import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useMutations, useRenameVault, useSettings, useUpdateSettings, useVault } from '@/data'
import { useTheme, type ThemePreference } from '@/lib/theme'

import { Section, SELECT_CLASS } from './shared'

const VISIBILITIES = [
  { value: 'public', label: 'Public: readers see new entities' },
  { value: 'spoiler', label: 'Spoiler: readers unfold them' },
  { value: 'private', label: 'Private: authors only' },
] as const

/** General settings: the vault's name, the default visibility of new entities, display. */
export function GeneralSettings({ vault }: { vault: string }) {
  const editable = useMutations() !== null
  const current = useVault(vault)
  const settings = useSettings(vault)
  const update = useUpdateSettings(vault)
  const rename = useRenameVault()
  const theme = useTheme()
  const [name, setName] = useState<string | null>(null)
  const shownName = name ?? current.data?.name ?? ''

  return (
    <div className="flex flex-col gap-4">
      <Section title="Vault">
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(event) => {
            event.preventDefault()
            const trimmed = shownName.trim()
            if (trimmed === '') return
            rename.mutate(
              { id: vault, name: trimmed },
              {
                onSuccess: () => {
                  setName(null)
                  toast.success('Vault renamed')
                },
              },
            )
          }}
        >
          <div className="flex min-w-60 flex-1 flex-col gap-1.5">
            <Label htmlFor="vault-name">Name</Label>
            <Input
              id="vault-name"
              value={shownName}
              disabled={!editable}
              maxLength={200}
              onChange={(event) => {
                setName(event.target.value)
              }}
            />
          </div>
          {editable && (
            <Button
              type="submit"
              disabled={rename.isPending || name === null || name.trim() === ''}
            >
              Rename
            </Button>
          )}
        </form>
      </Section>
      <Section
        title="New entities"
        description="The visibility new entities start with (each one can change it)."
      >
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="default-visibility">Default visibility</Label>
          <select
            id="default-visibility"
            className={SELECT_CLASS}
            disabled={!editable || settings.isPending || update.isPending}
            value={settings.data?.defaults?.visibility ?? 'public'}
            onChange={(event) => {
              update.mutate(
                {
                  defaults: {
                    visibility: event.target.value as (typeof VISIBILITIES)[number]['value'],
                  },
                },
                {
                  onSuccess: () => {
                    toast.success('Default visibility saved')
                  },
                },
              )
            }}
          >
            {VISIBILITIES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      </Section>
      <Section title="Display" description="Kept in this browser, for every vault.">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="display-theme">Theme</Label>
          <select
            id="display-theme"
            className={SELECT_CLASS}
            value={theme.preference}
            onChange={(event) => {
              theme.setPreference(event.target.value as ThemePreference)
            }}
          >
            <option value="system">Match the system</option>
            <option value="light">Light</option>
            <option value="dark">Dark</option>
          </select>
        </div>
        <p className="text-xs text-muted-foreground">
          The display calendar and time preferences arrive with the time UI (M5).
        </p>
      </Section>
    </div>
  )
}
