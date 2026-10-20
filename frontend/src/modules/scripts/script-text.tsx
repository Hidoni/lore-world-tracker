import type { TextRendererProps } from '@/core/modules'

import { fontStyle, useLanguageFont } from './fonts'

/**
 * Words of a language in its script's font (`textRenderers.language`): the font of the first
 * writing system the language is written in that has one, at its size and in its direction.
 */
export function ScriptText({ vault, owner, text, className }: TextRendererProps) {
  const font = useLanguageFont(vault, owner)
  if (font === null) return <span className={className}>{text}</span>
  return (
    <span
      className={className}
      style={fontStyle(font)}
      dir={font.direction ?? undefined}
      data-script-font={font.writingSystem}
    >
      {text}
    </span>
  )
}
