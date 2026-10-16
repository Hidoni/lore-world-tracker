import type { AnyExtension, Editor } from '@tiptap/core'
import { EditorContent, useEditor, useEditorState } from '@tiptap/react'
import {
  BoldIcon,
  CodeIcon,
  EyeOffIcon,
  Heading1Icon,
  Heading2Icon,
  Heading3Icon,
  InfoIcon,
  ItalicIcon,
  LinkIcon,
  ListIcon,
  ListOrderedIcon,
  LockIcon,
  MinusIcon,
  QuoteIcon,
  SquareCodeIcon,
  StrikethroughIcon,
  TableIcon,
  type LucideIcon,
} from 'lucide-react'
import { use, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'

import { CreateEntityDialog } from '@/core/entities/create-entity-dialog'
import { loadEditorExtensions, useExtensionList } from '@/core/modules'
import { useDataSource, useMutations } from '@/data'
import { cn } from '@/lib/utils'

import { editorContextOf } from './context'
import { insertEntityLink } from './entity-link'
import { editorExtensions } from './extensions'
import type { NameResolver } from './markdown-paste'
import { isSafeHref, type RichTextDoc } from './schema'
import { SuggestionBridge, type SuggestionState } from './suggestion-state'
import { SuggestionMenu } from './suggestion-menu'
import { TimeRefDialog } from './time-ref-dialog'

/** How long typing pauses before an autosave (frontend.md §6). */
export const AUTOSAVE_DELAY_MS = 1500

/** What a save reports: `conflict` stops autosaving (the conflict dialog takes over). */
export type SaveOutcome = 'saved' | 'conflict' | 'failed'

type Status = 'saved' | 'unsaved' | 'saving' | 'conflict' | 'failed'

const STATUS_TEXT: Record<Status, string> = {
  saved: 'Saved',
  unsaved: 'Unsaved changes',
  saving: 'Saving…',
  conflict: 'Not saved: someone saved first',
  failed: 'Not saved',
}

export interface RichTextEditorProps {
  vault: string
  /** The stored document (`null`: empty). Read once: key the editor to start over. */
  initial: RichTextDoc | null
  /** Saves the document (`null` when empty). */
  save: (doc: RichTextDoc | null) => Promise<SaveOutcome>
  /** The kind the quick create starts with. */
  defaultKind?: string
  label?: string
  placeholder?: string
}

/**
 * The WYSIWYG editor (TipTap, frontend.md §6): the stored schema, `[[`/`@` entity links with quick
 * create, markdown shortcuts, a toolbar, and autosave after a pause in typing, on blur and when
 * leaving the page, with a status ("Unsaved changes", "Saved"). Loaded lazily (`LazyRichTextEditor`).
 */
export default function RichTextEditor({
  vault,
  initial,
  save,
  defaultKind,
  label = 'Body',
  placeholder,
}: RichTextEditorProps) {
  const bridge = useMemo(() => new SuggestionBridge(), [])
  const moduleExtensions = use(loadEditorExtensions(useExtensionList('editorExtensions', vault)))
  const resolveName = useNameResolver(vault)
  /** The editor asking for a date (slash menu, `@date`): the date dialog inserts it there. */
  const [dating, setDating] = useState<Editor | null>(null)
  const requestDate = useCallback((current: Editor) => {
    setDating(current)
  }, [])
  const extensions = useMemo(
    () =>
      editorExtensions({
        bridge,
        resolveName,
        onUnresolvedNames: (names) => {
          toast.warning(`Not linked (no single match): ${names.join(', ')}`)
        },
        ...(placeholder !== undefined ? { placeholder } : {}),
        requestDate,
        extra: moduleExtensions as unknown as AnyExtension[],
      }),
    [bridge, placeholder, moduleExtensions, resolveName, requestDate],
  )
  const autosave = useAutosave(save)
  const editor = useEditor(
    {
      extensions,
      content: initial ?? '',
      editorProps: {
        attributes: {
          'aria-label': label,
          'aria-multiline': 'true',
          role: 'textbox',
          class: 'rich-text min-h-32 px-3 py-2 outline-none',
        },
      },
      onUpdate: ({ editor: current }) => {
        autosave.changed(current)
      },
      onBlur: () => {
        void autosave.flush()
      },
    },
    [extensions],
  )
  const [creating, setCreating] = useState<{ name: string; state: SuggestionState } | null>(null)
  const mutations = useMutations()
  useEffect(() => {
    const context = editorContextOf(editor)
    context.vault = vault
    context.mutations = mutations
  }, [editor, vault, mutations])

  return (
    <div className="rounded-md border">
      <Toolbar editor={editor} />
      <EditorContent editor={editor} />
      <div className="flex items-center justify-between border-t px-3 py-1 text-xs text-muted-foreground">
        <WordCount editor={editor} />
        <span role="status" aria-live="polite" data-status={autosave.status}>
          {STATUS_TEXT[autosave.status]}
        </span>
      </div>
      <SuggestionMenu
        vault={vault}
        editor={editor}
        bridge={bridge}
        onCreate={(name, state) => {
          setCreating({ name, state })
        }}
        onDate={requestDate}
      />
      {dating !== null && (
        <TimeRefDialog
          vault={vault}
          onInsert={(point) => {
            dating.chain().focus().insertTimeRef(point).run()
            setDating(null)
          }}
          onClose={() => {
            setDating(null)
            dating.commands.focus()
          }}
        />
      )}
      {creating !== null && (
        <CreateEntityDialog
          vault={vault}
          initialName={creating.name}
          {...(defaultKind !== undefined ? { initialKind: defaultKind } : {})}
          onClose={() => {
            setCreating(null)
          }}
          onCreated={(entity) => {
            setCreating(null)
            insertEntityLink(editor, creating.state.range, entity)
          }}
        />
      )}
    </div>
  )
}

interface AutosaveState {
  save: RichTextEditorProps['save']
  editor: Editor | null
  /** Bumped by every change. */
  version: number
  savedVersion: number
  timer: ReturnType<typeof setTimeout> | null
  inFlight: Promise<void> | null
  /** The version the newest flush saves. */
  latest: number
  /** After a conflict: the conflict dialog decides. */
  stopped: boolean
}

/**
 * `[[Name]]` in pasted Markdown: the one entity whose name or alias is `Name` (case-insensitive),
 * found with the quick switcher (`/search/quick`).
 */
function useNameResolver(vault: string): NameResolver {
  const source = useDataSource()
  return useCallback<NameResolver>(
    async (name) => {
      const wanted = name.trim().toLowerCase()
      if (wanted === '') return null
      const { items } = await source.quickSearch(vault, { q: name.trim() })
      const matches = new Map(
        items
          .filter((hit) => hit.name.toLowerCase() === wanted || hit.alias?.toLowerCase() === wanted)
          .map((hit) => [hit.entity_id, { id: hit.entity_id, name: hit.name }]),
      )
      const [only] = matches.values()
      return matches.size === 1 && only !== undefined ? only : null
    },
    [source, vault],
  )
}

/**
 * Debounced saving: a change schedules a save; a save waits for the one in flight; `flush` saves
 * now. Unsaved changes are saved when the editor unmounts (navigation) and the page warns before
 * closing with unsaved changes.
 */
function useAutosave(save: RichTextEditorProps['save']) {
  const [status, setStatus] = useState<Status>('saved')
  const ref = useRef<AutosaveState>({
    save,
    editor: null,
    version: 0,
    savedVersion: 0,
    timer: null,
    inFlight: null,
    latest: 0,
    stopped: false,
  })
  useEffect(() => {
    ref.current.save = save
  }, [save])

  const api = useMemo(() => {
    const self = ref.current
    const dirty = () => self.version !== self.savedVersion
    // Read through a function: it changes while a save is awaited.
    const stopped = () => self.stopped
    const flush = async (): Promise<void> => {
      if (self.timer !== null) clearTimeout(self.timer)
      self.timer = null
      const editor = self.editor
      if (stopped() || editor === null || !dirty()) return
      // Read the document now: when leaving the page the editor is gone after this tick.
      const version = self.version
      const doc = editor.isEmpty ? null : editor.getJSON()
      self.latest = version
      if (self.inFlight !== null) await self.inFlight
      // A later flush (newer content) or a save that already covered it.
      if (self.latest !== version || stopped() || self.savedVersion >= version) return
      setStatus('saving')
      self.inFlight = self.save(doc).then((outcome) => {
        self.inFlight = null
        if (outcome === 'saved') {
          self.savedVersion = version
          setStatus(dirty() ? 'unsaved' : 'saved')
        } else {
          if (outcome === 'conflict') self.stopped = true
          setStatus(outcome)
        }
      })
      await self.inFlight
    }
    return {
      flush,
      dirty,
      changed(editor: Editor) {
        self.editor = editor
        self.version += 1
        if (self.stopped) return
        setStatus('unsaved')
        if (self.timer !== null) clearTimeout(self.timer)
        self.timer = setTimeout(() => {
          void flush()
        }, AUTOSAVE_DELAY_MS)
      },
    }
  }, [])

  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (!api.dirty()) return
      void api.flush()
      event.preventDefault()
    }
    window.addEventListener('beforeunload', warn)
    return () => {
      window.removeEventListener('beforeunload', warn)
      // Leaving the page (or the entity): save what's left.
      void api.flush()
    }
  }, [api])

  return { ...api, status }
}

function WordCount({ editor }: { editor: Editor }) {
  const words = useEditorState({
    editor,
    selector: ({ editor: current }) =>
      (current.storage as { characterCount?: { words: () => number } }).characterCount?.words() ??
      0,
  })
  return <span>{words === 1 ? '1 word' : `${words} words`}</span>
}

interface Action {
  label: string
  icon: LucideIcon
  active?: (editor: Editor) => boolean
  run: (editor: Editor) => void
}

const ACTIONS: Action[][] = [
  [
    {
      label: 'Bold',
      icon: BoldIcon,
      active: (e) => e.isActive('bold'),
      run: (e) => e.chain().focus().toggleBold().run(),
    },
    {
      label: 'Italic',
      icon: ItalicIcon,
      active: (e) => e.isActive('italic'),
      run: (e) => e.chain().focus().toggleItalic().run(),
    },
    {
      label: 'Strikethrough',
      icon: StrikethroughIcon,
      active: (e) => e.isActive('strike'),
      run: (e) => e.chain().focus().toggleStrike().run(),
    },
    {
      label: 'Code',
      icon: CodeIcon,
      active: (e) => e.isActive('code'),
      run: (e) => e.chain().focus().toggleCode().run(),
    },
    {
      label: 'Link',
      icon: LinkIcon,
      active: (e) => e.isActive('link'),
      run: (e) => {
        if (e.isActive('link')) {
          e.chain().focus().unsetLink().run()
          return
        }
        const href = window.prompt('Link address (http, https or mailto)')
        if (href !== null && isSafeHref(href.trim())) {
          e.chain().focus().extendMarkRange('link').setLink({ href: href.trim() }).run()
        }
      },
    },
  ],
  [
    {
      label: 'Heading 1',
      icon: Heading1Icon,
      active: (e) => e.isActive('heading', { level: 1 }),
      run: (e) => e.chain().focus().toggleHeading({ level: 1 }).run(),
    },
    {
      label: 'Heading 2',
      icon: Heading2Icon,
      active: (e) => e.isActive('heading', { level: 2 }),
      run: (e) => e.chain().focus().toggleHeading({ level: 2 }).run(),
    },
    {
      label: 'Heading 3',
      icon: Heading3Icon,
      active: (e) => e.isActive('heading', { level: 3 }),
      run: (e) => e.chain().focus().toggleHeading({ level: 3 }).run(),
    },
  ],
  [
    {
      label: 'Bullet list',
      icon: ListIcon,
      active: (e) => e.isActive('bulletList'),
      run: (e) => e.chain().focus().toggleBulletList().run(),
    },
    {
      label: 'Numbered list',
      icon: ListOrderedIcon,
      active: (e) => e.isActive('orderedList'),
      run: (e) => e.chain().focus().toggleOrderedList().run(),
    },
    {
      label: 'Quote',
      icon: QuoteIcon,
      active: (e) => e.isActive('blockquote'),
      run: (e) => e.chain().focus().toggleBlockquote().run(),
    },
    {
      label: 'Code block',
      icon: SquareCodeIcon,
      active: (e) => e.isActive('codeBlock'),
      run: (e) => e.chain().focus().toggleCodeBlock().run(),
    },
    {
      label: 'Divider',
      icon: MinusIcon,
      run: (e) => e.chain().focus().setHorizontalRule().run(),
    },
    {
      label: 'Table',
      icon: TableIcon,
      run: (e) => e.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run(),
    },
  ],
  [
    {
      label: 'Callout',
      icon: InfoIcon,
      active: (e) => e.isActive('callout'),
      run: (e) => e.chain().focus().setCallout('note').run(),
    },
    {
      label: 'Spoiler block',
      icon: EyeOffIcon,
      active: (e) => e.isActive('visibilityBlock', { level: 'spoiler' }),
      run: (e) => e.chain().focus().setVisibilityBlock('spoiler').run(),
    },
    {
      label: 'Private block',
      icon: LockIcon,
      active: (e) => e.isActive('visibilityBlock', { level: 'private' }),
      run: (e) => e.chain().focus().setVisibilityBlock('private').run(),
    },
  ],
]

function Toolbar({ editor }: { editor: Editor }) {
  const active = useEditorState({
    editor,
    selector: ({ editor: current }) =>
      ACTIONS.flat().map((action) => action.active?.(current) ?? false),
  })
  let index = 0
  return (
    <div role="toolbar" aria-label="Formatting" className="flex flex-wrap gap-1 border-b p-1">
      {ACTIONS.map((group, groupIndex) => (
        <div key={groupIndex} className="flex gap-0.5 border-r pr-1 last:border-r-0">
          {group.map((action) => {
            const pressed = active[index++] ?? false
            const Icon = action.icon
            return (
              <button
                key={action.label}
                type="button"
                aria-label={action.label}
                title={action.label}
                aria-pressed={action.active ? pressed : undefined}
                className={cn(
                  'rounded p-1.5 text-muted-foreground hover:bg-accent hover:text-accent-foreground',
                  pressed && 'bg-accent text-accent-foreground',
                )}
                onMouseDown={(event) => {
                  event.preventDefault()
                }}
                onClick={() => {
                  action.run(editor)
                }}
              >
                <Icon className="size-4" />
              </button>
            )
          })}
        </div>
      ))}
    </div>
  )
}
