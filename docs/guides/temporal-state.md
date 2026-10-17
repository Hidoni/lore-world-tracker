# Browsing your world through time

Your world changes: people are born and die, cities are founded and razed, a king holds a title
for twelve years, an alliance breaks. Lore records **when** each of these is true, and lets you
look at the world **as of** any moment: pages, lists, trees, the graph and maps then show what
existed and what held at that moment.

Three things carry time on an entity:

| What | Example | Where you edit it |
|------|---------|-------------------|
| **Existence** | born 1002, died 1061 | the page's **Lifespan** section (§3) |
| **Link validity** | spouse of Ana from the wedding until her death | the link dialog (§4) |
| **Field history** | title "Duke" 1020–1035, then "King" | the field's history (§5) |

Each bound is an ordinary time point: a date in any calendar, an exact moment, or anchored to an
event, with a precision and circa flag (`docs/guides/events-and-recurrence.md` §2–§3). A bound
anchored to an event moves when the event moves.

## 1. The time cursor

The **time cursor** in the top bar says which moment you're looking at:

- **Present**: the dimension's narrative "now". Set it on the dimension's page under **Time** →
  **The present**. Without one, Lore starts at all time.
- **All time**: no moment; everything is shown, with full histories.
- A moment: click the cursor and use the picker under **Moment**, then **Go to this moment**.

The arrows on either side step one unit back or forward ("One year earlier", "One year later");
choose the unit with **Step by**. On the timeline, the cursor is a line you can drag (it snaps to
the axis' units), and a dashed **Now** marker shows the present.

The cursor, the timeline and the display calendar are part of the page address (`?tl=…&at=…`), so
a link or bookmark opens the same view at the same moment.

## 2. What changes with the cursor

With the cursor at a moment:

- **Entity pages** say when the entity doesn't exist then, in the kind's words: "Not yet born",
  "Died in 1204", "Not yet founded", "Destroyed", "Extinct", and so on. They also say when it only
  possibly exists (the moment falls inside an uncertain date), when its existence isn't specified,
  and when it was known by another name then.
- **Fields that change over time** show their value then, with "Changed N times over time" below.
  Where no dated value covers the moment, the field's ordinary (timeless) value shows.
- **Relations** show timeless links plus the dated links valid then. The same goes for module
  panels such as relationships, members, leaders, territory, residents and speakers.
- **Lists and trees:** open the cursor's popover and tick **Hide entities that don't exist then
  (lists and trees)** to leave out what doesn't exist at the cursor. Entities without existence
  periods stay, since they count as always existing. This choice is remembered in your browser.
- **Graph and maps:** the graph shows what existed then and the links valid then. A map hides
  pins of things that aren't there, or shows them faded with **Ghost what isn't there**.

Anything that only *possibly* applies (a bound given as "1023" while the cursor is inside 1023,
or a circa date) is shown muted, with a note saying the moment is inside an uncertain date.

Switch to **All time** to see everything again: static values, every link, and full histories.

## 3. Existence: when an entity exists

Characters, groups, locations, species and languages (and custom kinds that allow it) have a
**Lifespan** section under the page header. Its words follow the kind: Born/Died,
Founded/Dissolved, Founded/Destroyed, Emerged/Extinct.

- With no periods, the section says "Existence not specified: it counts as existing at every
  time." Nothing is ever hidden or flagged for it.
- **Add a period** sets a start, an end, or both. An open start means "since the beginning of
  time", an open end "still exists".
- An entity can have several periods: a city destroyed and rebuilt, a god who died and returned.

**Tie existence to an event.** **Create birth event…** (or founding, emergence, …) asks **When**,
then creates an event named like "Birth of Aldric" and anchors the period's start to it; the
death, dissolution or destruction button does the same for the end. The event is recorded as the
source of the change. From then on, moving the event on the timeline moves the lifespan with it.
You can also anchor a bound to an existing event yourself with the **Relative** tab.

## 4. Relationships that start and end

Links whose type can change over time have a **Valid** section in the link dialog (**Add link** in
the **Relations** panel, or editing an existing link):

- **From** shows **Always** until you click its set button; **Until** shows **Still**. **Clear**
  makes a bound open again.
- **Until** is the first moment the link no longer holds: a marriage valid until the death of one
  spouse ends exactly at that death.
- Use the **Relative** tab to anchor bounds to events: "from the end of the Wedding until the
  start of the Death of Ana". If either event moves, the marriage follows.
- Some link types are timeless (a sibling is always a sibling) and show no bounds. Others require
  one, and the dialog says "This link type needs a start or an end."

On the page, each link shows its validity. With the cursor at a moment, links outside their
validity drop out of the relations panel, the module panels and the graph.

## 5. Fields that change over time

Some fields are **temporal**: they keep a history of values, such as a character's titles. For
your own fields (custom fields module), turn on **Changes over time (a history of values)** when
defining the field in **Settings → Fields**.

A temporal field has a history button next to it (**Values over time**). It opens the list of its
dated values: **Add a value**, or edit or delete one. Each value has:

- the value itself, and **Valid**: its **From** and **Until** bounds, as for links;
- **Caused by**: optionally, the event that brought the change (a coronation). That event's page
  then lists it under **Changes caused**;
- a **Note** and a **Visibility**.

The field's ordinary value is the default shown when no dated value covers the moment. Editing the
field directly changes that default, not the history.

A field that holds one value at a time can't have two dated values at once. If two overlap, the
history flags it ("Overlaps another value: the later one wins where they overlap.") and the
consistency engine reports it. Fields that hold several values (titles) may overlap freely.

## 6. Precision: certain and possible

Bounds have a precision. "Died 1061" at year precision means some moment in 1061, so with the
cursor in mid-1061 Lore can't tell whether the character is alive. It shows the entity as
*possibly* existing, and the consistency engine reports conflicts that depend on such a date as
*possible* rather than definite. Give bounds the precision you actually know: a day you didn't
choose would make Lore certain of something you aren't.

## 7. Findings about time

The consistency engine compares what you recorded and reports contradictions as **findings**.
Narrative rules are warnings by default: they never stop you writing fiction. The ones about the
state of the world over time include:

| Rule | Finds |
|------|-------|
| `core.link.outside_existence` | a dated link valid while one of its ends doesn't exist (married before birth) |
| `core.fact.outside_existence` | a dated field value outside the entity's existence |
| `core.fact.overlap` | two values of a single-valued field at the same time |
| `core.event.participant_not_existing` | a participant that doesn't exist during the event |
| `characters.parent_born_after_child` | a parent born after the child |
| `groups.member_outside_group_existence` | a membership outside the group's existence |
| `locations.event_at_nonexistent_location` | an event at a place that doesn't exist then |
| `locations.child_outside_parent_existence` | a district existing outside its city's existence |
| `species.member_before_emergence` | an entity of a species before the species emerged |
| `languages.speaker_outside_existence` | a speaker link outside the language's existence |
| `characters.concurrent_spouses` | two spouses at once (off by default) |

Entities without existence periods count as existing at every time, so they never trigger these
rules. With the worldlines module on, time travelers are checked against their personal timeline
instead (`worldlines.absent_participant`).

Some checks are **hard rules** and always refuse the save: a date outside the dimension, an end
before its start, a date the calendar no longer has, a cycle of anchors.

## 8. The Consistency page

Open **Consistency** in the sidebar. An entity with open findings also has a badge in its page
header (and on sidebar rows) that opens the page filtered to it.

- **Filter** by severity (**Error**, **Warning**, **Info**), rule (**Every rule**), owner (**Every
  owner**) and timeline (**Every timeline**). **Show uncertain** adds possible findings, listed as
  **Info**. **Show suppressed** adds the ones you suppressed.
- **Explain** describes the rule, the finding's certainty, its subjects (linked) and any
  suppression note.
- **Suppress…** marks a finding as intentional, an impossible birth that's the whole point of the
  story. It asks **Why is this intentional?** and hides the finding from the default list.
  **Unsuppress** brings it back.
- **Check the whole vault** re-runs every rule, for example after changing severities.

**Configure rules** in **Settings → Consistency**. Rules are grouped by owner (core first, then
each module) with a description and their open findings. Set each to **Error (blocks saving)**,
**Warning** or **Off**; the default is marked **(default)**. Hard rules are locked.

**Save anyway.** When a save would create a finding of a rule set to error, Lore asks **Save
anyway?**, lists the findings, and asks **Why is this intentional?**. Saving records the note as a
suppression. A hard rule can't be overridden: the dialog only explains why.
