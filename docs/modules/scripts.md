# Module: `scripts` — Script fonts

> Fonts for writing systems: upload a font file for a conlang's script, and lexicon headwords,
> words in rich text and the writing system's sample show in that script (#155). Extends
> R-LNG-1.

## Summary

| | |
|---|---|
| Module id | `scripts` |
| Depends on | `languages`, `media` |
| Default enabled | yes |
| Milestone | M13 |

## Kinds

None. The module adds fields to the languages module's kinds.

### Fields (`writing_system`, section "Script font")

| Key | Type | Temporal | Default visibility | Notes |
|-----|------|----------|--------------------|-------|
| `scripts.font` | `media` | no | public | a font file of the media library (WOFF2, WOFF, TTF, OTF) |
| `scripts.font_scale` | `integer` | no | public | text size in the font, in percent of the text around it (default 100; shown within 50–400) |
| `scripts.sample` | `long_text` | no | public | text shown in the font on the writing system's page (default: Latin letters and digits) |

### Fields (`language`, section "Script font")

| Key | Type | Temporal | Default visibility | Notes |
|-----|------|----------|--------------------|-------|
| `scripts.headwords` | `enum` | no | public | `script` (default: in the script's font) or `plain` (plain text) |

## Link types

None. A language's script is the first writing system it is written in
(`languages.uses_script`, in link order) that has a font.

## Tables

None.

## API

None of its own: fonts are media items (`POST /m/media/items`, served by
`GET /m/media/items/{id}/file`), and the fields are entity fields.

## UI

- **Fonts load with `@font-face`** (`modules/scripts/fonts.ts`): the vault's writing systems
  with a font are read once (`GET /entities?kind=writing_system`), and each font file gets one
  rule per page (family `lore-script-<media id>`, `font-display: swap`; the browser downloads a
  font only when text uses it). Text in a font keeps the page's fonts as fallbacks, so letters
  the font lacks still show.
- **Words of a language** (`textRenderers.language`, a core extension point the languages
  module renders through `LanguageText`): lexicon headwords (table, entry drawer), `lexiconRef`
  words in rich text and lexicon search hits show in the language's script font, at its size,
  right to left when the writing system's `direction` is `rtl`. A language with
  `scripts.headwords: plain` shows them as plain text.
- **Writing system pages:** a **Script sample** panel shows the sample in the font; the **Font**
  field (`fieldRenderers` / `fieldEditors` by field key) shows a specimen and the file's name,
  and is edited with the media picker restricted to fonts (**Choose a font**: the library's fonts
  or an upload).

## Consistency rules

None.

## Search, graph, visibility, backup, publish

- `scripts.font` is a `media` field, so the media module tracks it like any image field
  (`media_refs` context `field:scripts.font`): the font is never collected while used, readers
  get the file exactly when they may see the field (its visibility, the writing system's), and
  backups, publishing and the static export copy it.
- The fields aren't searchable (`scripts.font`) or are plain text (`scripts.sample`).

## Disabling / removal notes

Disabling hides the fields (values are kept) and headwords show as plain text again. The font
files stay in the media library; unused, they are collected like any file.

## Implementation notes (#155)

- Font uploads are validated by the media module (`storage.sniff`): the type comes from the
  magic bytes (`wOF2`, `wOFF`, `OTTO`, `00 01 00 00`, `true`), a WOFF/WOFF2 file must be as long
  as its header says and an sfnt (TTF/OTF) file must hold its table directory. Browsers parse
  and sanitize the font tables themselves (OpenType Sanitizer in Chromium and Firefox).
- The font's family is named by its media item, so writing systems sharing a file share the
  rule.
