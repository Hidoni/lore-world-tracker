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

## Consistency rules

| Id | Default | Check |
|----|---------|-------|
| `languages.speaker_outside_existence` | warning | `speaks` validity outside the language's existence |
| `languages.entry_outside_existence` | warning | lexicon attestation outside the language's existence |

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
