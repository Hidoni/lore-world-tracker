import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  ApiError,
  interchangeExportUrl,
  markdownExportUrl,
  useDimensions,
  useExportStaticSite,
  useImportInterchange,
  useMutations,
  usePublish,
  usePublishStatus,
} from '@/data'

import { Section, SELECT_CLASS } from './shared'

/**
 * Publishing (visibility-and-sharing.md §4): a sanitized snapshot of the vault, private data
 * removed, written into the server's publish directory for a read-only server to share.
 */
export function PublishSettings({ vault }: { vault: string }) {
  return (
    <div className="flex flex-col gap-6">
      <PublishSnapshot vault={vault} />
      <StaticSite vault={vault} />
      <MarkdownExport vault={vault} />
      <InterchangeExport vault={vault} />
      <InterchangeImport vault={vault} />
    </div>
  )
}

function PublishSnapshot({ vault }: { vault: string }) {
  const editable = useMutations() !== null
  const status = usePublishStatus(vault)
  const publish = usePublish(vault)
  const publishedAt = status.data?.published_at ?? null
  return (
    <Section
      title="Publish snapshot"
      description="A copy of the vault for readers: private entities, fields, blocks, notes, history and findings are removed, and a leak check runs before anything is written. Serve the publish directory with a read-only server."
    >
      {status.isPending && <p className="text-sm text-muted-foreground">Loading…</p>}
      {status.data && !status.data.available && (
        <p className="text-sm text-muted-foreground">
          Publishing isn’t set up on this server: set <code>LORE_PUBLISH_DIR</code> to the data
          directory of the read-only server, or run <code>lore vault publish</code>.
        </p>
      )}
      {status.data?.available && (
        <div className="flex flex-wrap items-center gap-3">
          {editable && (
            <Button
              disabled={publish.isPending}
              onClick={() => {
                publish.mutate(undefined, {
                  onSuccess: () => {
                    toast.success('Snapshot published')
                  },
                })
              }}
            >
              {publish.isPending ? 'Publishing…' : 'Publish snapshot'}
            </Button>
          )}
          <p className="text-sm text-muted-foreground">
            {publishedAt === null ? (
              'Not published yet.'
            ) : (
              <>
                Last published{' '}
                <time dateTime={publishedAt}>{new Date(publishedAt).toLocaleString()}</time>.
              </>
            )}
          </p>
        </div>
      )}
    </Section>
  )
}

/**
 * The static site (visibility-and-sharing.md §8): the latest snapshot as plain files that any
 * static host serves, written beside the snapshot in the publish directory.
 */
function StaticSite({ vault }: { vault: string }) {
  const editable = useMutations() !== null
  const status = usePublishStatus(vault)
  const exportSite = useExportStaticSite(vault)
  if (!editable || !status.data?.available) return null
  const { published_at: publishedAt, static_available: available } = status.data
  const exportedAt = status.data.static_exported_at ?? null
  return (
    <Section
      title="Export static site"
      description="The latest snapshot as a website of plain files: copy the folder to any static host (GitHub Pages, a web server, a file share) and readers browse the world with no Lore server. Export again after publishing a new snapshot."
    >
      {!available && (
        <p className="text-sm text-muted-foreground">
          Static export isn’t set up on this server: set <code>LORE_STATIC_DIR</code> to the app’s
          build, or run <code>lore vault export-static</code>.
        </p>
      )}
      {available && (
        <div className="flex flex-wrap items-center gap-3">
          <Button
            disabled={exportSite.isPending || publishedAt === null}
            onClick={() => {
              exportSite.mutate(undefined, {
                onSuccess: () => {
                  toast.success('Static site exported')
                },
              })
            }}
          >
            {exportSite.isPending ? 'Exporting… (this can take minutes)' : 'Export static site'}
          </Button>
          <p className="text-sm text-muted-foreground">
            {publishedAt === null ? (
              'Publish a snapshot first: the site is made from it.'
            ) : exportedAt === null ? (
              'Not exported yet.'
            ) : (
              <>
                Exported <time dateTime={exportedAt}>{new Date(exportedAt).toLocaleString()}</time>{' '}
                to <code>{status.data.static_path}</code>.
              </>
            )}
          </p>
        </div>
      )}
    </Section>
  )
}

/**
 * The Markdown export (markdown-export.md): the vault as a zip of notes for Obsidian and other
 * Markdown tools, as readers see it or (author only) with everything.
 */
function MarkdownExport({ vault }: { vault: string }) {
  const editable = useMutations() !== null
  if (!editable) return null
  return (
    <Section
      title="Export as Markdown"
      description="A zip of Markdown notes for Obsidian or other Markdown tools: one note per entity with wikilinks, properties (fields, aliases, tags, dates in every calendar), facts, links and media. Nothing is read back from it."
    >
      <div className="flex flex-wrap items-center gap-3">
        <Button asChild>
          <a href={markdownExportUrl(vault, 'readers')} download>
            Download readers’ view
          </a>
        </Button>
        <Button asChild variant="outline">
          <a href={markdownExportUrl(vault, 'author')} download>
            Download everything
          </a>
        </Button>
      </div>
      <p className="text-sm text-muted-foreground">
        “Everything” includes private entities, fields and blocks: keep it to yourself, like a
        backup.
      </p>
    </Section>
  )
}

/**
 * The interchange export (interchange.md §3): the vault or one dimension as versioned JSON with its
 * media files, for importing into another vault of this app or a later one.
 */
function InterchangeExport({ vault }: { vault: string }) {
  const editable = useMutations() !== null
  const dimensions = useDimensions(vault)
  const [dimension, setDimension] = useState('')
  if (!editable) return null
  const only = dimension === '' ? undefined : dimension
  return (
    <Section
      title="Export as JSON"
      description="A zip of the vault’s records as documented, versioned JSON, with its media files: import it into another vault (below), here or on another server, now or with a later version of Lore. Export the whole vault, or one dimension: the multiversal entities it uses travel as references and are matched by name when imported."
    >
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="interchange-dimension">What to export</Label>
        <select
          id="interchange-dimension"
          className={SELECT_CLASS}
          value={dimension}
          onChange={(event) => {
            setDimension(event.target.value)
          }}
        >
          <option value="">The whole vault</option>
          {(dimensions.data?.items ?? []).map((item) => (
            <option key={item.id} value={item.id}>
              Dimension: {item.name}
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button asChild>
          <a href={interchangeExportUrl(vault, 'readers', only)} download>
            Export JSON (readers’ view)
          </a>
        </Button>
        <Button asChild variant="outline">
          <a href={interchangeExportUrl(vault, 'author', only)} download>
            Export JSON (everything)
          </a>
        </Button>
      </div>
      <p className="text-sm text-muted-foreground">
        “Everything” includes private entities, fields and blocks: keep it to yourself, like a
        backup.
      </p>
    </Section>
  )
}

/** The interchange import (interchange.md §4): one changeset, undoable from History. */
function InterchangeImport({ vault }: { vault: string }) {
  const editable = useMutations() !== null
  if (!editable) return null
  return <InterchangeImportForm vault={vault} />
}

function InterchangeImportForm({ vault }: { vault: string }) {
  const importFile = useImportInterchange(vault)
  const [file, setFile] = useState<File | null>(null)
  const [keepIds, setKeepIds] = useState(false)
  const [overwrite, setOverwrite] = useState(false)
  const report = importFile.data
  const error = importFile.error
  const conflicts =
    error instanceof ApiError && Array.isArray(error.context.conflicts)
      ? (error.context.conflicts as { table: string; id: string; name?: string }[])
      : []
  const total = (counts: Record<string, number>) =>
    Object.values(counts).reduce((sum, count) => sum + count, 0)
  return (
    <Section
      title="Import JSON"
      description="Adds the records of a JSON export (zip) to this vault in one change, which History can undo. Records get fresh ids, so importing a file twice makes two copies; keep the file’s ids to move records between your own vaults."
    >
      <form
        className="flex flex-col gap-3"
        onSubmit={(event) => {
          event.preventDefault()
          if (file === null) return
          importFile.mutate({
            file,
            options: {
              ids: keepIds ? 'keep' : 'remap',
              on_conflict: overwrite ? 'overwrite' : 'fail',
            },
          })
        }}
      >
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="interchange-file">JSON export</Label>
          <Input
            id="interchange-file"
            type="file"
            accept=".zip,application/zip,.json,application/json"
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null)
              importFile.reset()
            }}
          />
        </div>
        <div className="flex items-center gap-2">
          <Checkbox
            id="interchange-keep-ids"
            checked={keepIds}
            onCheckedChange={(checked) => {
              setKeepIds(checked === true)
              if (checked !== true) setOverwrite(false)
            }}
          />
          <Label htmlFor="interchange-keep-ids">Keep the file’s ids</Label>
        </div>
        <div className="flex items-center gap-2">
          <Checkbox
            id="interchange-overwrite"
            checked={overwrite}
            disabled={!keepIds}
            onCheckedChange={(checked) => {
              setOverwrite(checked === true)
            }}
          />
          <Label htmlFor="interchange-overwrite">
            Overwrite this vault’s records that differ (a backup is taken first)
          </Label>
        </div>
        <div>
          <Button type="submit" disabled={file === null || importFile.isPending}>
            {importFile.isPending ? 'Importing…' : 'Import'}
          </Button>
        </div>
      </form>
      {error && (
        <div role="alert" className="flex flex-col gap-1 text-sm text-destructive">
          <p>{error.message}</p>
          {conflicts.length > 0 && (
            <ul className="list-disc pl-5">
              {conflicts.slice(0, 10).map((conflict) => (
                <li key={`${conflict.table}/${conflict.id}`}>
                  {conflict.name ?? conflict.id}{' '}
                  <span className="opacity-75">({conflict.table})</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {report && (
        <div role="status" className="flex flex-col gap-1 text-sm">
          <p>
            {report.changeset_id === null
              ? 'Nothing to import: the vault already has every record of the file.'
              : `Imported ${report.entities} entities (${total(report.created)} records added, ${total(report.updated)} overwritten, ${total(report.reused)} already here).`}
          </p>
          {total(report.dropped) > 0 && (
            <p className="text-muted-foreground">
              {total(report.dropped)} records were left out: they need records this vault doesn’t
              have.
            </p>
          )}
          {report.references_unmatched.length > 0 && (
            <p className="text-muted-foreground">
              Not found here:{' '}
              {report.references_unmatched.map((reference) => reference.name).join(', ')}.
            </p>
          )}
        </div>
      )}
    </Section>
  )
}
