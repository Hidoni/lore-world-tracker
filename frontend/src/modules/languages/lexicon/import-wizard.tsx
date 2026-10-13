import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { useImportLexicon, type LexiconImportReport } from '@/data'

import { csvHeaders, IMPORT_FIELDS } from './fields'

const SELECT_CLASS =
  'h-8 rounded-md border border-input bg-transparent px-2 text-sm shadow-xs focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none'
const FIELD_LABEL: Record<(typeof IMPORT_FIELDS)[number], string> = {
  headword: 'Headword',
  romanization: 'Romanization',
  pronunciation: 'Pronunciation',
  part_of_speech: 'Part of speech',
  definitions: 'Glosses (; between)',
  tags: 'Tags',
  etymology: 'Etymology',
  notes: 'Notes',
}

type Step = 'upload' | 'mapping' | 'report'

/** The mapping a header gets first: the field it names, else none. */
function defaultMapping(headers: readonly string[]): Record<string, string> {
  return Object.fromEntries(
    headers.map((header) => {
      const name = header.trim().toLowerCase()
      return [header, (IMPORT_FIELDS as readonly string[]).includes(name) ? name : '']
    }),
  )
}

/**
 * The CSV import (docs/modules/languages.md): upload or paste a CSV, map its columns to entry
 * fields, check it (a dry run reporting each row's problems), then import, all rows or none.
 */
export function ImportWizard({
  vault,
  language,
  open,
  onClose,
}: {
  vault: string
  language: string
  open: boolean
  onClose: () => void
}) {
  const importer = useImportLexicon(vault, language)
  const [step, setStep] = useState<Step>('upload')
  const [csv, setCsv] = useState('')
  const [mapping, setMapping] = useState<Record<string, string>>({})
  const [report, setReport] = useState<LexiconImportReport | null>(null)
  const headers = csvHeaders(csv)
  const close = () => {
    setStep('upload')
    setCsv('')
    setReport(null)
    importer.reset()
    onClose()
  }
  const run = (dryRun: boolean) => {
    importer.mutate(
      { body: { csv, columns: mapping }, dryRun },
      {
        onSuccess: (result) => {
          if (dryRun) {
            setReport(result)
            setStep('report')
            return
          }
          if (result.errors.length > 0) {
            setReport(result)
            return
          }
          toast(`Imported ${result.created} ${result.created === 1 ? 'entry' : 'entries'}`)
          close()
        },
        onError: (error) => {
          toast.error(error.message)
        },
      },
    )
  }
  const mapped = Object.values(mapping).includes('headword')

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) close()
      }}
    >
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Import words from CSV</DialogTitle>
          <DialogDescription>
            {step === 'upload' &&
              'Step 1 of 3: choose a CSV file (or paste one). The first line names the columns.'}
            {step === 'mapping' && 'Step 2 of 3: choose the field each column fills.'}
            {step === 'report' &&
              'Step 3 of 3: the check’s result. Nothing is imported unless every row is valid.'}
          </DialogDescription>
        </DialogHeader>

        {step === 'upload' && (
          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="lexicon-csv-file">CSV file</Label>
              <input
                id="lexicon-csv-file"
                type="file"
                accept=".csv,text/csv"
                className="text-sm"
                onChange={(event) => {
                  const file = event.target.files?.[0]
                  if (file === undefined) return
                  void file.text().then(setCsv)
                }}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="lexicon-csv-text">Or paste it</Label>
              <Textarea
                id="lexicon-csv-text"
                rows={6}
                className="font-mono text-xs"
                value={csv}
                onChange={(event) => {
                  setCsv(event.target.value)
                }}
              />
            </div>
          </div>
        )}

        {step === 'mapping' && (
          <table className="text-sm">
            <thead>
              <tr className="text-left">
                <th className="py-1 font-medium">Column</th>
                <th className="py-1 font-medium">Field</th>
              </tr>
            </thead>
            <tbody>
              {headers.map((header) => (
                <tr key={header}>
                  <td className="py-1 pr-3">{header || <em>(unnamed)</em>}</td>
                  <td className="py-1">
                    <select
                      aria-label={`Field of column ${header}`}
                      className={SELECT_CLASS}
                      value={mapping[header] ?? ''}
                      onChange={(event) => {
                        setMapping({ ...mapping, [header]: event.target.value })
                      }}
                    >
                      <option value="">Skip</option>
                      {IMPORT_FIELDS.map((field) => (
                        <option key={field} value={field}>
                          {FIELD_LABEL[field]}
                        </option>
                      ))}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {step === 'report' && report !== null && (
          <div className="flex flex-col gap-2 text-sm" role="status">
            {report.errors.length === 0 ? (
              <p>
                {report.rows} {report.rows === 1 ? 'row is' : 'rows are'} ready to import.
              </p>
            ) : (
              <>
                <p className="text-destructive">
                  {report.errors.length} {report.errors.length === 1 ? 'problem' : 'problems'} in{' '}
                  {report.rows} rows. Fix the file and check again.
                </p>
                <ul
                  aria-label="Problems"
                  className="max-h-60 overflow-y-auto rounded-md border p-2"
                >
                  {report.errors.map((problem, index) => (
                    <li key={index}>
                      {problem.row === 0 ? 'Header' : `Row ${problem.row}`}
                      {problem.column && ` (${problem.column})`}: {problem.message}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        )}

        <DialogFooter>
          {step !== 'upload' && (
            <Button
              variant="outline"
              onClick={() => {
                setStep(step === 'report' ? 'mapping' : 'upload')
              }}
            >
              Back
            </Button>
          )}
          {step === 'upload' && (
            <Button
              disabled={csv.trim() === ''}
              onClick={() => {
                setMapping(defaultMapping(headers))
                setStep('mapping')
              }}
            >
              Next
            </Button>
          )}
          {step === 'mapping' && (
            <Button
              disabled={!mapped || importer.isPending}
              onClick={() => {
                run(true)
              }}
            >
              Check
            </Button>
          )}
          {step === 'report' && (
            <Button
              disabled={report === null || report.errors.length > 0 || importer.isPending}
              onClick={() => {
                run(false)
              }}
            >
              Import {report?.rows ?? 0} {report?.rows === 1 ? 'entry' : 'entries'}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
