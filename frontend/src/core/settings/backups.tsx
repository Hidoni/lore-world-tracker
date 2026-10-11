import { Link } from '@tanstack/react-router'
import { ShieldAlertIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  backupDownloadUrl,
  useBackups,
  useCreateBackup,
  useMutations,
  useRestoreBackup,
  useSettings,
  useUpdateSettings,
  type components,
} from '@/data'

import { Section } from './shared'

type Backup = components['schemas']['Backup']

const KIND_LABEL: Record<string, string> = {
  manual: 'Manual',
  scheduled: 'Scheduled',
  pre: 'Before a change',
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`
}

/**
 * Backups (deployment.md, persistence-and-migrations.md): the private-data notice, the list with
 * downloads, a backup now, the schedule, and restoring a zip into a new vault with upload progress.
 */
export function BackupsSettings({ vault }: { vault: string }) {
  const editable = useMutations() !== null
  return (
    <div className="flex flex-col gap-4">
      <div
        role="note"
        className="flex gap-2 rounded-md border border-amber-500/50 bg-amber-500/10 p-3 text-sm"
      >
        <ShieldAlertIcon aria-hidden className="mt-0.5 size-4 shrink-0" />
        <p>
          Backups contain <strong>everything</strong>, private entities, blocks and notes included.
          Share a backup only with people who may see all of it; to share with readers, publish a
          read-only view instead.
        </p>
      </div>
      <BackupList vault={vault} editable={editable} />
      {editable && <Schedule vault={vault} />}
      {editable && <Restore />}
    </div>
  )
}

function BackupList({ vault, editable }: { vault: string; editable: boolean }) {
  const backups = useBackups(vault)
  const create = useCreateBackup(vault)
  const [includeMedia, setIncludeMedia] = useState(true)
  const items = backups.data?.items ?? []
  return (
    <Section title="Backups" description="Newest first. Each is a zip of the vault.">
      {editable && (
        <div className="flex flex-wrap items-center gap-3">
          <Button
            disabled={create.isPending}
            onClick={() => {
              create.mutate(
                { include_media: includeMedia },
                {
                  onSuccess: (backup) => {
                    toast.success(`Backup created (${formatSize(backup.size)})`)
                  },
                },
              )
            }}
          >
            {create.isPending ? 'Backing up…' : 'Back up now'}
          </Button>
          <div className="flex items-center gap-2 text-sm">
            <Checkbox
              id="backup-now-media"
              checked={includeMedia}
              onCheckedChange={(checked) => {
                setIncludeMedia(checked === true)
              }}
            />
            <Label htmlFor="backup-now-media">Include media files</Label>
          </div>
        </div>
      )}
      {backups.isPending && <p className="text-sm text-muted-foreground">Loading…</p>}
      {!backups.isPending && items.length === 0 && (
        <p className="text-sm text-muted-foreground">No backups yet.</p>
      )}
      {items.length > 0 && (
        <ul aria-label="Backups list" className="flex flex-col divide-y text-sm">
          {items.map((backup: Backup) => (
            <li key={backup.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
              <time dateTime={backup.created_at} className="font-medium">
                {new Date(backup.created_at).toLocaleString()}
              </time>
              <span className="text-muted-foreground">
                {KIND_LABEL[backup.kind] ?? backup.kind}
                {backup.reason && ` (${backup.reason})`} · {formatSize(backup.size)}
                {!backup.includes_media && ' · without media'}
              </span>
              <Button asChild variant="outline" size="sm" className="ml-auto">
                <a href={backupDownloadUrl(vault, backup.id)} download>
                  Download
                </a>
              </Button>
            </li>
          ))}
        </ul>
      )}
    </Section>
  )
}

function Schedule({ vault }: { vault: string }) {
  const settings = useSettings(vault)
  const update = useUpdateSettings(vault)
  const current = settings.data?.backups
  const [draft, setDraft] = useState<{ every: string; keep: string; media: boolean } | null>(null)
  const shown = draft ?? {
    every: String(current?.every_hours ?? 24),
    keep: String(current?.keep ?? 7),
    media: current?.include_media ?? true,
  }
  const every = Number(shown.every)
  const keep = Number(shown.keep)
  const valid = Number.isInteger(every) && every >= 0 && Number.isInteger(keep) && keep >= 1
  return (
    <Section
      title="Schedule"
      description="Scheduled backups run while the server runs; 0 hours turns them off."
    >
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(event) => {
          event.preventDefault()
          if (!valid) return
          update.mutate(
            { backups: { every_hours: every, keep, include_media: shown.media } },
            {
              onSuccess: () => {
                setDraft(null)
                toast.success('Backup schedule saved')
              },
            },
          )
        }}
      >
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="backup-every">Every (hours)</Label>
          <Input
            id="backup-every"
            inputMode="numeric"
            className="w-28"
            value={shown.every}
            onChange={(event) => {
              setDraft({ ...shown, every: event.target.value })
            }}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="backup-keep">Keep the last</Label>
          <Input
            id="backup-keep"
            inputMode="numeric"
            className="w-28"
            value={shown.keep}
            onChange={(event) => {
              setDraft({ ...shown, keep: event.target.value })
            }}
          />
        </div>
        <div className="flex items-center gap-2 pb-2 text-sm">
          <Checkbox
            id="backup-schedule-media"
            checked={shown.media}
            onCheckedChange={(checked) => {
              setDraft({ ...shown, media: checked === true })
            }}
          />
          <Label htmlFor="backup-schedule-media">Include media</Label>
        </div>
        <Button type="submit" disabled={!valid || draft === null || update.isPending}>
          Save schedule
        </Button>
        {!valid && (
          <p className="w-full text-sm text-destructive">
            Use whole numbers: hours 0 or more, keep at least 1.
          </p>
        )}
      </form>
    </Section>
  )
}

function Restore() {
  const restore = useRestoreBackup()
  const [file, setFile] = useState<File | null>(null)
  const [progress, setProgress] = useState<number | null>(null)
  const restored = restore.data
  return (
    <Section
      title="Restore"
      description="Restoring creates a new vault from a backup zip; this vault is left as it is."
    >
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(event) => {
          event.preventDefault()
          if (file === null) return
          setProgress(0)
          restore.mutate(
            { file, onProgress: setProgress },
            {
              onSettled: () => {
                setProgress(null)
              },
            },
          )
        }}
      >
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="restore-file">Backup zip</Label>
          <Input
            id="restore-file"
            type="file"
            accept=".zip,application/zip"
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null)
              restore.reset()
            }}
          />
        </div>
        <Button type="submit" disabled={file === null || restore.isPending}>
          Restore into a new vault
        </Button>
      </form>
      {progress !== null && (
        <div className="flex items-center gap-2 text-sm">
          <progress aria-label="Upload progress" className="h-2 flex-1" max={1} value={progress} />
          <span>{progress < 1 ? `${Math.round(progress * 100)}%` : 'Restoring…'}</span>
        </div>
      )}
      {restore.isError && (
        <p role="alert" className="text-sm text-destructive">
          {restore.error.message}
        </p>
      )}
      {restored && (
        <p role="status" className="text-sm">
          Restored as{' '}
          <Link to="/v/$vault" params={{ vault: restored.id }} className="font-medium underline">
            {restored.name}
          </Link>
          .
        </p>
      )}
    </Section>
  )
}
