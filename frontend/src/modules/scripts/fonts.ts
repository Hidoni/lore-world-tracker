import { useMemo } from 'react'

import { mediaFileUrl, useEntities, useEntity, useLinks } from '@/data'

/** The scripts module's field keys (docs/modules/scripts.md). */
export const FONT = 'scripts.font'
export const FONT_SCALE = 'scripts.font_scale'
export const SAMPLE = 'scripts.sample'
export const HEADWORDS = 'scripts.headwords'

/** Font sizes are kept within this range (percent). */
export const MIN_SCALE = 50
export const MAX_SCALE = 400

/** A writing system's font, ready to style text with. */
export interface ScriptFont {
  writingSystem: string
  /** The font's media item. */
  media: string
  /** The CSS font family (`@font-face`), then the page's own fonts as fallbacks. */
  family: string
  /** Percent of the surrounding text. */
  scale: number
  direction: 'ltr' | 'rtl' | null
}

/** The `@font-face` family of a font file (by its media item: writing systems may share one). */
export function familyOf(media: string): string {
  return `lore-script-${media}`
}

/** The family of a font file, its `@font-face` rule added. */
export function useFontFamily(vault: string, media: string): string {
  const family = familyOf(media)
  ensureFontFace(family, mediaFileUrl(vault, media))
  return family
}

/** A font size from a `scripts.font_scale` value: an integer percent, clamped, else 100. */
export function scaleOf(value: unknown): number {
  const percent = typeof value === 'string' || typeof value === 'number' ? Number(value) : NaN
  if (!Number.isFinite(percent)) return 100
  return Math.min(Math.max(Math.round(percent), MIN_SCALE), MAX_SCALE)
}

const injected = new Set<string>()

/**
 * Adds the `@font-face` rule of a font file once per page (the browser downloads it only when
 * text uses the family). `font-display: swap`: text shows in the fallback until the font loads.
 */
export function ensureFontFace(family: string, url: string): void {
  const key = `${family} ${url}`
  if (injected.has(key) || typeof document === 'undefined') return
  injected.add(key)
  const style = document.createElement('style')
  style.dataset.loreScriptFont = family
  const quoted = url.replace(/["\\\n]/g, (char) => `\\${char}`)
  style.textContent = `@font-face { font-family: "${family}"; src: url("${quoted}"); font-display: swap; }`
  document.head.append(style)
}

/** A font's style for text: its family (with the page's fonts after it) and size. */
export function fontStyle(font: Pick<ScriptFont, 'family' | 'scale'>): {
  fontFamily: string
  fontSize?: string
} {
  return {
    fontFamily: `"${font.family}", ui-sans-serif, system-ui, sans-serif`,
    ...(font.scale === 100 ? {} : { fontSize: `${String(font.scale)}%` }),
  }
}

/**
 * The vault's writing systems with a font, by id; their `@font-face` rules are added. Readers get
 * only fonts they may see (the field's visibility).
 */
export function useScriptFonts(vault: string): ReadonlyMap<string, ScriptFont> {
  const systems = useEntities(vault, { kind: ['writing_system'], limit: 500 })
  return useMemo(() => {
    const fonts = new Map<string, ScriptFont>()
    for (const system of systems.data?.items ?? []) {
      const fields: Record<string, unknown> = system.fields
      const media = fields[FONT]
      if (typeof media !== 'string' || media === '') continue
      const family = familyOf(media)
      ensureFontFace(family, mediaFileUrl(vault, media))
      const direction = fields.direction
      fonts.set(system.id, {
        writingSystem: system.id,
        media,
        family,
        scale: scaleOf(fields[FONT_SCALE]),
        direction: direction === 'rtl' || direction === 'ltr' ? direction : null,
      })
    }
    return fonts
  }, [systems.data, vault])
}

/**
 * The font a language's words show in: the font of the first writing system it is written in
 * (`languages.uses_script`) that has one, unless the language shows headwords as plain text.
 */
export function useLanguageFont(vault: string, language: string): ScriptFont | null {
  const fonts = useScriptFonts(vault)
  const entity = useEntity(vault, language)
  const links = useLinks(vault, language, { type: ['languages.uses_script'], direction: 'out' })
  const fields: Record<string, unknown> = entity.data?.fields ?? {}
  if (fields[HEADWORDS] === 'plain') {
    return null
  }
  for (const link of links.data?.items ?? []) {
    const font = fonts.get(link.other.id)
    if (font !== undefined) return font
  }
  return null
}
