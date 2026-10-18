# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/). Releases happen at the milestones listed in
`docs/plan/roadmap.md` (the first is v0.1.0, at the end of M2).

## [Unreleased]

### Added

- **History compaction** (#159): `lore vault compact-history <vault> --older-than N
  [--dry-run]` replaces the history older than N days with one snapshot per entity (its net
  change over that period) to bound storage. Snapshots show as “Compacted” in the history and
  can't be undone.
- **Uncertainty ranges for time points** (#399, part of #151): "began between 1020 and 1025".
  A time point can carry a range of moments; its anchor stays the best estimate. The range
  widens the point's uncertainty, so as-of states and consistency findings become *possible*
  inside it, and dates show as "between AD 1020 and 1025". Both chronology engines format
  ranges (`format_between`), with new calendar display options for the wording. The picker
  follows in #400.
- **Static site export** (#373–#378): Settings → Publishing → **Export static site**, or
  `lore vault export-static <snapshot> --out <dir>`, turns a published snapshot into a static
  site that any web host serves without a Lore server: the vault's landing page, lists and
  entity pages with the time cursor (#374), the timeline at any zoom with recurring events,
  branches, correspondences and worldlines (#375), module pages (characters, groups, places,
  species, languages and lexicons, maps, the graph) with their images and files (#376), and
  search with the quick switcher (#377). Exports record in several processes
  (`LORE_EXPORT_WORKERS`) and pages load only the files they need (#378). Family trees, org
  charts and the graph work at every setting: any generations, levels, filters and depth
  (#386).
- The dimension wizard's first calendar can be a **Custom calendar**, designed in the calendar
  editor inside the wizard, blank or from a preset, instead of a preset as is (#379).

- **Markdown / Obsidian export** (#148): Settings → Publishing → Export as Markdown, or
  `lore vault export-markdown <vault> --out <dir>`, writes the vault as Markdown notes for
  Obsidian and other Markdown tools: one note per entity with `[[wikilinks]]`, its fields,
  aliases, tags and dates in every calendar as properties, its text, facts and links, and the
  media files. The readers' export holds only what readers see; "everything" includes private
  content.
- **SVG images** (#161): uploaded SVGs show inline wherever images do (pages, covers, galleries,
  `media` fields), as a sanitized copy without scripts, event handlers, links or anything that
  loads from elsewhere. SVGs the sanitizer can't read are refused on upload.

### Fixed

- **Vault picker for readers** (#373): a read-only server no longer shows the create, rename,
  trash and migrate buttons.

## [1.0.0] - 2026-10-17

The MVP (M12: sharing, backup and hardening). Share your world safely: a hardened read-only
server, published snapshots with every secret physically removed, and a reader mode made for
reading, on phones too. Upgrade with confidence: backups and restores you can trust, every
release's vault tested on upgrade. Faster, lighter pages, every page checked for accessibility,
and a user guide (`docs/guides/`). Every MVP requirement is traced to the issues that built it
(`docs/plan/mvp-traceability.md`). Vaults from v0.10.0 open without a migration.

### Added

- **Read-only server mode, hardened** (#138): on a read-only server (`LORE_READ_ONLY=true`) every
  request that would change something is refused before it reaches the app, and serving a vault
  leaves its folder untouched: not even SQLite's side files appear while no author is writing.
- **Published snapshots** (#140): share your world without its secrets. **Settings → Publishing →
  Publish snapshot** (or `lore vault publish <vault>`) writes a copy of the vault for a read-only
  server into `LORE_PUBLISH_DIR`: private entities, fields, blocks, notes, links and module data
  are physically removed, time points anchored to hidden records become plain moments, and
  history, findings and proposals are dropped. A leak check runs before anything is written, and
  an author server refuses to open a snapshot.

- **Reader mode** (#141): a read-only server is a clean wiki for readers: no editing anywhere,
  spoilers folded behind a click (pages, field values, links and blocks), a landing page with the
  dimensions, kinds to browse and the latest pages, and author-only pages kept out of the way.
  Authors can **Preview as reader** from the top bar to see exactly what readers get. Reading is
  more comfortable: bodies at a readable size and width, an optional serif reading font, and on
  phones a navigation drawer, a top bar that fits, and pinch-to-zoom on the timeline.

- **Sharing guide and reader deployment** (#142): `docs/guides/sharing.md` walks through
  visibility, previewing as a reader, publishing, running the read-only `reader` profile of
  `docker-compose.yml` (now functional) and updating it; `deploy/Caddyfile` puts it behind HTTPS
  with an optional password. The container smoke test now runs the whole workflow.

- **User guide** (#146): `docs/guides/` explains the app task by task: getting started,
  calendars, events and recurrence, temporal state, advanced time (branches, correspondences,
  time travelers), modules, sharing and backups.
- **Migrate from the vault picker** (#146): a vault whose schema is behind the app gets a
  **Migrate** button (a backup is taken first).

### Changed

- **Accessibility pass** (#145): maps and the local graph read as lists too ("As a list"), so
  every diagram, map and graph has a keyboard- and screen-reader-friendly view; the minimap works
  with the keyboard; the shortcut sheet (`?`) now lists every shortcut, grouped by where it works.
  Automated accessibility checks (axe) cover every page in both themes, and a keyboard-only
  walkthrough of the main journeys runs in CI. Fixed along the way: the calendar editor's rule
  tabs, a file tile in the media library, the connected-dimensions drawing, and small checkboxes
  on the graph page.

- **Faster pages** (#144): the app loads less code up front (387 kB instead of 514 kB, the
  editor, timeline and settings now load when first used), entity pages no longer pause while
  their panels arrive, and on large worlds the sidebar's events, the findings badges and the
  consistency scan are much quicker. `make bench-pages` measures the entity page and the
  timeline in a browser.

- **Entity pages with many panels open faster** (#363): panels below the fold load as you scroll
  to them (or a moment after the page opens), so a richly linked character's page is ready in
  about 220 ms instead of 330.

### Fixed

- A private map sharing a public map's image no longer hides that image from readers (#140).
- Cross-dimension "effect before its cause" findings were always reported as definite; a circa
  or coarse start now makes them possible (#144).

## [0.10.0] - 2026-10-16

Custom fields and kinds (M11): make the app fit your world. Define kinds of your own (Artifact,
Spell, Ship) with their icon, color, parents and capabilities, give any kind (or every kind)
fields of your own, including ones that change over time, and link kinds with relation fields.
Their entities show in the sidebar, create menus, search, the graph and the timeline like
built-in ones. New tables for custom fields and kinds are added when a v0.9.0 vault opens.

### Added

- **Custom fields** (#133, backend): add your own fields to any kind, or to every kind at once,
  of any field type (also temporal fields with a history, time points and media). They validate,
  show, search and hide from readers like built-in fields. Archive a field to hide it with its
  values, convert its type safely (values follow), reorder fields, and delete a field with its
  values in one undoable step.
- **Custom kinds** (#134, backend): define your own kinds ("Artifact", "Spell", "Ship") with a
  label, icon, color, allowed parents, capabilities and a default visibility; their entities work
  like any other kind's in lists, search, links, the graph and consistency checks. Archive a kind
  to hide it with its entities, delete it once nothing uses it, and convert entities between
  kinds (built-in or custom), mapping their fields, in one undoable step.
- **Settings for custom fields and kinds** (#135): Settings → Kinds (icon picker, color, parents,
  capabilities, archive) and Settings → Fields (per kind, by section, reorder, option editor,
  temporal and visibility settings, safe type changes with a value-mapping step, delete with
  values). Relation fields ("Wielder → Character") are custom link types from a kind and show as
  rows in a Relation fields panel on its entities' pages.

### Fixed

- A date picker opened before the dimension's calendars loaded (the time cursor right after a
  page load) showed no date fields; it now takes the default calendar once they arrive (#136).

## [0.9.0] - 2026-10-16

Media and maps (M10): pictures in a world. Upload images and files into a vault, put images in
pages (paste or drop them), give entities cover images and galleries, and keep it all in a media
library that shows where every file is used. Locations get maps to pin places, characters,
events and labels on, with nested maps to drill into and pins that follow the time cursor:
a destroyed city's pin is gone after its destruction. New tables for media and maps are added
when a v0.8.0 vault opens.

### Added

- **Map editing** (#130): create a map for a location from an image, then pin places, characters,
  events or labels by clicking the map (or create a new location right there), drag pins to move
  them, and edit a pin's label, icon, color, the map it leads into, when it stands and who sees
  it. A tray lists the location's child locations that aren't on the map yet, to drag onto it.
- **Images in pages** (#127): paste or drop images into a page (they upload with progress) or
  add one from the slash menu, with alt text, a caption and a width. Entities get a cover image in
  their header and a gallery to reorder and caption. The new media library lists every file with
  filters (unused, by entity, type, trash), uploads several at once, edits alt texts and captions,
  shows where each file is used, replaces a file everywhere it is used, and trashes files in
  bulk. Media fields get an image picker.
- **Map views** (#129): location pages show their maps (with a switcher when there are several),
  and each map has a full-screen page. Pins show their kind's icon and color, cluster when
  crowded, name themselves on hover and open a card on click with the summary, dates, a link to
  the page and a way into the pinned place's own map; breadcrumbs lead back out. Layers toggle by
  kind, and with a time cursor pins that aren't there are hidden or shown faded. Pinned entities
  get "Show on map".
- **Maps** (#128): attach image maps to locations and pin locations, events, characters or plain
  labels on them. Pins follow the time cursor: a pin with its own period shows while it lasts, any
  other while its target exists (an event: while it happens), and a branch can end a pin early.
  Clicking a location's pin leads into that location's map, and nested maps know their way back
  out. The sample world has a continent map and a city map. New tables `maps_maps` and `maps_pins`
  (migrated automatically).
- **Media** (#126): upload images and files into a vault: png, jpeg, webp, gif and avif images,
  pdf, text and Markdown documents, and SVG (downloaded, never shown inline). Files are checked by
  their content, stored once however often they are uploaded, and served with thumbnails and
  safe headers. Entities get cover images and galleries, and pages can show images. Readers see an
  image only where a page they may see uses it. Unused files go to the trash after 30 days and are
  deleted 30 days later; `lore vault check` reports missing files. New tables `media_items`,
  `media_refs` and `media_gallery` (migrated automatically).

### Fixed

- Map pins near the bottom of the page can be clicked: the page no longer scrolls to the map (or
  the map to the pin) between pressing and releasing the mouse, which made the click miss (#131).
- Creating a location's first map no longer reopens the empty "New map" dialog (#131).

## [0.8.0] - 2026-10-15

Advanced time (M9): stories that branch, worlds whose time runs differently and characters who
travel through it. "What if" branches share their past with the timeline they branch from and
can change what happens after; compare mode lays them side by side. Correspondences relate the
time of two dimensions, so events show what happens concurrently elsewhere and can be anchored
across dimensions. Worldlines give time travelers a life of their own: a Time travel wizard,
a personal timeline in the order they lived it, lived ages, and consistency checks that know about
paradoxes. New tables for branches' changes, correspondences and worldline segments are added
when a v0.7.0 vault opens.

### Added

- **Branches** (#114): alternate timelines. A new branches module creates a "what if" branch
  of any timeline at a branch point, which may be anchored to an event and then moves with it.
  Everything that started before the branch point is shared, everything after diverges.
  Entities and events created in a branch exist only there (and in its own branches): lists, the
  tree, search and the graph show them when you look at that branch. Trashing a branch asks
  before taking its branches and contents along. The sample world asks "What if Aurel survived".
- **Changing history in a branch** (#115): a branch can change what it inherited after its branch
  point: end a reign earlier, end a festival series, let a character die sooner or a rivalry end
  differently. Events anchored to the changed event follow it in that branch only. A branch can
  be compared with its parent (what it created, what it changed, what it carries over), and
  entities can have notes per branch. A new warning flags branch records that start in the shared
  past. New table `entity_timeline_notes` (migrated automatically).
- **Working in branches** (#116): a timeline switcher in the top bar moves every view to another
  timeline. Start a branch from the switcher, by right-clicking the timeline ("Branch here") or
  from an event ("What if…", branching at its start or end). In a branch, inherited events,
  values and links say where they come from; what ended before the branch point is the shared
  past and stays read-only, and what was still going can be edited in this timeline (and
  reverted).
- **Comparing branches** (#117): the timeline shows other timelines' events in lanes of their
  own below the one you're viewing, with a marker where each branch diverges and what it changed
  outlined. A timeline's page shows its lineage, branch point, branches and what it changed, and
  entities can have notes for each branch ("In this timeline she became a pirate").
- **Correspondences** (#118): say which moments of two dimensions happen at the same time, with
  time flowing at different rates if need be ("a day here is a year there"). Sync points can be
  anchored to events and move with them; a move that would make time run backwards in one
  dimension is refused. Moments map across dimensions, through other dimensions when there is no
  direct correspondence, and a warning appears when two routes disagree. The sample world's
  Drowned Gate joins Aetheria and the Dreaming. New tables (migrated automatically).
- **Relating dimensions' time** (#119): a dimension's overview lists its correspondences and the
  dimensions it is connected to, and an editor creates and changes them: sync points picked in
  each dimension's calendars, rates set with "1 day here = 1 year there", a chart of how time maps
  across and a tester that converts any moment. Event pages show when the event happens in every
  connected dimension ("Concurrently in…"), and the timeline can add another dimension's events in
  a lane of their own, placed where they happen on this timeline, with that dimension's calendar
  above them.
- **Worldlines** (#120): time travelers live through time in their own order. A character's
  worldline is a list of segments (where and when they were, and how fast time passed for them),
  with jumps in between; segments can be anchored to events and move with them. The API reports
  where an entity is at a moment (a traveler can be there twice), and a personal timeline of
  what it experienced in its own order with its age at each moment. Entities without segments
  live their lifespan. New table `worldline_segments` (migrated automatically).
- **Time travel** (#121): send a character back in time, into a new branch or to another
  dimension in one step, with departure and arrival events created along the way. When a time
  traveler is present more than once at an event, a warning asks which visit takes part (a
  participation can name it), and another warns when a participant isn't there at all.
- **Worldlines in the app** (#122): a character's page lists the segments of its worldline
  (add, edit, split, reorder, remove) and has a Time travel… wizard. A personal timeline page shows
  what the character lived, in order of lived time, with jumps as breaks (and as a list). Events
  ask which visit of a time traveler takes part, the life panel shows lived ages, and the timeline
  can draw the jumps of chosen characters. An end-to-end journey (E8) covers it (#124).
- **Paradox-aware checks** (#123): "effect before cause" now compares events in different
  dimensions through their correspondences, and stays quiet when a time traveler takes part in
  both and lived the cause first. New warning when a departure or arrival event doesn't match
  the jump it documents; two informational rules (off by default) flag someone meeting their
  other self and events that cause each other in a loop. The sample world has a time traveler.
- **Anchors across dimensions** (#327): an event in one dimension can be anchored to an event in
  another, through their correspondence: it happens at the corresponding moment, and moves when
  either the other event or the correspondence changes. Without a correspondence relating the two
  dimensions, the anchor is refused, and `lore vault check` reports old ones that no longer
  resolve.

## [0.7.0] - 2026-10-14

Exploration (M8): see the world as a web of connections. A graph view maps every entity and how
they link, mention and contain each other: filtered, at the time cursor, saved as named views,
smooth at 10,000 entities and 50,000 links. Every entity page shows its neighborhood, `Alt`+drag
links two entities in either graph, and dropping entities on timeline events makes them
participants or causes. The backlinks panel finds where an entity is named but not yet linked,
and links it in place. No storage changes: v0.6.0 vaults open as they are.

### Added

- **Bigger graphs** (#320): when there are too many entities to show, the graph offers to show
  up to 20,000, and large graphs stay smooth to pan, zoom and hover. Two quick drags no longer
  count as a double click (which opened the entity under the cursor).
  `make bench-graph` measures the graph page at 10k entities in a real browser.
- **Unlinked mentions** (#112): the backlinks panel lists the places where other entities'
  text names this one, by its name or an alias, without linking to it (ignoring case and
  accents). Each one shows in context and can be linked in place with one click, or all of a
  source's at once.
- **Local graph and visual linking** (#111): every entity page shows its neighborhood as a
  small graph that opens the full graph centered on it. In either graph, `Alt`+drag from one
  entity to another opens the link dialog with both filled in. Drop an entity onto a timeline
  event to make it a participant, or another event to make it a cause or an effect.
- **Graph view** (#110): an explorable map of the whole world (Graph, in the command
  palette). Entities are colored by kind and sized by how connected they are. Hovering one
  lights up its neighbors, a click previews it and a double click opens it. Find, filter by
  kind, link type and tag, hide mentions, the hierarchy or loners, or show one entity's
  neighborhood. With the time cursor it shows the world as it was. Filters can be saved as named
  views, and each view remembers its layout.
- **Graph data** (#109): a new graph module serves the entities and how they connect (links,
  mentions and the parent tree) for the whole vault, a dimension, or the neighborhood of an
  entity. It can filter by kind, link type and tag, and show only what existed at a moment and
  the links valid then. It keeps the best-connected entities when there are too many. Readers
  see only what they may, and mentions in private passages don't connect anything for them.

## [0.6.0] - 2026-10-14

Temporal world state (M7): the wiki knows what was true when. Field values, names and
lifespans hold for periods, relationships have start and end dates anchored to events, and a
time cursor in the top bar shows any entity, list, tree or family as it was at a moment, with
uncertain dates flagged. Ages and elapsed time are shown in the world's calendars, and
consistency checks catch a story contradicting itself in time. The sample world gains
lifespans, names and values over time and a marriage, and the v0.6.0 fixture vault keeps them
under upgrade tests.

### Added

- **Facts** (#100): field values that hold for a period of a timeline, existence periods and
  names over time, stored with exact validity bounds that can be anchored to events (and move
  with them) or referenced by other dates. A multiversal entity can have facts in several
  dimensions. Fact values are searchable, and readers only see the facts they may see.
  Time-point field values now take part in time: anchored to an event, they follow it. Vaults
  from earlier versions update their time-point fields once, when they first open.
- **As-of state** (#101): what was true of an entity at a moment of a timeline: whether it
  existed (or whether that is unknown, or only possible because a date is given to the year),
  its name then and its time-dependent field values, flagged when facts overlap. The moment can be
  the dimension's present. Entity lists, the navigation tree and children can show only what
  exists at a moment.
- **Temporal links** (#102): a relationship can hold for a period ("married from the Wedding
  until her death"). Its start and end can be anchored to events and move with them, and other
  dates can refer to them. Links, backlinks, relationships, members, leaders, territory,
  residents and species members can be shown as of a moment, with uncertain ones flagged. Links
  from earlier versions resolve their dates once, when the vault first opens.
- **Time cursor** (#103): the top bar sets the moment the wiki shows: the present, all time, a
  picked date, or one day, month or year before or after. Entity pages then say whether the
  entity existed ("Not yet born", "Died in 1204"), show its name and time-dependent fields as
  they were, and list the relationships, members, residents and other links valid then;
  uncertain ones are shown muted. Lists and the sidebar can hide what didn't exist then.
- **Editing over time** (#104): a field's values over time can be added, changed and removed,
  with a warning where two overlap. Lifespans (born and died, founded and destroyed…) are edited
  on the entity page, and one click creates the birth or death event and ties the date to it.
  Links get start and end dates in the link dialog, and an event's page lists the changes it
  caused.
- **Ages and elapsed time** (#105): how long ago things happened ("34 years, 2 months ago"),
  with huge spans in scientific notation. A character's Life panel shows when they were born and
  died, their age at death and at each event they took part in, and their species' typical
  lifespan.
- **Lifespans in the family tree** (#308): each person's birth and death, and at the time
  cursor who wasn't born yet or had died (muted) and who only possibly lived then.
- **Narrative consistency checks** (#106): warnings when the story contradicts itself in time.
  Someone takes part in an event while not alive, a value or a relationship holds while its
  entity doesn't exist, two values of a field overlap, a parent is born after their child,
  someone belongs to or speaks something that doesn't exist yet, an event happens at a place
  that is gone, a place outlives the place it lies in, a species member lives before the species
  emerged, or a word is attested before its language existed. Optional checks flag two spouses at
  once and leaders who aren't members. Dates known only roughly give "possible" findings.

## [0.5.0] - 2026-10-13

The content modules (M6): the things a world is made of get their own kinds, fields, link types,
panels and views. Misc entries hold anything, locations nest from galaxies to rooms, characters
have relationships, a life and a family tree, groups have members, leaders, an org chart and a
membership history, languages have families, speakers, scripts and a full lexicon editor, and
species have descent and native lands. The sample world gains them all, and the v0.5.0 fixture
vault keeps them under upgrade tests.

### Added

- **Misc entries** (#89): the first feature module. A misc entry (with a free-text category) can
  hold entities of any kind; its page lists its children by kind with an "Add child" menu, and
  the sidebar groups misc entries by category. Text fields suggest the values other entities of
  the kind use. The sample world gains "Time Travel" and "Tide Magic".
- **Locations** (#90): places from galaxies to rooms, nested in a containment tree with type
  icons, can be event sites and have residents, origins and connections (including portals
  between dimensions). A location page lists its contents, the events there (and inside it) and
  its residents and connections. There is a location tree page, and event pages get a
  "Location" field. The sample world gains a galaxy-to-room hierarchy.
- **Characters** (#92): people with family (parent, sibling, spouse), social (romance, friend,
  rival, enemy, mentor, serves) and custom relationships, and a private-by-default "Secret"
  field. A character page groups their relationships, lists the events of their life on the
  timeline, and shows their affiliations from other modules. The sample world gains three
  generations of the royal house of Varn.
- **Groups** (#94): organizations (governments, guilds, houses, secret societies…) with
  sub-groups, members with ranks and titles, leaders, alliances, wars, vassalage and territory.
  A group page lists its members (with sub-groups on request), structure, leadership, relations
  with other groups and territory. Characters can now serve groups. The sample world gains an
  empire with ministries, a secret society and a war.
- **Languages** (#96): languages (with dialects) and writing systems, with descent, borrowing,
  scripts and speakers. A language page shows its family, speakers and scripts, and a language
  family tree view draws the descent of a dimension's languages. The sample world gains a
  language family with a dialect and two scripts.
- **Species** (#91): peoples and creatures with subspecies, descent, members and native lands. A
  species page lists its members, descent and native lands, a descent tree view draws a
  dimension's species, and character pages show their species as a chip. The sample world gains
  the Tideborn and their ancestors.
- **Lexicon backend** (#97): a dictionary per language, with headwords, romanization,
  pronunciation, parts of speech, definitions with examples, etymology, tags and attestation
  periods. Entries sort by the language's own alphabet (multigraphs such as "ch" included) and
  re-sort when it changes. They can be searched, imported from CSV (with a dry run) and exported.
  Private entries, and the entries of hidden languages, stay hidden from readers.
- **Org charts and membership history** (#95): a group's org chart view shows its sub-groups
  and parts top down, with each one's leaders and member count, drawn or as a list. The Members
  panel has a History toggle that shows memberships as bars on the display calendar's time axis,
  ready for membership dates once temporal links arrive.
- **Family trees** (#93): character pages have a Family tree panel, and there is a full family
  tree view. Generations run top to bottom, spouses sit side by side (remarriages too), and
  half-siblings and siblings without known parents are placed correctly. You choose how many
  generations to show each way and whether to include spouses and siblings, and there is a list
  alternative. Clicking a relative re-centers the tree on them. Lifespans show as unknown until
  temporal facts arrive. The layout uses relatives-tree (ADR-0015), which handles 300 people
  in well under a second.
- **Release v0.5.0** (#99): the v0.5.0 golden fixture vault, now with lexicons (an alphabet with
  a digraph, an etymology across languages, a private word and a page referring to a word), and
  upgrade tests for them.
- **Lexicon editor** (#98): each language page has a Lexicon panel (and a full page) with a
  keyboard-first table: type new words in the entry row, edit any cell in place, search, filter
  by part of speech or tag, and sort by the language's own alphabet. 10,000 words scroll
  smoothly. An entry drawer edits definitions with examples, etymology sources, notes, visibility
  and attestation. The CSV import maps columns and runs a dry run that lists problems before
  importing; Export CSV downloads the lexicon. Pronunciation fields have an IPA palette. In rich
  text, `@@` (or "Word" in the slash menu) inserts a word that shows its glosses on hover, and
  search results show lexicon words with their language.

## [0.4.0] - 2026-10-12

The time UI (M5): worlds get their time in the browser. A wizard creates dimensions with preset
calendars; time pickers type dates in any calendar, absolute moments or anchors relative to other
records; a calendar editor shows the impact of each change before applying it; events have
sub-events, causes, participants and recurrence; the timeline view zooms from a dimension's whole
span to single base units, with lanes, eras, overlays, the time cursor, filters, grouping and
direct editing; and rich text carries dates in each reader's calendar. The time journeys E1–E4 run
end to end.

### Added

- **Inline dates in rich text** (#86): insert a date with `/date` or `@date`. It is shown in
  each reader's display calendar, and clicking it lists every calendar with a link to the timeline
  there.
- **E2E journeys E1–E4** (#87): the dimension wizard to an event on the timeline, a calendar
  edit with its impact preview, relative anchors (with a drag on the timeline and a refused
  cycle), and a recurring event's materialized occurrence with a sub-event.
- **Timeline view IV** (#83):
  - Sub-events expand inline into nested lanes, or you can drill in (with a breadcrumb, kept in
    the URL).
  - Double-click empty space to create an event there.
  - Drag an event or its edges to retime it: snapped to the axis unit and typed in the anchor's
    calendar. Relative times show a lock and an "Edit offset" action.
  - A context menu offers sub-events, participants, causes and effects, materializing
    occurrences, expanding and drilling.
  - A filters panel covers importance, categories, tags, participants and participant kinds.
  - Lanes can be grouped by category, importance or participant swimlanes.
  - Selections are announced to screen readers, and a "List view" link opens the outline.
  - API: `GET /tags` and the window's `participant_kind` filter.

- **Causality view and event hierarchy** (#84):
  - Event pages show a compact cause → effect graph (React Flow, laid out by ELK in time order,
    left → right), with a full-page view that has a depth control, focus, timeline choice and a
    list alternative.
  - The sidebar has an Events section: the timeline's top-level events by time, which expand
    lazily into sub-events and materialized occurrences.
  - API: `GET /timelines/{id}/causality`.
  - The event tree now lists a series' materialized occurrences under the series.

- **Timeline view III** (#82): the display calendar's eras as named, coloured bands; astronomical
  overlays (moon phases, seasons…) as phase glyphs once zoomed in enough to tell them apart; the
  time cursor as a line you can drag (snapping to the axis' minor unit) or move with ←/→ on its
  handle; a "Now" marker at the dimension's present. Occurrences of a series are drawn as ticks,
  and materialized occurrences with sub-events get a marker.
- **Timeline view II** (#81): events on the timeline, fetched tile by tile with caching and
  prefetching. They are drawn in sticky lanes: spans with edges fading over their precision
  (softer for circa), instants as diamonds, unknown ends fading out, and series bands with
  counts. A density strip shows what the server culled. Click selects with a preview of dates,
  participants and actions; double-click or Enter opens; ↑/↓ move the selection.
- **Timeline view I** (#80): `/d/<dimension>/timeline` shows an exact viewport from the whole
  dimension (10^100 base units and more) down to 10 base units, kept in the URL. It has a time
  axis with calendar ticks in the display calendar (base units for Absolute) and a minimap. You
  can zoom with the wheel (or Ctrl+wheel), drag to pan, use the keyboard (+/−, Home, ←/→) or the
  toolbar, and go to a date. A `?perf=1` overlay shows fps and render counts.
- **Recurring events in the UI** (#79):
  - The event form gets a recurrence editor. Presets cover every year on this date, every month
    on this day, the nth weekday of the month, weekly on chosen days, and every N base units.
    An advanced mode covers period, interval, filters, positions, time of day, exclusions and
    JSON.
  - The editor shows the rule in words, the next 10 occurrences and its problems.
  - A series' page lists its occurrences with their numbers. Each can be opened, retimed,
    cancelled or restored, given a sub-event or a note, or reverted to the computed occurrence.
  - An occurrence's page says which occurrence of which series it is, and shows what it
    inherits.
  - A rule change that orphans customized occurrences opens a reconciliation dialog with a
    strategy per occurrence; the change is undoable.
- **Event pages and the event outline** (#78): an event's page shows its start and end with
  how each was given (typed dates, moments, or "3 days after the end of <Coronation>" with the
  target linked), its duration, its dates in every calendar, and its timeline, importance and
  category. It also lists its sub-events, its causes and effects (an effect that starts before
  its cause is flagged) and its participants with their roles, each with add, create and remove.
  A dialog creates and edits events (start, end, parent, importance, category, timeline). The
  event outline (`/d/<dimension>/events`) is a lazily expanded tree table of a timeline's events
  with keyboard navigation. Event-tree rows count their `participants`.
- **Calendar editor II and the impact preview** (#77): the editor now covers reforms (one tab
  per set of rules, each with its start), cycles, eras (starts at any time point, including
  event anchors), overlays (a period with an "in days" helper), formats per precision (token
  suggestions and live samples) and display options. Saving an existing calendar previews the
  change first: when something depends on it, a dialog lists every time point that moves or
  breaks, with a strategy per record and bulk actions. The change is applied as one changeset,
  undoable from the toast, and a stale preview can be run again.
- **Calendar editor I** (#76): build a calendar without JSON. You edit its levels, its templates
  (uniform, or named and numbered units, with shared slot ids highlighted), its years (fixed,
  cycle, or rules with a predicate builder, plus exceptions) and its alignment. A JSON tab and a
  live preview by the TS engine sit alongside: problems focus their field, there is a year grid
  and a converter. New calendars start blank or from a preset. A calendar that nothing depends
  on saves directly.
- **Dimension wizard and overview** (#75): the vault home lists dimensions with "Create dimension";
  a five-step wizard (name, base unit, duration with lifetime presets, first calendar from a
  preset with a live preview, review) creates a dimension with its prime timeline and default
  calendar; the dimension overview shows and edits its duration (explaining what blocks a
  shrink), present moment and default calendar, with timelines, counts and recent events.
- **Relative anchors and end specs** (#74): the time point picker's Relative tab (target search,
  edge, occurrence key, offset, live server resolution with the resulting precision, problems
  inline) and `EndSpecPicker` (end date, duration, instant, end of time, unknown; an end before
  the start is refused). `GET /registry` lists `referenceable_slots`, and `/time/resolve` items
  carry `default_precision`.
- **Time inputs** (#73): `BigNumberInput` (grouping, `1e100`, powers, a unit calculator like
  `10^100 years × 31,557,600 s`), `TimePointPicker` (Date tab driven by the calendar's valid
  units per parent, eras, precision, circa, live preview; Absolute tab bounded by the dimension)
  and `DurationPicker` (base units or calendar amounts, with a sign).
- **Consistency UI** (#85): the findings panel (filters for severity, certainty, rule, owner,
  entity and timeline, kept in the URL; explain; suppress with a note; re-check the vault),
  finding badges on entity headers and sidebar trees, Settings → Consistency with rule severities
  (hard rules locked), and a "Save anyway (intentional)" dialog for every write that consistency
  rules refuse.
- **Time display and context** (#72): every moment can be shown in the chosen display calendar
  (`MomentDisplay`, `SpanDisplay`), with a tooltip listing it in all the dimension's calendars,
  the absolute value and its distance from the present; huge years use scientific notation. The
  top bar has a dimension switcher and a display-calendar selector (with Absolute); the
  dimension, timeline, cursor and calendar live in the URL (`tl`, `at`, `cal`) and are
  remembered per vault and dimension. Calendars compile client-side with `@lore/chronology` and
  are cached by id, revision and resolved anchors.
- The golden fixture vault `v0.4.0`.

### Fixed

- An anchor to an occurrence of a series names it by its number ("the 4th occurrence of the
  Festival") rather than its 0-based key ("(occurrence 3)") (#287).
- Vaults created at the same time (concurrent requests) no longer fail with "no such table":
  Alembic's migration context is module-global, so migrations in one process now run one at a
  time (#87).
- The calendar impact preview shows what "Keep the moment" leads to: the moment read through the
  edited calendar (`pinned_display`), no longer its date before the edit (#87).

## [0.3.0] - 2026-10-11

The frontend foundation (M4): a generic wiki usable in the browser. Every kind has an entity page
with fields, a rich-text body with entity links, relations, backlinks and history; the sidebar,
command palette and search find things; settings cover modules, link types and backups. The
editor-linking journey (E5) runs end to end.

### Added

- **Frontend data layer** (#59): `DataSource` (every read, static-export ready) and `Mutations`
  (author-only) over the HTTP API, with hooks for vaults, entities, trees, links, search and
  history, query keys and `invalidateAffected`. Resolved moments are `bigint` in the UI: `make
  gen` brands them `MomentString` and records where they sit (`moments.gen.ts`), and the
  `lore/no-number-moment` lint rule keeps them out of JS numbers.
- **Frontend module framework and KindRegistry** (#60): `defineModule` with typed extension points
  (kinds, routes, nav sections, entity panels, renderers, timeline layers, graph styles, editor
  extensions, commands, settings pages, header media), activation per vault from `GET /registry`
  (dependencies included), lazily loaded module routes, and the KindRegistry merging server kinds
  and link types with module UI configs (`useKind`, `useLinkType`, curated `iconMap`).
- **Entity page and create/trash flows** (#61): one page for every kind (header with inline rename,
  badges, breadcrumbs, aliases, tags and visibility; slots for fields, body, relations, time and
  module panels), a "New…" menu with a create dialog (dimension or multiversal, allowed parents),
  and move to trash, restore and permanent deletion.
- **Renames relabel links** (#70): renaming an entity updates the link text that read its old name
  in other entities' bodies and rich-text fields, in the same undoable change; custom labels stay.
- **E2E harness and journey E5** (#70): a fresh vault per test with API setup helpers, traces on
  failure, and the editor-linking journey (`[[` link, backlink, rename).
- **Rich-text fields use the editor** (#259): the fields panel shows `rich_text` fields with the
  renderer (entity links with kind icons) and edits them in the TipTap editor, so links and other
  marks survive a save.
- **Settings UI** (#69): vault name, default visibility and theme; module toggles that confirm
  the dependencies or dependents they switch too; custom link types (create, edit, archive,
  delete) next to the built-in ones; backups with the private-data notice, downloads, a schedule
  and restore with upload progress; module settings pages in the settings navigation.
- **History UI** (#68): an entity History tab and a recent changes page (filterable by origin)
  with readable diffs and undo, showing why an undo was refused; "Undo the last change" in the
  palette. `GET /changes` takes `origin` filters.
- **Command palette and search** (#67): `Ctrl/Cmd+K` opens a palette with recent entities, a quick
  switcher and commands (new entity, go to a dimension, its timeline or a page, theme, shortcuts,
  module commands). The search page has kind and dimension filters, highlighted snippets and
  module result renderers. `?` lists the keyboard shortcuts.
- **Rich-text editor II** (#64):
  - Spoiler and private blocks with labels, and callouts in three tones, shown framed in the
    editor; spoilers fold for readers.
  - A slash menu with every block type, including module ones.
  - Markdown paste that turns `[[Name]]` into entity links when the name is unique.
- **Links UI** (#66):
  - Relations panel: links grouped by type with labels from the entity's side, roles, details and
    visibility, with edit and remove.
  - Add-link dialog: target search, the link types that fit both kinds (either direction), role,
    details from the type's schema, and visibility.
  - Backlinks and mentions in the context panel.
- **Navigation** (#65):
  - Sidebar: a lazily loaded tree per kind, with multiversal badges. Drag and drop moves an entity
    to an allowed parent, by mouse or keyboard. A context menu offers new child, rename, pin and
    move to trash. Pinned and recently visited entities are kept per vault.
  - Entity lists per kind: virtualized, with name and dimension filters, sorting, and columns from
    the kind's UI config.
  - Trash page: restore, or delete permanently.
- **Rich-text editor** (#63): the body editor (TipTap, loaded lazily) with headings, lists,
  quotes, code, tables, links, markdown shortcuts and a word count. Typing `[[` or `@` links an
  entity, or creates it first. It autosaves after a pause, on blur and when you leave the page,
  and shows its save status. Readers see the read-only renderer: links carry their kind icon and a
  hover card, and missing targets render as plain text. Writes now report the entities whose
  mentions changed, so their backlinks refresh.
- **Field editors** (#62): display and inline editors for every core field type, checked against
  zod schemas built from the field definitions, saved on Enter or blur, with per-field
  visibility, collapsible sections, required fields in the create dialog, module field
  renderers, and a revision-conflict dialog (reload theirs, overwrite, copy mine).
- The golden fixture vault `v0.3.0`.

## [0.2.0] - 2026-10-11

The time core (M3): the full time model is usable through the API, from a dimension's inception
to its end, at cosmic scales and within the performance budgets on the `large` sample world. The
release also carries the first piece of M4, the app shell and vault picker.

### Added

- **M3 Time core** (#44–#56):
  - Time specs on records with a slot registry and the `time_dependencies` graph; dimensions
    and prime timelines (time spec, duration limits, present moment).
  - Calendars: storage, compilation cache, presets, preview endpoints and the dimension wizard.
  - Anchor resolution (absolute, calendar, relative with calendar offsets, occurrence refs) and
    the `/time` endpoints; dependency propagation with cycle rejection, topological
    re-resolution, hard checks and anchor freezing.
  - `TimelineView` (lineage visibility and override resolution for time-bound tables).
  - Events: CRUD with time specs, sub-events, causality, participants and the event tree; the
    timeline window API (overlap queries, importance-based level of detail, density buckets).
  - Recurring series (rule validation, cached series bounds, occurrence expansion in windows)
    and materialized occurrences (materialize, modify, cancel, occurrence anchors, sub-events).
  - Proposals with impact previews: calendar edits (keep dates / pin / constrain) and
    recurrence-rule reconciliation (keep key / rekey / detach / trash).
  - The consistency engine: findings and suppressions API, precision-aware comparisons, core
    structural and event rules, and checks on every changeset.
  - The sample world generator writes time data (`make sample-vault`), and `make perf` checks
    the backend budgets on the `large` world.
  - The golden fixture vault `v0.2.0`.
- **App shell and vault picker** (#58): the SPA's frame (top bar, resizable and collapsible
  sidebar, context panel, mobile drawer), every route of `frontend.md` §4 (placeholders until
  their pages land), light/dark/system themes, per-route error boundaries, toasts for API errors,
  and a vault picker to create, rename and move vaults to the trash that reopens the last vault.

### Changed

- **Write responses report what moved** (#224): `affected.entities` lists every entity whose
  stored moment or time status the write changed through propagation (the events anchored to a
  moved event, the dates of an edited calendar, …), `affected.dimensions` their dimensions, and
  `affected.time_changed` is `true` when any moment or status changed (it was always `false`).
- **Large vaults** (#235–#238), measured on the `large` sample world (100k events, 500k links):
  - Timeline windows: cold windows take 20–100 ms zoomed in and about 330 ms over the whole
    dimension (were 250 ms to 5 s; readers were slowest). Series are looked up through their
    index and their occurrences remembered, sub-event markers cost one probe per event, and a
    reader's window asks what is visible once.
  - Consistency: a full scan takes 8 s (was more than 15 minutes), enabling the duplicate-name
    rule under a second (was 28 minutes), and a write's check no longer grows with the vault.
    Writing a link costs 1.2 ms (was 10 ms): it only re-checks rules about its link type.
  - Calendar proposals: preview under 5 s (was 9 s), apply 22 s (was 2 minutes; the budget
    for an apply on a vault this large is now 30 s). The backup
    taken before a large apply is deflated at the fastest level.
  - A full garbage collection no longer stalls about one request in ten for 85 ms.
  - Series bounds of a far count limit (`count` 10^12 on a yearly rule) take about 5 ms (were
    90 ms, close to their 100 ms budget): both engines go to the super-period counter after 64
    enumerated periods instead of 10,000 (#247).

### Fixed

- A materialized occurrence kept on its key through a recurrence change (`keep_key`, or a direct
  edit that moves it) takes the key's new start as `original_start_t`, so later proposals report
  it as `moved` only when they move it (#230).
- A modified occurrence anchored to its own occurrence ("two days after occurrence 4", said by
  occurrence 4) resolves against the computed occurrence (#234). It used to resolve against its
  own stored moment: `lore vault check` reported `time_moment_stale` and every re-resolution
  moved it again.
- SQL compiled with literal binds renders moments quoted once (`'00015'`, was `'''00015'''`),
  so such statements compare against the right key (#222).
- Pinning an item a calendar edit broke without moving it no longer makes the proposal apply
  answer `409 proposal_stale` (#233).

## [0.1.0] - 2026-10-05

The first release that writes vaults: the core platform (M2) on top of the foundations (M0) and
the chronology engine (M1). It has no UI for worlds yet (M4); everything is reachable through the
`/api/v1` API and the `lore` CLI.

### Added

- **M0 Foundations** (#1–#7, #167):
  - Backend scaffold: FastAPI app factory, `LORE_*` settings, `lore` CLI (`serve`, `openapi`),
    `/api/v1/health` and `/api/v1/meta`, structured logging with request ids.
  - HTTP hardening: Host allowlist, mutation guard (`X-Lore-Client`, `Origin`), security headers
    and CSP, request size limits, problem+json errors.
  - Frontend workspaces: `@lore/web` SPA shell (React, TanStack Router/Query, Tailwind, shadcn)
    and the `@lore/chronology` package skeleton.
  - API contract pipeline: OpenAPI → generated TypeScript types, typed client, drift check.
  - Makefile entry point, dev orchestration (`make dev`), GitHub Actions CI (backend, frontend,
    contract, chronology, e2e, docker) and Dependabot.
  - Multi-stage Docker image and `docker-compose.yml` (author instance on `127.0.0.1:8080`).
- **M1 Chronology engine** (#8–#29):
  - The time engine in Python (`lore.chronology`) and TypeScript (`@lore/chronology`), sharing one
    spec, exported JSON Schemas and conformance vectors that both engines pass.
  - Calendars: definition validation and compilation, moment ⇄ fields conversions, unit bounds,
    ordinals and picker options, parallel cycles (weeks), intercalary units, eras, regimes
    (calendar reforms) and local anchors, astronomical overlays (moons, seasons).
  - Calendar arithmetic (add with constrain/reject, diff by largest unit) and formatting
    (patterns, defaults, intercalary formats, spans, large numbers).
  - Calendar preset library with base-unit scaling.
  - Recurrence rules: intervals, calendar rules, filters and selectors, cycle frequencies,
    counts, exclusions, occurrence numbers and window expansion without bulk storage.
  - Correspondence mapping between dimensions.
  - Timeline viewport math, calendar-aware ticks and tiles.
  - Cross-engine differential fuzzing (`make test-differential`) and benchmarks (`make bench`).
- **M2 Core platform** (#30–#43):
  - Vaults: a data directory of vault folders (`vault.json` + one SQLite database each), with a
    registry, per-vault locks and engines, and the vault API and `lore vault` CLI.
  - Migrations: per-vault Alembic upgrades on open with an automatic pre-migration backup,
    `lore vault migrate` and `lore db check`/`revision` tooling.
  - Core schema v1 (entities, aliases, tags, links, link types, mentions) with exact sortable
    integers and UUIDv7 ids.
  - The backend module framework: module specs, registries of kinds, fields and link types,
    per-vault module enablement.
  - Entities: create, read, update, trash, restore and purge with parent rules and optimistic
    concurrency; listing, the navigation tree, children, the trash and field value suggestions.
  - Links: core and custom link types, link CRUD, per-entity links and backlinks.
  - History: every write is a changeset; the recent changes feed, per-entity history and undo.
  - Rich text: document validation, text and mention extraction, mentions and reader filtering.
  - Search: FTS5 full-text search (incl. trigram matching) and the quick switcher, kept current in
    the write transaction, with reindexing.
  - Visibility: author and reader policies (public, spoiler, private), `?as_reader=true` previews
    and the canary leak-test harness.
  - Backups: manual zip backups, scheduled backups with retention, and restore into a new vault.
  - Maintenance: `lore vault check` (integrity, foreign keys, derived data), `reindex` and
    `optimize`, plus a daily `PRAGMA optimize`.
  - The sample world generator (`make sample-vault SIZE=tiny|small|medium|large`) and the first
    golden fixture vault, which every later migration is tested against.

[Unreleased]: https://github.com/Hidoni/lore-world-tracker/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Hidoni/lore-world-tracker/compare/v0.10.0...v1.0.0
[0.10.0]: https://github.com/Hidoni/lore-world-tracker/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/Hidoni/lore-world-tracker/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/Hidoni/lore-world-tracker/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/Hidoni/lore-world-tracker/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/Hidoni/lore-world-tracker/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/Hidoni/lore-world-tracker/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/Hidoni/lore-world-tracker/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/Hidoni/lore-world-tracker/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Hidoni/lore-world-tracker/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Hidoni/lore-world-tracker/releases/tag/v0.1.0
