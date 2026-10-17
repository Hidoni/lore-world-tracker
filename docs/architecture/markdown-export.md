# Markdown / Obsidian export

A vault as a folder of Markdown notes, one per entity, for [Obsidian](https://obsidian.md) or any
other Markdown tool (#148, post-MVP). The export is **one-way**: nothing reads it back (a
round-trip import is out of scope; portable interchange is #149). Code: `lore.core.markdown`
(`render.py`: rich text and properties as Markdown; `export.py`: the export; `router.py`: the
download).

## 1. Audiences and entry points

| Audience | What it holds |
|----------|---------------|
| `readers` (default) | What a reader may see: everything is read with the `READER` policy (`visibility-and-sharing.md` §3), so private entities, aliases, fields, facts, links, blocks and media are left out, links to hidden entities stay plain text, and dates relative to hidden records show as "a date". Safe to share. |
| `author` | Everything: private blocks become `> [!private]` callouts, private entities and values are written like the others (`visibility: "private"` in their properties). Treat it like a backup. |

- **CLI**: `lore vault export-markdown <vault> --out <dir> [--audience readers|author]
  [--calendar <id>]… [--data-dir <dir>]`. It opens the vault **read-only** (no lock, nothing
  written), so it runs next to an author server and also exports a published snapshot
  (`--data-dir` = `LORE_PUBLISH_DIR`). `<dir>` is created and must be empty.
- **API**: `GET /vaults/{v}/export/markdown?audience=…&calendar=…` → a zip
  (`<folder>-markdown.zip`, `-private` for the author's), built in the request's read
  transaction. Author-only: readers (and `?as_reader=true`) get `404`.
- **UI**: Settings → Publishing → Export as Markdown (two download links).

`calendar` (repeatable): calendars to show dates in first. Per dimension, the first listed
calendar that belongs to it wins; otherwise its default calendar; otherwise Absolute.

## 2. Layout and names

```
<dimension>/<dimension>.md              the dimension's own note
<dimension>/<kind plural>/<name>.md     its entities (calendars and timelines included)
Multiverse/<kind plural>/<name>.md      multiversal entities
_media/<file>                           media files (media module)
lore-export.json                        {format: 1, vault_id, vault_name, audience, app_version, exported_at, notes}
```

- Names go through `file_name`: characters unsafe on Windows/macOS/Linux or in Obsidian links
  (`\ / : * ? " < > | # ^ [ ]`, control characters) become spaces, runs of spaces collapse,
  leading/trailing dots and spaces go, at most 120 characters, `Untitled` when nothing is left,
  Windows device names (`con`, `com1`…) get a `_`.
- **Note names are unique in the whole export**, ignoring case (Obsidian resolves `[[name]]` by
  file name, and some file systems ignore case): a name several entities share gets the kind's
  label (`Engine (Gadget)`), then a number (`Engine (Gadget 2)`). Entities are placed in name
  order (`sort_name`, then id), so the same vault exports to the same names. Folder names are
  deduplicated the same way (`Aetheria (2)`); `_media` is reserved.

## 3. A note

YAML frontmatter ("properties"), then the body, then sections:

```markdown
---
lore_id: "0190…"
kind: "Character"
dimension: "[[Aetheria]]"
parent: "[[House Varn]]"
aliases:
  - "The Tidecaller"
tags:
  - "Old-Gods"
summary: "Queen of Varn."
born: "2 Frostfall 1 AF"
dates:
  born:
    "Spire Reckoning": "2 Frostfall 1 AF"
    Absolute: "t = 33,600 s"
---

Body…

## <rich-text field label>

…

## Facts

- **Rank**: 7 · from 3 AF until 9 AF · in What if · caused by [[Battle of Varn]]

## Links

- **parent of**: [[Ilsa]] (heir) · from 1 AF
```

- Properties, in order: `lore_id`, `kind` (label), `dimension` and `parent` (wikilinks, when
  exported), `aliases` (Obsidian's alias property), `tags` (as Obsidian tags: whitespace → `-`,
  characters other than letters, digits, `_`, `-`, `/` removed, a purely numeric tag prefixed
  with `_`), `summary`, `visibility` (only when not public), events' `start`, `end` (`?` for an
  unknown end), `importance`, `category`, `recurring: true` for a series, then the fields the
  audience sees, by field key, then `dates`.
- Field values: `enum`/`multi_enum` by option label, `integer` as a number (a string beyond
  2^53), `boolean`, `measurement` as `"<value> <unit>"`, `duration` as `"60 seconds"` (base
  units) or `"3 year, 2 day"` (calendar units), `time_point` in the primary calendar, `multiple`
  fields as lists; `rich_text` fields become sections; module field types render through their
  module (`media`: `"[[_media/<file>]]"`). Strings are always double-quoted (JSON string syntax,
  valid YAML), so no value changes type when read back.
- `dates`: every time point of the note (event `start`/`end`, `time_point` fields, `<key>.<i>`
  for multiple ones) in every calendar of the dimension the audience sees, primary first,
  Absolute last; only when the dimension has more than one (Absolute counts). Moments are the
  stored ones, shown to anyone who sees the value (as in `EventTimes`); multiversal entities'
  own time points have no moment and are left out.
- **Facts** (the entity's live facts the audience sees, `Facts.of_entity`): `core.exists` as
  "Exists", `core.name` as "Name", others by field label; validity in the primary calendar of
  the fact's timeline's dimension; the timeline's name when it isn't the prime one; the source
  event as a wikilink; the note.
- **Links** (`LinkService.entity_links`, both directions): the label as seen from this entity
  (the inverse label for incoming links), the other end as a wikilink, the role, the validity
  and the timeline (when not prime). Links to entities the export doesn't hold are left out.
- A cover image (media module) is embedded above the body.

## 4. Rich text

The document is read as the audience may see it (`filter_richtext`), then rendered:

| Node / mark | Markdown |
|-------------|----------|
| `paragraph`, `heading` (levels 1–4) | text, `## text` |
| `bulletList`, `orderedList` (`start`) | `- `, `3. `; nested content indented under the marker |
| `blockquote` | `> ` lines |
| `codeBlock` (`language`) | a fence longer than any backtick run in the code |
| `horizontalRule` | `---` |
| `table` | a GFM table, the first row as header; cell blocks joined with `<br>` |
| `visibilityBlock` spoiler / private | `> [!spoiler]- <label>` (collapsed) / `> [!private] <label>` |
| `callout` (`note`, `warning`, `quote`) | `> [!note]`, `> [!warning]`, `> [!quote]` |
| `hardBreak` | `\` + newline |
| `timeRef` | the date in the primary calendar (resolved through what the audience sees; "a date" when it can't be) |
| `bold`, `italic`, `strike`, `code` | `**…**`, `*…*`, `~~…~~`, backticks (literal) |
| `link` | `[text](href)` (`(`, `)`, `<`, `>` percent-encoded) |
| `entityLink` | `[[Note name|text]]` (`[[Note name]]` when they're equal); plain text when the target isn't exported |
| module nodes | the module's renderer (`image`: `![[_media/<file>|<width or alt>]]` and the caption in italics; `lexiconRef`: the headword in italics), else the handler's text |

Text is escaped so that it renders as itself: `` \ ` * _ [ ] < > | # $ ~ & `` get a backslash
(`#` and `$` because Obsidian reads tags and math anywhere), and a line that would start a block
(`- `, `+ `, `> `, `1. `) has its marker escaped. Neighbouring text runs with the same marks are
merged before rendering, and a run's outer spaces stay outside its emphasis delimiters.

## 5. Modules

`ModuleSpec.markdown_contributors` (`modules.md` §2.1): called once per export, for enabled
modules, before any note is written, with a `MarkdownExport` (the vault context, the policy, the
sink, `claim(folder, name)` for a free path) where they register `nodes` (rich-text node type →
renderer), `field_values` (field type → property value) and `cover`.

- **media**: copies the files of the items the audience may see (`Media.visible_conditions`;
  readers: items used where readers see them) to `_media/<uploaded name>` (numbered when taken);
  renders images, `media` fields and covers.
- **languages**: `lexiconRef` → the entry's headword (nothing when the audience can't see it).

Not exported yet: module tables other than media (lexicon entries, map pins, worldline segments,
correspondences, groups' and characters' derived views beyond their links), per-timeline notes,
history. They can be added through contributors.

## 6. Tests

`backend/tests/test_markdown_export.py`: rendering of every node and mark, names, properties, a
note's exact text for readers and the author, dates in a chosen calendar, the download (`404` for
readers), the CLI, and the **canary vault**: the readers' export's files (contents and names)
hold no canary string or id, and the author's holds the canaries.
