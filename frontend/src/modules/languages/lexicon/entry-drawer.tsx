import type { TimePoint } from '@lore/chronology'
import { PlusIcon, XIcon } from 'lucide-react'
import { Suspense, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { Textarea } from '@/components/ui/textarea'
import { TimePointPicker, useTimeContext } from '@/core/time'
import {
  isRevisionConflict,
  useDeleteLexiconEntry,
  useEntities,
  useLexicon,
  useLexiconEntry,
  useMutations,
  useUpdateLexiconEntry,
  type EtymologySource,
  type LexiconDefinition,
  type LexiconEntry,
  type LexiconEntryUpdate,
  type WireTimePoint,
} from '@/data'
import { isDoc, LazyRichTextEditor, RichTextView, type SaveOutcome } from '@/editor'

import { PARTS_OF_SPEECH } from './fields'
import { IpaInput } from './ipa-palette'

type Definition = LexiconDefinition
type Source = EtymologySource
type Visibility = LexiconEntry['visibility']

const SELECT_CLASS =
  'h-9 rounded-md border border-input bg-transparent px-2 text-sm shadow-xs focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none'
const VISIBILITIES: readonly { value: Visibility; label: string }[] = [
  { value: 'public', label: 'Public' },
  { value: 'spoiler', label: 'Spoiler' },
  { value: 'private', label: 'Private' },
]

/**
 * An entry's full details in a side drawer: definitions with examples, etymology (text and the
 * words or languages it comes from), rich-text notes, visibility and when it was attested.
 */
export function EntryDrawer({
  vault,
  entryId,
  onClose,
}: {
  vault: string
  entryId: string | null
  onClose: () => void
}) {
  return (
    <Sheet
      open={entryId !== null}
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <SheetContent side="right" className="w-[32rem] max-w-full overflow-y-auto">
        {entryId !== null && <DrawerBody vault={vault} entryId={entryId} onClose={onClose} />}
      </SheetContent>
    </Sheet>
  )
}

function DrawerBody({
  vault,
  entryId,
  onClose,
}: {
  vault: string
  entryId: string
  onClose: () => void
}) {
  const entry = useLexiconEntry(vault, entryId)
  const editable = useMutations() !== null
  if (entry.isPending) {
    return (
      <SheetHeader>
        <SheetTitle>Loading…</SheetTitle>
        <SheetDescription className="sr-only">The entry is loading.</SheetDescription>
      </SheetHeader>
    )
  }
  if (entry.data === undefined) {
    return (
      <SheetHeader>
        <SheetTitle>Not found</SheetTitle>
        <SheetDescription>This entry was deleted or is not visible.</SheetDescription>
      </SheetHeader>
    )
  }
  return editable ? (
    <EntryForm key={entry.data.id} vault={vault} entry={entry.data} onClose={onClose} />
  ) : (
    <EntryDetails vault={vault} entry={entry.data} />
  )
}

/** The reader's view of an entry. */
function EntryDetails({ vault, entry }: { vault: string; entry: LexiconEntry }) {
  const notes = isDoc(entry.notes) ? entry.notes : null
  return (
    <>
      <SheetHeader>
        <SheetTitle>{entry.headword}</SheetTitle>
        <SheetDescription>
          {[
            entry.romanization,
            entry.pronunciation && `/${entry.pronunciation}/`,
            entry.part_of_speech,
          ]
            .filter(Boolean)
            .join(' · ')}
        </SheetDescription>
      </SheetHeader>
      <div className="flex flex-col gap-3 px-4 pb-4 text-sm">
        <ol className="list-decimal pl-5">
          {entry.definitions.map((definition, index) => (
            <li key={index}>
              {definition.gloss}
              {definition.notes && (
                <span className="text-muted-foreground"> — {definition.notes}</span>
              )}
              {(definition.examples ?? []).map((example, at) => (
                <p key={at} className="italic">
                  {example.text}
                  {example.translation && (
                    <span className="text-muted-foreground not-italic">
                      {' '}
                      ‘{example.translation}’
                    </span>
                  )}
                </p>
              ))}
            </li>
          ))}
        </ol>
        {entry.etymology.text && <p>Etymology: {entry.etymology.text}</p>}
        {notes && <RichTextView vault={vault} doc={notes} />}
      </div>
    </>
  )
}

interface Draft {
  headword: string
  romanization: string
  pronunciation: string
  part_of_speech: string
  definitions: Definition[]
  etymologyText: string
  sources: Source[]
  tags: string
  visibility: Visibility
  attested: boolean
  validFrom: TimePoint | null
  validTo: TimePoint | null
}

function draftOf(entry: LexiconEntry): Draft {
  return {
    headword: entry.headword,
    romanization: entry.romanization ?? '',
    pronunciation: entry.pronunciation ?? '',
    part_of_speech: entry.part_of_speech ?? '',
    definitions: entry.definitions.map((definition) => ({
      ...definition,
      examples: definition.examples ?? [],
    })),
    etymologyText: entry.etymology.text ?? '',
    sources: entry.etymology.sources ?? [],
    tags: entry.tags.join(', '),
    visibility: entry.visibility,
    attested: entry.valid_from !== null || entry.valid_to !== null,
    validFrom: entry.valid_from,
    validTo: entry.valid_to,
  }
}

const optional = (value: string) => (value.trim() === '' ? null : value.trim())
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)

/** The members that changed (an update sends only those). */
export function draftChanges(
  entry: LexiconEntry,
  draft: Draft,
  timelineId: string | null,
): LexiconEntryUpdate {
  const before = draftOf(entry)
  const body: LexiconEntryUpdate = { revision: entry.revision }
  if (draft.headword.trim() !== before.headword) body.headword = draft.headword.trim()
  for (const key of ['romanization', 'pronunciation', 'part_of_speech'] as const) {
    if (draft[key].trim() !== before[key]) body[key] = optional(draft[key])
  }
  const definitions = draft.definitions
    .filter((definition) => definition.gloss.trim() !== '')
    .map((definition) => ({
      gloss: definition.gloss.trim(),
      notes: optional(definition.notes ?? ''),
      examples: (definition.examples ?? []).filter((example) => example.text.trim() !== ''),
    }))
  if (
    !same(
      definitions,
      before.definitions.map((d) => ({ ...d, notes: d.notes ?? null })),
    )
  ) {
    body.definitions = definitions
  }
  const sources = draft.sources.filter((source) =>
    [source.entry_id, source.language_id, source.form?.trim()].some(Boolean),
  )
  if (draft.etymologyText.trim() !== before.etymologyText || !same(sources, before.sources)) {
    body.etymology = { text: optional(draft.etymologyText), sources }
  }
  const tags = draft.tags
    .split(',')
    .map((tag) => tag.trim())
    .filter(Boolean)
  if (!same(tags, entry.tags)) body.tags = tags
  if (draft.visibility !== before.visibility) body.visibility = draft.visibility
  const from = draft.attested ? draft.validFrom : null
  const to = draft.attested ? draft.validTo : null
  if (!same(from, before.validFrom) || !same(to, before.validTo)) {
    // The picker's time points have the schema's shape (named units are slot id strings).
    body.valid_from = from as WireTimePoint | null
    body.valid_to = to as WireTimePoint | null
    if (from !== null || to !== null) body.timeline_id = entry.timeline_id ?? timelineId
  }
  return body
}

function EntryForm({
  vault,
  entry,
  onClose,
}: {
  vault: string
  entry: LexiconEntry
  onClose: () => void
}) {
  const update = useUpdateLexiconEntry(vault)
  const remove = useDeleteLexiconEntry(vault)
  const time = useTimeContext(vault)
  const [draft, setDraft] = useState(() => draftOf(entry))
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => {
    setDraft((current) => ({ ...current, [key]: value }))
  }
  // The notes save on their own (autosave) with the latest revision.
  const latest = useRef(entry)
  useEffect(() => {
    latest.current = entry
  }, [entry])
  const changes = draftChanges(entry, draft, time.timelineId)
  const dirty = Object.keys(changes).length > 1
  const save = () => {
    update.mutate(
      { id: entry.id, body: changes },
      {
        onSuccess: (result) => {
          setDraft(draftOf(result.entry))
          toast('Saved')
        },
        onError: (error) => {
          toast.error(error.message)
        },
      },
    )
  }
  const setDefinition = (index: number, change: Partial<Definition>) => {
    set(
      'definitions',
      draft.definitions.map((definition, at) =>
        at === index ? { ...definition, ...change } : definition,
      ),
    )
  }
  const notes = isDoc(entry.notes) ? entry.notes : null
  const datable = time.dimension !== null && (entry.timeline_id ?? time.timelineId) !== null
  return (
    <form
      className="flex flex-col gap-4 px-4 pb-4"
      onSubmit={(event) => {
        event.preventDefault()
        if (dirty) save()
      }}
    >
      <SheetHeader className="px-0">
        <SheetTitle>{entry.headword}</SheetTitle>
        <SheetDescription>The entry’s details. Notes save as you type.</SheetDescription>
      </SheetHeader>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Headword" id="entry-headword">
          <Input
            id="entry-headword"
            required
            value={draft.headword}
            onChange={(event) => {
              set('headword', event.target.value)
            }}
          />
        </Field>
        <Field label="Romanization" id="entry-romanization">
          <Input
            id="entry-romanization"
            value={draft.romanization}
            onChange={(event) => {
              set('romanization', event.target.value)
            }}
          />
        </Field>
        <Field label="Pronunciation (IPA)" id="entry-pronunciation">
          <IpaInput
            id="entry-pronunciation"
            value={draft.pronunciation}
            onValue={(value) => {
              set('pronunciation', value)
            }}
          />
        </Field>
        <Field label="Part of speech" id="entry-pos">
          <Input
            id="entry-pos"
            list="entry-pos-list"
            value={draft.part_of_speech}
            onChange={(event) => {
              set('part_of_speech', event.target.value)
            }}
          />
          <datalist id="entry-pos-list">
            {PARTS_OF_SPEECH.map((value) => (
              <option key={value} value={value} />
            ))}
          </datalist>
        </Field>
      </div>

      <fieldset className="flex flex-col gap-2">
        <legend className="text-sm font-medium">Definitions</legend>
        {draft.definitions.map((definition, index) => (
          <div key={index} className="flex flex-col gap-1.5 rounded-md border p-2">
            <div className="flex items-center gap-1">
              <Input
                aria-label={`Gloss ${index + 1}`}
                placeholder="Gloss"
                value={definition.gloss}
                onChange={(event) => {
                  setDefinition(index, { gloss: event.target.value })
                }}
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={`Remove definition ${index + 1}`}
                onClick={() => {
                  set(
                    'definitions',
                    draft.definitions.filter((_, at) => at !== index),
                  )
                }}
              >
                <XIcon className="size-4" />
              </Button>
            </div>
            <Input
              aria-label={`Notes on definition ${index + 1}`}
              placeholder="Notes (usage, register…)"
              value={definition.notes ?? ''}
              onChange={(event) => {
                setDefinition(index, { notes: event.target.value })
              }}
            />
            {(definition.examples ?? []).map((example, at) => (
              <div key={at} className="flex items-center gap-1 pl-4">
                <Input
                  aria-label={`Example ${at + 1} of definition ${index + 1}`}
                  placeholder="Example"
                  value={example.text}
                  onChange={(event) => {
                    const examples = [...(definition.examples ?? [])]
                    examples[at] = { ...example, text: event.target.value }
                    setDefinition(index, { examples })
                  }}
                />
                <Input
                  aria-label={`Translation of example ${at + 1} of definition ${index + 1}`}
                  placeholder="Translation"
                  value={example.translation ?? ''}
                  onChange={(event) => {
                    const examples = [...(definition.examples ?? [])]
                    examples[at] = { ...example, translation: event.target.value || null }
                    setDefinition(index, { examples })
                  }}
                />
              </div>
            ))}
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="self-start"
              onClick={() => {
                setDefinition(index, {
                  examples: [...(definition.examples ?? []), { text: '', translation: null }],
                })
              }}
            >
              <PlusIcon className="size-3.5" /> Example
            </Button>
          </div>
        ))}
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="self-start"
          onClick={() => {
            set('definitions', [...draft.definitions, { gloss: '', notes: null, examples: [] }])
          }}
        >
          <PlusIcon className="size-3.5" /> Definition
        </Button>
      </fieldset>

      <fieldset className="flex flex-col gap-2">
        <legend className="text-sm font-medium">Etymology</legend>
        <Textarea
          aria-label="Etymology"
          rows={2}
          value={draft.etymologyText}
          onChange={(event) => {
            set('etymologyText', event.target.value)
          }}
        />
        {draft.sources.map((source, index) => (
          <SourceRow
            key={index}
            vault={vault}
            index={index}
            source={source}
            onChange={(next) => {
              set(
                'sources',
                next === null
                  ? draft.sources.filter((_, at) => at !== index)
                  : draft.sources.map((item, at) => (at === index ? next : item)),
              )
            }}
          />
        ))}
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="self-start"
          onClick={() => {
            set('sources', [...draft.sources, { language_id: null, entry_id: null, form: null }])
          }}
        >
          <PlusIcon className="size-3.5" /> Source
        </Button>
      </fieldset>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Tags" id="entry-tags">
          <Input
            id="entry-tags"
            placeholder="comma, separated"
            value={draft.tags}
            onChange={(event) => {
              set('tags', event.target.value)
            }}
          />
        </Field>
        <Field label="Visibility" id="entry-visibility">
          <select
            id="entry-visibility"
            className={SELECT_CLASS}
            value={draft.visibility}
            onChange={(event) => {
              set('visibility', event.target.value as Visibility)
            }}
          >
            {VISIBILITIES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </Field>
      </div>

      <fieldset className="flex flex-col gap-2">
        <legend className="text-sm font-medium">Attested</legend>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={draft.attested}
            disabled={!datable && !draft.attested}
            onChange={(event) => {
              set('attested', event.target.checked)
            }}
          />
          Dated (first and last attestation, on the current timeline)
        </label>
        {draft.attested && time.dimension !== null && (
          <>
            <TimePointPicker
              dimension={time.dimension}
              lenses={time.lenses}
              value={draft.validFrom}
              label="First attested"
              onChange={(value) => {
                set('validFrom', value)
              }}
            />
            <TimePointPicker
              dimension={time.dimension}
              lenses={time.lenses}
              value={draft.validTo}
              label="Last attested"
              onChange={(value) => {
                set('validTo', value)
              }}
            />
          </>
        )}
      </fieldset>

      <div className="flex flex-col gap-1.5">
        <span className="text-sm font-medium">Notes</span>
        <Suspense fallback={<p className="text-sm text-muted-foreground">Loading the editor…</p>}>
          <LazyRichTextEditor
            vault={vault}
            initial={notes}
            label="Notes"
            save={async (doc): Promise<SaveOutcome> => {
              try {
                await update.mutateAsync({
                  id: entry.id,
                  body: { revision: latest.current.revision, notes: doc },
                })
                return 'saved'
              } catch (error) {
                return isRevisionConflict(error) ? 'conflict' : 'failed'
              }
            }}
          />
        </Suspense>
      </div>

      <div className="flex items-center gap-2">
        <Button type="submit" disabled={!dirty || update.isPending}>
          Save
        </Button>
        <Button
          type="button"
          variant="outline"
          className="ml-auto text-destructive"
          onClick={() => {
            remove.mutate(entry.id, {
              onSuccess: () => {
                toast(`Deleted “${entry.headword}”`)
                onClose()
              },
              onError: (error) => {
                toast.error(error.message)
              },
            })
          }}
        >
          Delete
        </Button>
      </div>
    </form>
  )
}

function Field({ label, id, children }: { label: string; id: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children}
    </div>
  )
}

/** One etymology source: a language, the form, and (when it is in that lexicon) the word. */
function SourceRow({
  vault,
  index,
  source,
  onChange,
}: {
  vault: string
  index: number
  source: Source
  onChange: (source: Source | null) => void
}) {
  const languages = useEntities(vault, { kind: ['language'], limit: 200 })
  const form = (source.form ?? '').trim()
  return (
    <div className="flex flex-wrap items-center gap-1 rounded-md border p-2">
      <select
        aria-label={`Language of source ${index + 1}`}
        className={SELECT_CLASS}
        value={source.language_id ?? ''}
        onChange={(event) => {
          onChange({ ...source, language_id: event.target.value || null, entry_id: null })
        }}
      >
        <option value="">Language…</option>
        {(languages.data?.items ?? []).map((language) => (
          <option key={language.id} value={language.id}>
            {language.name}
          </option>
        ))}
      </select>
      <Input
        aria-label={`Form of source ${index + 1}`}
        className="w-32"
        placeholder="Form"
        value={source.form ?? ''}
        onChange={(event) => {
          onChange({ ...source, form: event.target.value || null })
        }}
      />
      {source.language_id && (
        <SourceEntry
          vault={vault}
          index={index}
          language={source.language_id}
          form={form}
          value={source.entry_id ?? null}
          onChange={(entryId, headword) => {
            onChange({ ...source, entry_id: entryId, form: source.form ?? headword })
          }}
        />
      )}
      <Button
        type="button"
        variant="ghost"
        size="icon"
        aria-label={`Remove source ${index + 1}`}
        onClick={() => {
          onChange(null)
        }}
      >
        <XIcon className="size-4" />
      </Button>
    </div>
  )
}

function SourceEntry({
  vault,
  index,
  language,
  form,
  value,
  onChange,
}: {
  vault: string
  index: number
  language: string
  form: string
  value: string | null
  onChange: (entryId: string | null, headword: string | null) => void
}) {
  const words = useLexicon(vault, language, {
    sort: 'collation',
    limit: 30,
    ...(form ? { q: form } : {}),
  })
  const items = words.data?.pages.flatMap((page) => page.items) ?? []
  const linked = useLexiconEntry(vault, value ?? '', { enabled: value !== null })
  const options =
    linked.data && !items.some((item) => item.id === linked.data.id)
      ? [linked.data, ...items]
      : items
  return (
    <select
      aria-label={`Word of source ${index + 1}`}
      className={SELECT_CLASS}
      value={value ?? ''}
      onChange={(event) => {
        const picked = options.find((item) => item.id === event.target.value)
        onChange(picked?.id ?? null, picked?.headword ?? null)
      }}
    >
      <option value="">Word (optional)…</option>
      {options.map((item) => (
        <option key={item.id} value={item.id}>
          {item.headword}
          {item.definitions[0] ? ` ‘${item.definitions[0].gloss}’` : ''}
        </option>
      ))}
    </select>
  )
}
