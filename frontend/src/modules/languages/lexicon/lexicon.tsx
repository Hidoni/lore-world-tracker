import { Link } from '@tanstack/react-router'
import { DownloadIcon, UploadIcon } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { lexiconExportUrl, useMutations } from '@/data'
import { cn } from '@/lib/utils'

import { EntryDrawer } from './entry-drawer'
import { ImportWizard } from './import-wizard'
import { LexiconTable } from './lexicon-table'

/**
 * A language's lexicon with its tools: import and export, the table, and the entry drawer. The
 * panel links to the full page.
 */
export function Lexicon({
  vault,
  language,
  full = false,
}: {
  vault: string
  language: string
  full?: boolean
}) {
  const editable = useMutations() !== null
  const [open, setOpen] = useState<string | null>(null)
  const [importing, setImporting] = useState(false)
  return (
    <div className={cn('flex min-h-0 flex-col gap-3', full ? 'flex-1' : 'h-[28rem]')}>
      <div className="flex flex-wrap items-center gap-2">
        {!full && (
          <Link
            to="/v/$vault/m/$module/$"
            params={{ vault, module: 'languages', _splat: `${language}/lexicon` }}
            className="text-sm text-primary underline-offset-2 hover:underline"
          >
            Open the full lexicon
          </Link>
        )}
        <div className="ml-auto flex gap-2">
          {editable && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setImporting(true)
              }}
            >
              <UploadIcon className="size-3.5" /> Import CSV
            </Button>
          )}
          <Button variant="outline" size="sm" asChild>
            <a href={lexiconExportUrl(vault, language)} download>
              <DownloadIcon className="size-3.5" /> Export CSV
            </a>
          </Button>
        </div>
      </div>
      <LexiconTable vault={vault} language={language} onOpen={setOpen} className="flex-1" />
      <EntryDrawer
        vault={vault}
        entryId={open}
        onClose={() => {
          setOpen(null)
        }}
      />
      {editable && (
        <ImportWizard
          vault={vault}
          language={language}
          open={importing}
          onClose={() => {
            setImporting(false)
          }}
        />
      )}
    </div>
  )
}
