# Alternate timelines, other dimensions and time travel

Lore keeps one exact history per dimension, but stories rarely stay that simple. This guide
covers the three tools for bending it, each provided by a module you can turn off in
**Settings → Modules**:

- **Branches**: "what if…" versions of a dimension's history (`docs/modules/branches.md`).
- **Correspondences**: how time in one dimension lines up with time in another
  (`docs/modules/correspondences.md`).
- **Worldlines**: entities that live their lives out of order, such as time travelers
  (`docs/modules/worldlines.md`).

The model behind all three is in `docs/architecture/time-model.md` (§4, §11, §12).

## 1. Alternate timelines (branches)

Every dimension has exactly one **prime** timeline. A **branch** forks from a parent timeline at a
**branch point**: everything that starts before the branch point is the **shared past**, which
the branch inherits live from its parent; everything from the branch point on can differ.
Branches can fork from other branches, so a dimension's timelines form a tree.

### Create a branch

You can start a branch in three places. Each opens the **New branch** dialog:

- **From the timeline switcher** in the top bar: open it and choose **New branch…**.
- **From a moment on the timeline:** right-click the timeline view where the history should split
  and choose **Branch here…**. The branch point is the moment you clicked.
- **From an event:** on the event's page, open **What if…** and choose **Branch at its start…** or
  **Branch at its end…**. The branch point is anchored to the event, so if you later move the
  event, the branch point moves with it.

In the dialog, give the branch a **Name** (for example "What if Aurel survived"), a **Premise**
(what happens differently, shown on the timeline's page), the timeline to **Branch from** and the
**Branch point**. Then click **Create branch**.

A branch point can only refer to things its parent timeline sees. You can't anchor it to an event
that only exists in a sibling branch.

### Switch timelines

The timeline switcher in the top bar lists every timeline of the current dimension as a tree, each
branch with the moment it branches at. Pick one to view it. The choice goes into the page's URL
(`tl`), and every view follows it: entity pages, lists, the sidebar, search, the graph, maps and
the timeline. Readers only see the switcher when a dimension has branches.

The dimension overview also lists the **Timelines**. A timeline has a page of its own: its
**Timeline** panel shows its kind (prime or branch), lineage, branch point, child branches and the
**Differences** from its parent (**Created in this branch**, **Changed in this branch** and
**Carried over the branch point**). **View this timeline** switches to it.

### Work in a branch

While you view a branch:

- **New things belong to the branch.** An entity you create is **branch-only**: its header says
  **Only in** and the branch's name, and it shows only in that branch and the branches forked
  from it. Events, facts and links you add are the branch's own.
- **The shared past is read-only.** An event, fact or link that ended before the branch point is
  marked **Shared past** with a lock. Change it in the parent timeline instead: the branch sees
  the change.
- **Inherited records** carry an **Inherited from** badge naming the timeline they come from.
- **Override what spans the branch point.** A record that started before the branch point and was
  still going on offers **Edit in this timeline** (on event pages, on temporal field values and
  lifespans, and on links in the relations panel). Only what comes after the branch point can
  change: an event's end, when a recurring event stops, a fact's value or end, a link's end or
  role. The start belongs to the shared past and stays as it is. The changed record is marked
  **Changed in** with the branch's name. **Revert** goes back to the inherited version.
- To "remove" an inherited record from a branch, edit it in the branch so that it ends at the
  branch point.

If you create something in a branch that starts before its branch point, Lore allows it, but the
consistency checks warn you that the branch contradicts the shared past.

### Write notes per timeline

When an entity is the same in every timeline but its story differs ("in this timeline she became
a pirate"), don't fork its page. While you view a branch, the entity's page has a **Notes in this
timeline** panel: rich text that belongs to this entity in this branch only. It saves as you type.
Emptying it deletes the note.

### Compare timelines

In the timeline view, open **Compare** in the toolbar and check timelines under **Compare
with**. Each checked timeline gets its own lanes under the one you're viewing, on the same axis
(read-only). A dashed line marks where each compared branch diverges, and the events a branch
created or changed are outlined in its lanes.

## 2. Other dimensions (correspondences)

Each dimension has its own time, counted from its own inception. When two dimensions are
connected (a portal, a dream realm where a day here is a year there), a **correspondence** says
which moments are simultaneous. It is a list of **sync points**, pairs of moments declared
simultaneous, and time between them is interpolated in straight lines. Correspondences chain:
if A corresponds with B and B with C, Lore can map A to C through B.

### Create a correspondence

1. Open the dimension overview (from the sidebar). Its **Correspondences** section lists this
   dimension's correspondences and draws the connected dimensions (a node opens that dimension).
2. Click **New correspondence**. Give it a **Name** and choose which dimension it **Corresponds
   with**.
3. Under **Sync points**, click **Add sync point** for each pair of simultaneous moments. Each
   side is picked in its own dimension's calendars, and can be anchored to an event (for example,
   the moment the portal opens). Sync points must move forward in both dimensions: the editor
   flags any that go backwards before you save.
4. Choose what happens **Outside the sync points**: **No correspondence (undefined)**, or
   **Continue at a rate** with a **Rate before** and **Rate after**. The rate helper turns a
   sentence like "1 day in Aetheria = 1 year in The Dreaming" into a rate: set the amounts and
   units, then click **Use for both rates**.
5. Click **Save correspondence**. Use **Edit** and **Delete** in the list to change it later.

### Test it

While you edit, the chart plots the mapping between the sync points (tick **Log scale** for very
different rates; hover to see a pair), and the **Conversion tester** maps any moment you type, in
either **Direction**. Both work on the draft, before you save.

### See what happens elsewhere

- **Concurrently in…** on an event's page lists the moment the event starts at in every dimension
  it maps to, written in that dimension's default calendar. It isn't shown when nothing
  corresponds.
- **Dimension lanes:** in the timeline view, open **Dimensions** in the toolbar and check a
  dimension under **Add dimension lane**. Its events appear in lanes of their own, mapped onto
  this dimension's axis, with an extra row of ticks in that dimension's calendar. The lanes are
  read-only. Events whose start has no corresponding moment are left out.

If two chains of correspondences between the same dimensions disagree, the consistency checks
warn you.

## 3. Time travel (worldlines)

Most entities live their lifespan in order. A **worldline** is for those that don't: a time
traveler, a dimension hopper, someone in stasis. It is an ordered list of **segments**, each a
stretch of continuous life in one dimension and timeline, between two moments, with a **rate**
(how much time the entity lives per unit of the world's time). Between segments are **jumps**.
The time the entity has lived along its worldline is its **subjective time**, its age.

Worldlines are available on characters and on any custom kind that **Can travel (worldlines)**
(**Settings → Kinds**).

### Edit segments

The **Worldline** panel on a character's page lists the segments in the order they are lived.
Without segments it says the entity lives its lifespan in order.

- **Add segment** opens a dialog for the dimension, timeline, start and end (**From**,
  **Until**), the rate and a note. Starts and ends can be anchored to events.
- Each segment has buttons to edit, split (at a moment you choose), move up or down, and remove.
- **Clear worldline** removes every segment: the entity lives its lifespan in order again.

### Use the time-travel wizard

**Time travel…** records a jump in one step:

1. **Departure:** leave **At a moment** (optionally recording a departure event, by giving it a
   name) or **At an event** you pick.
2. **Destination:** the dimension, then **Arrive in** **The timeline above** or **A new branch
   ("what if")** with its name (the branch needs the branches module). Set when it **Arrives
   at**, **Stays until (optional)**, its rate, and an optional arrival event.
3. Click **Travel**.

Lore cuts the segment the entity is in at the departure (anchored to the departure event, so it
moves with it), adds the new visit right after it, and makes the entity a participant of the
departure and arrival events.

### Read the personal timeline

**Personal timeline** (on the Worldline panel) shows what the entity lives through in its own
order, on an axis of lived time. Jumps are breaks in the axis, labelled with where they lead.
**List view** shows the same as a table with the age at each item. A character's **Life** panel
also shows ages as lived time once the character has a worldline.

When a traveler visits the same moment twice, Lore can't tell which visit took part in an event.
The event's participants then ask **Which visit?**: choose the segment. Until you do, the
personal timeline marks the event "which visit?" and the consistency checks warn you.

### See jumps on the timeline

In the timeline view, open **Jumps** and find the entities to follow (**Draw the time jumps
of…**). Each jump within this dimension is drawn as an arc from departure to arrival. A jump to or
from another dimension gets a marker at the end that is here. Each entity in the list links to
its **Personal timeline**, which lists the jumps for keyboard and screen-reader use.

## Turning these modules off

- **Branches** off: the switcher offers only the prime timeline, and you can't create or edit
  branches. Branch data is kept.
- **Correspondences** off: "Concurrently in…", dimension lanes and the correspondence editor go
  away. Correspondences are kept.
- **Worldlines** off: every entity lives its lifespan in order again. Segments are kept and come
  back when you turn the module on.
