import { ENGINE_VERSION } from '@lore/chronology'
import { Link, useNavigate } from '@tanstack/react-router'
import { PencilIcon, Trash2Icon } from 'lucide-react'
import { useEffect, useState, type ComponentProps } from 'react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  useCreateVault,
  useDeleteVault,
  useMeta,
  useRenameVault,
  useVaults,
  type Vault,
} from '@/data'

import { lastVault, rememberVault } from './last-vault'

const STATE_LABELS: Partial<Record<Vault['schema_status']['state'], string>> = {
  needs_migration: 'Needs migration',
  newer_than_app: 'Newer than this app',
  migration_failed: 'Migration failed',
  database_unreadable: 'Unreadable',
}

type FormSubmit = NonNullable<ComponentProps<'form'>['onSubmit']>

function formatModified(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

function CreateVaultForm() {
  const [name, setName] = useState('')
  const create = useCreateVault()

  const onSubmit: FormSubmit = (event) => {
    event.preventDefault()
    const trimmed = name.trim()
    if (!trimmed) return
    create.mutate(trimmed, {
      onSuccess: (vault) => {
        setName('')
        toast.success(`Created “${vault.name}”`)
      },
    })
  }

  return (
    <form onSubmit={onSubmit} className="flex items-end gap-2">
      <div className="flex flex-1 flex-col gap-1.5">
        <Label htmlFor="new-vault-name">New vault</Label>
        <Input
          id="new-vault-name"
          value={name}
          maxLength={200}
          placeholder="World name"
          onChange={(event) => {
            setName(event.target.value)
          }}
        />
      </div>
      <Button type="submit" disabled={!name.trim() || create.isPending}>
        Create vault
      </Button>
    </form>
  )
}

function RenameDialog({ vault, onClose }: { vault: Vault; onClose: () => void }) {
  const [name, setName] = useState(vault.name)
  const rename = useRenameVault()

  const onSubmit: FormSubmit = (event) => {
    event.preventDefault()
    const trimmed = name.trim()
    if (!trimmed) return
    rename.mutate({ id: vault.id, name: trimmed }, { onSuccess: onClose })
  }

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent>
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <DialogHeader>
            <DialogTitle>Rename vault</DialogTitle>
            <DialogDescription>
              Only the display name changes; the folder keeps its name.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="rename-vault-name">Name</Label>
            <Input
              id="rename-vault-name"
              value={name}
              maxLength={200}
              onChange={(event) => {
                setName(event.target.value)
              }}
            />
          </div>
          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="outline">
                Cancel
              </Button>
            </DialogClose>
            <Button type="submit" disabled={!name.trim() || rename.isPending}>
              Rename
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function DeleteDialog({ vault, onClose }: { vault: Vault; onClose: () => void }) {
  const remove = useDeleteVault()

  const onConfirm = (): void => {
    remove.mutate(vault.id, {
      onSuccess: () => {
        if (lastVault() === vault.id) rememberVault(null)
        toast.success(`Moved “${vault.name}” to the trash`)
        onClose()
      },
    })
  }

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Move “{vault.name}” to the trash?</DialogTitle>
          <DialogDescription>
            The vault’s folder moves to the data directory’s trash. Nothing is deleted: move it back
            to restore the vault.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="outline">
              Cancel
            </Button>
          </DialogClose>
          <Button variant="destructive" onClick={onConfirm} disabled={remove.isPending}>
            Move to trash
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ServerInfo() {
  const meta = useMeta()
  return (
    <dl className="grid grid-cols-[auto_1fr] items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
      <dt>Server version</dt>
      <dd data-testid="server-version">
        {meta.isPending && 'Connecting…'}
        {meta.isError && <Badge variant="destructive">Backend unreachable</Badge>}
        {meta.isSuccess && (
          <>
            {meta.data.app_version}{' '}
            {meta.data.read_only && <Badge variant="secondary">Read-only</Badge>}
          </>
        )}
      </dd>
      <dt>Chronology engine</dt>
      <dd>{ENGINE_VERSION}</dd>
    </dl>
  )
}

/**
 * The vault picker (`/`, R-VLT-1): list, create, rename and move vaults to the trash. Without
 * `?pick`, it opens the last-opened vault when it still exists.
 */
export function VaultPicker({ pick }: { pick: boolean }) {
  const vaults = useVaults()
  const navigate = useNavigate()
  const [renaming, setRenaming] = useState<Vault | null>(null)
  const [deleting, setDeleting] = useState<Vault | null>(null)
  const items = vaults.data?.items

  useEffect(() => {
    if (items === undefined) return
    const last = lastVault()
    if (last === null) return
    if (!items.some((vault) => vault.id === last)) {
      rememberVault(null)
      return
    }
    if (!pick) void navigate({ to: '/v/$vault', params: { vault: last }, replace: true })
  }, [items, pick, navigate])

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6 p-8">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold">Vaults</h1>
        <p className="text-muted-foreground">Each vault holds one world, with its own history.</p>
      </div>
      <CreateVaultForm />
      {vaults.isPending && <p className="text-muted-foreground">Loading vaults…</p>}
      {vaults.isError && (
        <p role="alert" className="text-destructive">
          Couldn’t load the vaults: {vaults.error.message}
        </p>
      )}
      {items?.length === 0 && (
        <p className="text-muted-foreground">No vaults yet: create one to start a world.</p>
      )}
      {items !== undefined && items.length > 0 && (
        <ul aria-label="Vaults" className="flex flex-col divide-y rounded-md border">
          {items.map((vault) => {
            const state = STATE_LABELS[vault.schema_status.state]
            return (
              <li key={vault.id} className="flex items-center gap-2 px-3 py-2">
                <div className="flex min-w-0 flex-1 flex-col">
                  <Link
                    to="/v/$vault"
                    params={{ vault: vault.id }}
                    className="truncate font-medium hover:underline"
                  >
                    {vault.name}
                  </Link>
                  <span className="text-xs text-muted-foreground">
                    Modified {formatModified(vault.modified_at)}
                  </span>
                </div>
                {state !== undefined && <Badge variant="secondary">{state}</Badge>}
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={`Rename ${vault.name}`}
                  onClick={() => {
                    setRenaming(vault)
                  }}
                >
                  <PencilIcon />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={`Move ${vault.name} to the trash`}
                  onClick={() => {
                    setDeleting(vault)
                  }}
                >
                  <Trash2Icon />
                </Button>
              </li>
            )
          })}
        </ul>
      )}
      {vaults.data !== undefined && vaults.data.problems.length > 0 && (
        <section aria-labelledby="vault-problems" className="flex flex-col gap-2">
          <h2 id="vault-problems" className="font-medium">
            Folders that can’t be opened
          </h2>
          <ul className="flex flex-col gap-1 text-sm">
            {vaults.data.problems.map((problem) => (
              <li key={problem.folder}>
                <span className="font-mono">{problem.folder}</span>: {problem.detail}
              </li>
            ))}
          </ul>
        </section>
      )}
      <ServerInfo />
      {renaming !== null && (
        <RenameDialog
          vault={renaming}
          onClose={() => {
            setRenaming(null)
          }}
        />
      )}
      {deleting !== null && (
        <DeleteDialog
          vault={deleting}
          onClose={() => {
            setDeleting(null)
          }}
        />
      )}
    </div>
  )
}
