# Module: `languages` — Languages, writing systems and lexicon

> Spoken, written and signed languages, their writing systems, their family trees, who speaks
> them, and a full **lexicon** (D16). Covers R-LNG-1, R-LNG-2.

## Summary

| | |
|---|---|
| Module id | `languages` |
| Depends on | – (media for writing-system samples when enabled) |
| Default enabled | yes |
| Milestone | M6 |

## Kinds

| Kind | Label / plural | Icon | Allowed parents | Capabilities |
|------|----------------|------|-----------------|--------------|
| `language` | Language / Languages | `languages` | `language` (dialect), `misc` | body, existence (emerged/extinct), multiversal |
| `writing_system` | Writing system / Writing systems | `type` | `misc` | body, existence, multiversal |

### Fields (`language`)

| Key | Type | Temporal | Default visibility | Notes |
|-----|------|----------|--------------------|-------|
| `modality` | `multi_enum` | no | public | spoken, written, signed, telepathic, other |
| `status` | `enum` | **yes** | public | living, endangered, extinct, constructed, liturgical, other |
| `word_order` | `enum` | no | public | SOV, SVO, VSO, VOS, OVS, OSV, free, other |
| `alphabet_order` | `long_text` | no | public | Space-separated collation order ("a b c ch d …") used to sort the lexicon. Empty means Unicode order. |
| `phonology` | `rich_text` | no | public | |
| `grammar` | `rich_text` | no | public | |
| `code` | `text` | no | public | short code ("hv") |

### Fields (`writing_system`)

| Key | Type | Temporal | Default visibility | Notes |
|-----|------|----------|--------------------|-------|
| `script_type` | `enum` | no | public | alphabet, abjad, abugida, syllabary, logographic, featural, other |
| `direction` | `enum` | no | public | ltr, rtl, ttb, btt, boustrophedon |
| `glyph_count` | `integer` | no | public | |

## Link types

| Key | Source → target | Labels | Symmetric | Temporal | Data |
|-----|-----------------|--------|-----------|----------|------|
| `languages.descended_from` | language → language | descended from / ancestor of | no | optional (`valid_from` = divergence) | – |
| `languages.borrowed_from` | language → language | borrows from / lends to | no | optional | `{note}` |
| `languages.uses_script` | language → writing_system | written in / used by | no | optional | – |
| `languages.speaks` | any (character, group, species, location, custom) → language | speaks / spoken by | no | optional | `{fluency: native|fluent|conversational|basic}` |

## Tables

`languages_lexicon_entries`:

| Column | Type | Notes |
|--------|------|-------|
| `id` | TEXT PK | |
| `language_id` | → entities | |
| `headword` | TEXT | native form (may use any Unicode script) |
| `romanization` | TEXT NULL | |
| `pronunciation` | TEXT NULL | IPA |
| `part_of_speech` | TEXT NULL | suggestions: noun, verb, adjective, adverb, pronoun, preposition, conjunction, interjection, particle, numeral, affix, phrase, other |
| `definitions` | JSON | `[{gloss, notes?, examples?: [{text, translation}]}]` |
| `etymology` | JSON | `{text?, sources?: [{entry_id?, language_id?, form?}]}` |
| `notes` | JSON NULL | rich text |
| `tags` | JSON | string list |
| `collation_key` | TEXT | derived from `alphabet_order` (recomputed when the order changes) |
| `visibility`, `timeline_id NULL`, `valid_from/to spec+t`, `time_status` | | optional attestation period (words appear and disappear) |
| `sort_key`, `revision`, timestamps, `deleted_at` | | |

Indexes: `(language_id, collation_key)`, `(language_id, headword)`, `(language_id, part_of_speech)`.

## API

- `GET /m/languages/{language_id}/lexicon?q=&pos=&tag=&sort=collation|headword|recent&cursor=&limit=&timeline=&at=`
- `POST /m/languages/{language_id}/lexicon`, `PATCH|DELETE /m/languages/lexicon/{entry_id}`
- `POST /m/languages/{language_id}/lexicon/import` (CSV, `dry_run=true` returns a validation
  report; columns map to fields; definitions as `gloss1; gloss2`)
- `GET /m/languages/{language_id}/lexicon/export` (CSV)
- `GET /m/languages/family-tree?dimension=`: `descended_from`/`borrowed_from` graph

## UI

- Sidebar sections "Languages" and "Writing systems".
- Language page panels: **Lexicon** (virtualized table with inline editing, search, POS/tag
  filters, sorting by the language's own alphabet, keyboard-first entry), **Family**
  (ancestors/descendants), **Speakers** (as-of), **Scripts**.
- **Lexicon page** (`/m/languages/{id}/lexicon`): full-width version plus CSV import wizard.
- **Language family tree view** (React Flow + elkjs, time-ordered by divergence).
- Editor extension `lexiconRef` (inline node `{entryId}`): renders the headword with a gloss
  tooltip. Inserted via `@@` or the slash menu.
- IPA input helper (a character palette popover) for the pronunciation field.

Implementation (#98): `frontend/src/modules/languages/lexicon/` and `editor/`. The **Lexicon**
panel (on language pages, first in the main column) and the full page
(`/v/<vault>/m/languages/<language>/lexicon`) share one component: a find box (headword or
romanization start, gloss words), part-of-speech and tag filters, sorting (alphabet, headword,
recently changed), Import CSV / Export CSV, and a virtualized table that fetches pages of 200 as
it nears their end (10,000 words keep only a window of rows in the DOM). Authors type new words in
the entry row at the top (headword, romanization, pronunciation, part of speech, gloss; Enter adds
and returns to the headword) and edit any cell in place (click, type, Enter or leaving saves,
Escape cancels; glosses are `;`-separated and keep each definition's notes and examples by
position; tags are `,`-separated). "Details" opens the **entry drawer**: definitions with notes and
examples, etymology text and sources (a language, a form, and optionally a word of that lexicon),
tags, visibility, attestation (first and last, two time points on the current timeline) and
rich-text notes (autosaved). The **import wizard** takes a file or pasted CSV, maps each column to
a field (headers that name one are mapped already), runs a dry run that lists each row's problems,
and imports only when there are none. Pronunciation inputs have the IPA palette (vowels,
consonants, marks; inserts at the caret). `GET /m/languages/lexicon/{entry_id}` serves one entry
(the drawer, `lexiconRef`), `404` when it may not be seen.

`lexiconRef` (attrs `{entryId, languageId}`): `@@` opens a word menu (full-text search of
`languages.lexicon_entry`; the core `@` menu stays closed), and the slash menu's "Word" types
`@@`. Editor and reader show the headword with pronunciation, part of speech and glosses in a
tooltip, or "a word" when the entry is gone or hidden. The backend handler accepts only those two
id attrs, and reader filtering drops a reference whose language the reader may not see. Search
results render lexicon hits with their language, linking to the lexicon page.

Implementation (#96): `backend/src/lore/modules/languages/` and `frontend/src/modules/languages/`. Panels: **Family** (descended from, ancestor of, dialects, borrows from, lends to; a link
to the tree view), **Speakers** (`speaks` with fluency) and **Scripts** (on languages and, the
other way round, on writing systems). The family tree view (`/v/<vault>/m/languages/family-tree`,
also in the command palette) draws the time context's dimension with React Flow and ELK:
ancestors above descendants, dialects below their language, borrowings dashed and not shaping
the layout; "As a list" gives the same graph as text. The sample world has Old Tidespeech →
Varnish (with the Harbor Cant dialect) and Shoal Tongue, the multiversal Common Trade, Tide Runes
and Spire Glyphs, and speakers. Since v0.5.0 (#99) it also has lexicons: Varnish has its own
alphabet ("th" a letter after "s"), "thalass" comes from Old Tidespeech "thal" (an etymology
source), "velkorran" is private, and the "Sailors' Glossary" refers to "thalass" with a
`lexiconRef`.

Lexicon backend (#97): the model and migration (`languages_lexicon_entries`, on the core
declarative base: the registry tells module tables from core ones by their models), the service
(`lexicon.py`), collation (`collation.py`) and CSV (`lexicon_csv.py`).

- Collation keys: the headword is split into letters of `alphabet_order` by longest match
  (multigraphs such as "ch"), ignoring case and composition; each letter is 8 hex digits, letters
  outside the alphabet after it by code point. Changing a language's fields re-keys its lexicon
  in the same transaction (a `KindExtension.update` hook).
- Attestation: `valid_from`/`valid_to` are time slots of the record type
  `languages.lexicon_entry` (a `SlotProvider` on `timeline_id`), resolved and propagated with the
  `TimeWriter`, and registered with `TimelineView` (open-ended bounds). A bound needs a timeline
  of the language's dimension.
- Visibility: the `VisibilityFilter` hides private entries and those of hidden languages; search
  documents (`languages.lexicon_entry`: headword as name, romanization and pronunciation as
  aliases, glosses as summary, tags as extra) are found only while the language is. An undo
  re-indexes the entries it touched (`REVERT_HOOKS`); purging a language deletes its entries.
- CSV: the import takes JSON `{csv, columns?}` (headers name fields unless mapped; `definitions`
  `gloss1; gloss2`, `tags` by `;` or `,`, `etymology` its text), skips blank lines, and is all or
  nothing; the export writes the same columns. Publish sanitizing waits for the publish
  machinery (M12).

## Consistency rules

| Id | Default | Check |
|----|---------|-------|
| `languages.speaker_outside_existence` | warning | `speaks` validity outside the language's existence |
| `languages.entry_outside_existence` | warning | lexicon attestation outside the language's existence |

Implemented in `lore.modules.languages.consistency` (#106, `consistency.md` §6): a temporal
`speaks` link's validity, and a lexicon entry's attestation period in its timeline, within the
language's existence.

## Search, graph, visibility, publish

- Search contributor: lexicon entries become search docs (`languages.lexicon_entry`) with
  headword/romanization/glosses. Results render with a module renderer and open the entry in the
  lexicon.
- Lexicon entries have their own visibility. They are hidden when the language is hidden. Publish
  sanitizer drops private entries.
- Graph: languages and writing systems are nodes. Lexicon entries are **not** graph nodes.

## Disabling / removal notes

Disabling hides languages, writing systems, link types, lexicon and `lexiconRef` rendering (shown
as plain headword text). Removal would convert languages to `misc` and export lexicons as CSV
attachments.

## Future ideas

Custom script fonts (`scripts` module) to render headwords in the conlang's script; sound-change
appliers and word generators; interlinear glossed texts; per-entry audio (media).
