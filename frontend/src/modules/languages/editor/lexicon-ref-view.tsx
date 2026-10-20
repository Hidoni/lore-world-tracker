import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { LanguageText, type RichTextNodeProps } from '@/core/modules'
import { useLexiconEntry } from '@/data'

/**
 * A word of a lexicon in rich text (`lexiconRef`): its headword, with its glosses in a tooltip.
 * "a word" when the entry is gone or not visible.
 */
export function LexiconRefView({ vault, entryId }: { vault: string; entryId: string | null }) {
  const entry = useLexiconEntry(vault, entryId ?? '', { enabled: entryId !== null })
  if (entry.data === undefined) {
    return (
      <span className="lexicon-ref text-muted-foreground italic" data-lexicon-ref="">
        {entry.isPending && entryId !== null ? '…' : 'a word'}
      </span>
    )
  }
  const glosses = entry.data.definitions.map((definition) => definition.gloss).join('; ')
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        {/* A button: readers reach the gloss with the keyboard too. */}
        <button
          type="button"
          className="lexicon-ref inline cursor-help font-medium italic underline decoration-dotted underline-offset-2"
          data-lexicon-ref=""
        >
          <LanguageText
            vault={vault}
            language={entry.data.language_id}
            text={entry.data.headword}
          />
        </button>
      </TooltipTrigger>
      <TooltipContent className="max-w-sm">
        {[
          entry.data.pronunciation && `/${entry.data.pronunciation}/`,
          entry.data.part_of_speech,
          glosses || 'No gloss yet',
        ]
          .filter(Boolean)
          .join(' · ')}
      </TooltipContent>
    </Tooltip>
  )
}

/** The reader's renderer (`richTextNodeRenderers.lexiconRef`). */
export function LexiconRefNode({ vault, attrs }: RichTextNodeProps) {
  const id = attrs.entryId
  return <LexiconRefView vault={vault} entryId={typeof id === 'string' ? id : null} />
}
