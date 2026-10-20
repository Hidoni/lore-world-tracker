import { useExtensionRecord } from './context'

/**
 * Words of a language (a headword, a sample): set by a module's `textRenderers.language` (the
 * scripts module: in the language's script font), else plain text.
 */
export function LanguageText({
  vault,
  language,
  text,
  className,
}: {
  vault: string
  language: string
  text: string
  className?: string
}) {
  const Renderer = useExtensionRecord('textRenderers', vault).language
  if (Renderer === undefined) return <span className={className}>{text}</span>
  return <Renderer vault={vault} owner={language} text={text} className={className} />
}
