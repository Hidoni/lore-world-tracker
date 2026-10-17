# Modules

Lore's core gives you dimensions, calendars, timelines, events and the generic wiki: pages, fields,
links, search, history and the timeline view. Everything else comes from **modules**: optional
feature packages that add kinds of entities, fields, link types, panels on pages, and views of
their own. This guide says what each module adds and how to do the main tasks with it. The full
behavior of each module is in `docs/modules/<id>.md`.

## Turn modules on and off

Open **Settings → Modules**. Each module has a switch, a description and the modules it needs.
Every module is on in a new vault.

- Turning a module **off** hides its kinds, fields, links, panels and views. **Nothing is
  deleted**: turn it on again and everything is back.
- Some modules need others (**Maps** needs **Locations** and **Media**). Turning on a module whose
  needs are off, or turning off one that others need, first lists the modules that will switch
  with it; confirm with **Enable all** or **Disable all**.

Module views such as **Open the graph** are also commands in the command palette (`Ctrl/Cmd+K`).

## Entity modules

These add kinds of entities. Each kind gets a section in the sidebar (its **+** button creates
one), a list page and panels on its entities' pages. All of them can have a lifespan (existence),
can be multiversal, and can sit under a misc entry.

### Locations

Places from galaxies to rooms, nested inside each other: a city's parent is its country. Fields
include the location type (which picks the icon in the sidebar), population over time, climate
and area.

- **Panels:** **Contents** (the places inside, by type), **Events here** (time-ordered; tick
  **Include places inside** for the sub-locations too), **Residents** (as of the time cursor) and
  **Connections** (roads, rivers, portals; a portal may lead to another dimension).
- **Set where an event happened** with the **Location** panel on the event's page.
- **Browse the whole tree:** **Open the location tree**, a collapsible outline with a type filter.

### Species

Peoples, creatures and organisms, with subspecies as children.

- **Panels:** **Members** (who is this species, as of the cursor), **Descent** (what it descended
  from and what descends from it) and **Native to** (needs Locations).
- A character's species shows as a chip in their page header.
- **See evolution:** **Open the species descent tree** (with **As a list**).

### Characters

People in your world. Birth and death are the character's lifespan (**Born**, **Died**), which
you can anchor to events.

- **Panels:** **Relationships** (family, social and other, with **Add relationship**), **Family
  tree**, **Affiliations** (groups, residence, origin, species and languages) and **Life** (birth,
  death, and the events they took part in with their age at each).
- **Family tree:** the panel shows two generations each way; click a relative to re-center on
  them (**Back to this character** returns). The full view has controls for the generations up
  and down, **Spouses**, **Siblings** and **As a list**. People not alive at the time cursor are
  muted.
- Characters can have a worldline: see the
  [advanced time guide](advanced-time.md#3-time-travel-worldlines).

### Groups

Governments, armies, guilds, noble houses and secret societies, with sub-groups as children.

- **Panels:** **Members** (ranks and titles; **Include sub-groups**; **History** shows every
  membership as a bar chart over time), **Structure** (sub-groups and parts), **Leadership** (the
  succession), **Group relations** (alliances, wars, vassalage) and **Territory** (needs
  Locations).
- **See the hierarchy:** **Open the org chart** in the Structure panel shows sub-groups with their
  leaders and member counts as of the cursor, with **Levels** and **As a list**.

### Languages

Languages (dialects as children) and writing systems, with a full lexicon.

- **Panels:** **Lexicon**, **Family** (ancestors, descendants, dialects, borrowings),
  **Speakers** (with fluency) and **Scripts**. Writing systems get **Scripts** too, the other way
  round.
- **See the family:** **Open the language family tree** (with **As a list**).
- **Set the alphabetical order:** the language's alphabet order field ("a b c ch d …") sorts the
  lexicon by your language's own alphabet. Leave it empty for Unicode order.

**Work with the lexicon.** The Lexicon panel (also a full page) has a find box, part-of-speech
and tag filters, and sorting by alphabet, headword or recent changes.

- **Add words** in the entry row at the top: headword, romanization, pronunciation, part of
  speech, gloss. Enter adds the word and goes back to the headword. Pronunciation fields have an
  IPA palette.
- **Edit in place:** click a cell, type, then Enter (or leave it) to save, Escape to cancel.
  Separate several glosses with `;` and tags with `,`.
- **Details** (the pencil on a row) opens the full entry: definitions with notes and examples,
  etymology and its sources, tags, visibility, when the word is attested, and notes.
- **Import CSV** maps your columns to fields and checks every row before importing anything.
  **Export CSV** writes the same columns.
- **Refer to a word in a page:** type `@@` in the editor (or choose **Word** in the `/` menu) and
  pick the word. Readers see the headword with its pronunciation and glosses on hover.

### Misc

**Misc entries** are for anything else: concepts, technologies, magic systems, artifacts. Give
one a category ("Magic") to group it in the sidebar. A misc entry can hold entities of any kind,
so it also works as a folder or topic page: its **Children** panel lists them, and **Add child**
creates a child of any kind.

## Media: images and attachments

Upload images (PNG, JPEG, WebP, GIF, AVIF) and documents (PDF, text, Markdown) into the vault.

- **In a page:** paste or drop an image into the editor, or choose **Image** in the `/` menu.
  Click the image to set its caption, alt text and width (**Small**, **Medium**, **Large**,
  **Full**).
- **Cover image:** **Add cover** in an entity's header.
- **Gallery:** the **Gallery** panel on any entity page. Drag to reorder, add captions, and set
  each image's visibility.
- **Media library** (**Open the media library**): every file in the vault, with filters by text,
  type, **Unused only**, the entity that uses it, and **Trash**. Upload several files at once,
  select files to move them to the trash or restore them, and open a file to edit its alt text
  and caption, see where it's **Used by**, download it or **Replace file** (everything that uses it
  shows the new file).

Files no page uses for 30 days go to the trash on their own, and leave the trash after another
30.

## Maps

Image maps of locations, with pins for places, events, characters or anything else (needs
Locations and Media).

- **Add a map:** on a location's page, **New map** in the **Map** panel; name it and pick or
  upload its image. A location can have several maps. **Full screen** opens the map page.
- **Add pins:** click **Edit pins**, then click the map: **Add a pin** finds an entity by name,
  **Create a location here** makes a new child location, or add a label. Drag pins to move them;
  click one to set its label, icon, color, the map it **Drills into**, when it stands, and its
  visibility, or **Remove pin**. The tray of unplaced child locations (**Pin child locations**)
  lets you drag them onto the map. Click **Done editing** when you're finished.
- **Drill down:** a pin on a city can open the city's map (**Drill into map**). Breadcrumbs lead
  back out (continent → country → city).
- **Time cursor:** pins follow it. A pin shows while its target exists (a character between
  birth and death, an event while it happens), unless you give the pin dates of its own. Tick
  **Ghost what isn't there** to see the hidden pins faded instead.
- **Layers** turn pins on and off by kind; pins without a target form the **Labels** layer.
- **As a list** shows the pins as a list, with whether each is there at the cursor.
- A pinned entity's page gets a **Show on map** panel that opens the map at its pin.

## Graph

An explorable network of your entities and how they connect: links, mentions in text, and
parents.

- **Global graph** (**Open the graph**): node color is the kind, size the number of connections.
  Hover to highlight neighbors, click to preview (**Show its neighborhood** focuses on it),
  double-click to open. Type in **Find…** to pick out entities. The layout settles by itself;
  **Freeze** keeps the positions.
- **Filters:** kinds, link types, tags, and toggles for **Mentions**, **Hierarchy** and
  **Orphans**; the entities of **This dimension** or **The whole vault**; and the **Steps from the
  center** when you focus on one entity. With the time cursor at a moment, the graph shows what
  existed then and the links valid then.
- **Saved views:** name the current filters and click **Save view**; apply one from the select.
  Saved views live in this browser only.
- **Local graph:** the **Local graph** panel on every entity page shows its neighbors one or two
  steps out. **Open in the graph** continues on the graph page.
- **Link visually:** `Alt`+drag from one node to another opens the link dialog with both ends
  filled in.
- **As a list**, in both, lists the same entities and connections as text, for keyboard and
  screen-reader use.

## Custom kinds and fields

Add fields to any kind, and kinds of your own ("Artifact", "Spell", "Ship").

- **Settings → Kinds:** **New kind**: label, plural, icon, color, which kinds it **Can be nested
  under**, its capabilities (**Exists in time (lifespans, existence facts)**, **Can be multiversal
  (no home dimension)**, **Can travel (worldlines)**) and the visibility of new entities. A custom
  kind gets a sidebar section, create menus, a graph color and search filters like any built-in
  kind. **Archive** hides a kind and its entities; you can only delete a kind with no entities.
- **Settings → Fields:** pick a kind (or **Every kind**), then **New field**: label, type, options
  for choice fields, **Several values**, **Required**, **Changes over time (a history of
  values)**, **Searchable**, default visibility, section and help text. Fields are listed by
  section; reorder them with the arrows. Built-in fields are listed for reference.
- **Changing a field:** only safe type changes are offered (text to long text, a choice to a
  multiple choice, text to a choice, where you say which option each existing value becomes).
  **Archive** hides a field and keeps its values; deleting a field with values asks you to
  confirm deleting them too. Turning off "changes over time" asks whether to keep the dated
  values hidden or move them to the trash. Every change can be undone from history.
- **Relation fields:** **New relation field** on a kind's Fields page creates a link type from
  that kind to the kinds you choose ("Wielder → Character"). Its pages then show it in the
  **Relation fields** panel, with **Link…** to add one. Edit or archive them in
  **Settings → Link types**.

## Time modules

**Branches** (alternate timelines), **Correspondences** (time across dimensions) and
**Worldlines** (time travel) have a guide of their own: [advanced-time.md](advanced-time.md).
