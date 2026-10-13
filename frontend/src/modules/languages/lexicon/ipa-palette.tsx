import { useEffect, useRef, type ComponentProps } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'

/** The palette's characters, by group (IPA chart order). */
export const IPA_GROUPS: readonly { title: string; chars: readonly string[] }[] = [
  {
    title: 'Vowels',
    chars: [
      'i',
      'y',
      'ɨ',
      'ʉ',
      'ɯ',
      'u',
      'ɪ',
      'ʏ',
      'ʊ',
      'e',
      'ø',
      'ɘ',
      'ɵ',
      'ɤ',
      'o',
      'ə',
      'ɛ',
      'œ',
      'ɜ',
      'ɞ',
      'ʌ',
      'ɔ',
      'æ',
      'ɐ',
      'a',
      'ɶ',
      'ɑ',
      'ɒ',
    ],
  },
  {
    title: 'Consonants',
    chars: [
      'ɓ',
      'ɗ',
      'ɠ',
      'ʄ',
      'ʛ',
      'ɸ',
      'β',
      'θ',
      'ð',
      'ʃ',
      'ʒ',
      'ʂ',
      'ʐ',
      'ç',
      'ʝ',
      'ɣ',
      'χ',
      'ʁ',
      'ħ',
      'ʕ',
      'ɦ',
      'ɬ',
      'ɮ',
      'ʋ',
      'ɹ',
      'ɻ',
      'ɰ',
      'ɭ',
      'ʎ',
      'ʟ',
      'ɱ',
      'ɳ',
      'ɲ',
      'ŋ',
      'ɴ',
      'ʙ',
      'ʀ',
      'ɾ',
      'ɽ',
      'ʈ',
      'ɖ',
      'ɟ',
      'ɢ',
      'ʔ',
      'ʡ',
      'ʘ',
      'ǀ',
      'ǃ',
      'ǂ',
      'ǁ',
    ],
  },
  {
    title: 'Marks',
    chars: ['ˈ', 'ˌ', 'ː', 'ˑ', '.', '|', '‖', 'ʰ', 'ʷ', 'ʲ', 'ˠ', 'ˤ', '̃', '̥', '̩', '̯', '͡'],
  },
]

/**
 * A text input with an IPA character palette (a popover): picking a character inserts it at the
 * caret. Props go to the input; `onValue` gets the text after each change.
 */
export function IpaInput({
  value,
  onValue,
  focusOnMount = false,
  ...props
}: Omit<ComponentProps<typeof Input>, 'value' | 'onChange'> & {
  value: string
  onValue: (value: string) => void
  /** Focuses the input when it appears (a cell starting to edit). */
  focusOnMount?: boolean
}) {
  const input = useRef<HTMLInputElement>(null)
  useEffect(() => {
    if (focusOnMount) input.current?.focus()
  }, [focusOnMount])
  const insert = (char: string) => {
    const element = input.current
    const start = element?.selectionStart ?? value.length
    const end = element?.selectionEnd ?? value.length
    onValue(value.slice(0, start) + char + value.slice(end))
    requestAnimationFrame(() => {
      element?.focus()
      element?.setSelectionRange(start + char.length, start + char.length)
    })
  }
  return (
    <div className="flex items-center gap-1">
      <Input
        ref={input}
        value={value}
        onChange={(event) => {
          onValue(event.target.value)
        }}
        {...props}
      />
      <Popover>
        <PopoverTrigger asChild>
          <Button type="button" variant="outline" size="sm" aria-label="IPA characters">
            ə
          </Button>
        </PopoverTrigger>
        <PopoverContent
          className="w-80"
          // The input keeps its caret.
          onOpenAutoFocus={(event) => {
            event.preventDefault()
          }}
        >
          <div role="group" aria-label="IPA palette" className="flex flex-col gap-2">
            {IPA_GROUPS.map((group) => (
              <div key={group.title}>
                <p className="mb-1 text-xs font-medium text-muted-foreground">{group.title}</p>
                <div className="flex flex-wrap gap-0.5">
                  {group.chars.map((char) => (
                    <button
                      key={char}
                      type="button"
                      title={`Insert ${char}`}
                      className="size-7 rounded-sm font-serif text-base hover:bg-accent"
                      onMouseDown={(event) => {
                        event.preventDefault()
                      }}
                      onClick={() => {
                        insert(char)
                      }}
                    >
                      {/^\p{M}$/u.test(char) ? `◌${char}` : char}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </PopoverContent>
      </Popover>
    </div>
  )
}
