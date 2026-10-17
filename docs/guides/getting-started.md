# Getting started

Lore is a wiki for one fictional world (or several), with a strict, exact sense of time. You run
it on your own machine, write in your browser, and keep everything in **vaults**: folders on disk
that hold one world each. This guide takes you from installing the app to a first dimension, a
few linked entities, and the sample world.

## 1. Run Lore

### With Docker (recommended)

You need Docker with the compose plugin. Get the repository, create the two folders the app
writes to, and start it:

```sh
git clone https://github.com/Hidoni/lore-world-tracker.git
cd lore-world-tracker
mkdir -p data published
docker compose up -d
```

The first start builds the image, which takes a few minutes. Then open
`http://127.0.0.1:8080`. The app only listens on this machine.

- Your vaults live in `./data`. Back up that folder, or use the app's backups (`backups.md`).
- Create `data` and `published` yourself: folders Docker creates are owned by root and the app
  can't write to them.
- The container runs as uid/gid 1000. If `id -u` or `id -g` print something else, put
  `LORE_UID=<uid>` and `LORE_GID=<gid>` in a `.env` file next to `docker-compose.yml`.
- `docker compose down` stops it; `docker compose up -d` starts it again.

All settings are environment variables (`docs/architecture/deployment.md` §1). You rarely need
any of them.

### For development

You need `uv`, Node.js (the version in `.nvmrc`) and `make`:

```sh
make setup   # once: backend and frontend dependencies
make dev     # backend on :8000, the app on http://localhost:5173
```

Data goes into `./data`. Ctrl-C stops both servers.

## 2. Create a vault

The first page lists your vaults (**Vaults**). Type a name under **New vault** (for example the
name of your world) and click **Create vault**. Click a vault's name to open it; the pencil and
trash buttons rename it or move it to the trash. Lore reopens the last vault you used; the vault
name in the top bar (**Switch vault**) brings you back to this list.

## 3. Create a dimension

Everything that happens in time happens in a **dimension**: a universe with its own time axis,
from its inception to its end. A new vault is empty, so its home page offers **Create
dimension**. (Later, use the top bar's **New** menu → **Dimension…**.)

The wizard has five steps:

1. **Name**: a name and an optional description.
2. **Base unit**: the smallest unit of time Lore tracks in this dimension (default: second), and
   how many seconds it lasts (**Seconds per unit**, **Divided by**). Every moment is a whole
   number of base units since the inception, so pick the finest unit you will ever need.
3. **Duration**: how long the dimension lasts, in base units. Start from one of the lifetimes
   offered (10,000 years, 13.8 billion years, 10^100 years) or type a number; `1e100` and
   `10^100 years × 31,557,600 s` work too. You can lengthen it later.
4. **First calendar**: **From a preset**, pick a **Preset** (Gregorian, Julian, Shire Reckoning,
   Maya Long Count, …), its **Calendar name**, and where year 1 begins (**Year 1 begins at**, in
   base units since the inception). Or pick **Custom calendar** to design your world's own: give
   it a **Calendar name**, choose what to **Begin with** (**Blank** or a preset), and click
   **Design calendar…**. The calendar editor (`calendars.md` §3) opens on the base unit and
   duration you chose. **Use this calendar** brings you back to the wizard, and **Edit
   calendar…** reopens it. Either way, a preview shows when the first years begin. Events need a
   calendar, so every dimension starts with one. You can add more and change them later
   (`calendars.md`).
5. **Review**, then **Create dimension**.

The dimension's page shows its time spec, its calendars, its timelines and recent events. Set
**The present** there: the dimension's narrative "now", which the time cursor starts at.

## 4. Find your way around

- **Sidebar** (left): links to Home, Search, Recent changes, Consistency, Trash and Settings,
  then **Pinned**, **Recent**, the events of the current timeline, and one tree per kind
  (locations, characters, groups, …). Each kind's heading has a **+** button to create one.
  Right-click a row for **New child…**, **Rename…**, pin and **Move to trash**; drag a row onto
  another to change its parent. The button at the top left hides or shows the sidebar.
- **Top bar**, left to right: the vault, the **dimension** you are working in, the timeline (once
  a dimension has branches), the **display calendar**, the **time cursor**, then **New**,
  **Search**, the context panel toggle, **Preview as reader** (the eye, `sharing.md`), **Settings**
  and **Display**.
- **Context panel** (right): backlinks, unlinked mentions and other context for the page you're
  on.
- **Display** menu: **Theme** (Light, Dark, System) and **Reading font** (Sans-serif, Serif).
  These are kept in your browser.

### The time cursor

Lore shows the world **as of** a moment. The time cursor in the top bar is **Present** (the
dimension's present moment), **All time** (everything, regardless of when), or a moment you
pick. Click it to choose; the arrows on either side step one unit back or forward (pick the unit
under **Step by**). Pick a date and click **Go to this moment** to see entity pages, fields and
relations as they were then. Tick **Hide entities that don't exist then** to drop the dead and
the unborn from lists and trees too.

### The display calendar

Every date is shown in the **display calendar** you pick in the top bar. Switching it rewrites
every date on screen, including dates inside text. **Absolute** shows raw base units. See
`calendars.md`.

### Keyboard

- **Ctrl K** (**⌘ K** on a Mac) opens the command palette: type part of a name or alias and
  press Enter to open that entity, or run a command (**New …**, go to a page, switch the theme,
  **Keyboard shortcuts**). **Search everything for "…"** opens the full search.
- **?** (outside text fields) lists every keyboard shortcut.

## 5. Create entities and link them

Click **New** in the top bar and pick a kind, or use a kind's **+** button in the sidebar. Give
it a **Name**, a **Dimension** (or **Multiversal (every dimension)** for things that exist
everywhere) and optionally a **Parent** (a city inside a country, a sub-group inside a group),
then click **Create**.

An entity page has a header (name, visibility, pin), **Fields** (structured values for the
kind), a **Body** (free text), and **Relations**. Events also get **Time**, **Sub-events**,
**Causes and effects** and **Participants**.

The body is a rich-text editor that saves itself a moment after you stop typing ("Saved"). In
it:

- Type `[[` or `@` and a few letters to link another entity. Pick it with the arrow keys and
  Enter; the last entry, **Create "…" as…**, creates the entity and links it in one go.
- `@date` (or **Date…** in that menu) inserts a date, shown in each reader's display calendar.
- `/` opens the block menu: headings, lists, tables, callouts, spoiler and private blocks.
- Pasting Markdown works, and `[[Name]]` in pasted text becomes a link when the name is unique.

Links in text are **mentions**. For a typed relationship (a character's parent, a member of a
group), use **Add link** under **Relations**: choose the **Link type** and the **Target**, and
optionally a role, the period it was valid and its visibility. Both kinds of link show up on the
other entity's page under **Backlinks**. **Unlinked mentions** lists pages that name an entity
without linking it.

Made a mistake? The command palette's **Undo the last change** reverts it, and **Recent changes**
lists everything you did.

## 6. Search

Press **Ctrl K** for quick name and alias lookups. For full-text search, open **Search** in the
sidebar (or **Search everything for "…"** in the palette). It searches names, aliases, bodies
and fields, accepts `"a phrase"`, `a OR b` and `-word`, and filters by **Kind** and
**Dimension**. Each hit shows where it matched.

## 7. Explore the sample world

To see what a full world looks like, generate the demo world "Aetheria" from a development
checkout:

```sh
make sample-vault                  # SIZE=small: about 1,000 events
make sample-vault SIZE=tiny        # only the hand-made core
```

`SIZE` is `tiny`, `small`, `medium` or `large` (100,000 events, which takes a long time).
`SEED=<n>` gives a different but repeatable world. It is added as a new vault in `./data`, which
is also the folder the Docker setup uses; reload the vault list to see it. Aetheria has several
dimensions, a calendar from every preset plus a custom one using every calendar feature,
recurring events, branches, characters, groups, languages, maps and private content, so it is a
good place to try things before your own world has them.

## Next steps

- `calendars.md`: custom calendars and editing them safely.
- `backups.md`: backups, restore and upgrading.
- `sharing.md`: letting readers see your world.
