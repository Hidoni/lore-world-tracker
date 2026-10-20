# Events and recurring events

An **event** is something that happens on one timeline of a dimension: a battle, a coronation, a
comet passing. Its start and end are stored as exact moments, but you type them the way your world
does: as a date in any of the dimension's calendars, as an exact moment, or relative to another
event ("three days after the coronation ends"). This guide covers creating events, linking them
to each other and to the entities that take part, finding them on the timeline, and making them
repeat.

An event needs a dimension with at least one calendar (`docs/architecture/time-model.md` §9).

## 1. Create an event

Open the **New…** menu in the top bar and pick the event kind, or click **New event** on the event
outline, or double-click empty space on the timeline (§7). The event dialog asks for:

- **Name**, and on creation the **Dimension** and **Timeline** (the prime timeline by default; it
  can't change later).
- **Start** (required) and **End** (§2–§4).
- **Parent event**, to make it a sub-event (§5).
- **Importance** from **1 · Minor** to **5 · Major**. The timeline shows important events first
  when it has to leave some out, and draws them stronger.
- **Category**, free text such as "Battle, treaty, festival…", used by timeline filters and
  grouping.
- **Repeats**, to make it recurring (§8).

Click **Create event**. To change the dates later, use **Edit time** in the event page's **Time**
section: it opens the same dialog.

## 2. Type a date in any calendar

The start (and an end date) is a time point picker with three tabs:

- **Date:** pick the **Calendar**, an **Era** if the calendar has eras (or **None (astronomical
  years)**), and the **Precision**. Then fill in the levels from the top down: the year is typed,
  lower levels offer only what exists for the parents you chose (an odd year offers its own
  months). If a date falls in the overlap of a calendar reform, a **Calendar rules** select asks
  which rules you mean; a date a reform skipped is refused.
- **Relative:** anchor to another record (§3).
- **Absolute:** an exact count of base units since the dimension's inception.

Below the tabs, a preview shows the date in the display calendar and the moment it resolves to.
Lore keeps what you typed: if a later calendar edit would move it, the edit's impact preview lets
you keep the typed date or the moment, per date.

The event page's **Time** section shows the start and end in the display calendar, how each was
given ("Typed in …", a fixed moment, or "3 days after the end of …"), the duration, how long ago
it started, and a table **In every calendar** of the dimension.

### Precision and circa

**Precision** says how well you know the date. "1023" at year precision means *some moment in
1023*: the event sorts at the start of the year, displays as "1023", and the timeline fades its
edge over the whole year. Choose the coarsest level you actually know rather than inventing a day.

**Circa (approximate)** marks a date as uncertain without widening it: it displays with a "c."
prefix, the timeline softens the edge, and consistency rules report problems involving it as only
*possible* (see `temporal-state.md` §7).

### Between two dates

When all you know is a range ("founded between 1020 and 1025"), tick **Between two dates
(uncertain)** under the picker. Pick the **Earliest** and the **Latest** date, each one a date, a
fixed moment or relative to another event, at its own precision. The event sorts at the earliest
date unless you tick **A best estimate other than the earliest date** and pick one inside the
range. It displays as "between AD 1020 and 1025" (or "AD 1022 (between AD 1020 and 1025)" with an
estimate), the timeline fades its edge over the whole range, and as with precision, the moments
inside it only *possibly* hold the event (`temporal-state.md` §6). A latest date before the
earliest, or an estimate outside the range, is refused. The same option is offered for event
ends and for the bounds of facts, links and map pins. The wording ("between", "and") is part of
the calendar's **Display** options.

## 3. Anchor a date to another event

On the **Relative** tab:

1. **Find the target** by name: events (and timelines, through their branch point) of the
   dimension.
2. Pick the **Edge**: **Start** or **End** of the target. For a recurring event you can also give
   an **Occurrence key** to anchor to one occurrence; leave it empty for the series itself.
3. Set the **Offset**: a sign, then base units or amounts of a calendar's units ("3 months, 2
   days"). Zero means "at the same moment".
4. Leave **Precision** at **Default (from the target)**, or pick one.

The anchor is live. When the target moves, everything anchored to it moves in the same save, and
the changes show up together in history (one undo reverts them all). If a move would break a
dependent, for example push its end before its start or out of the dimension, the save is refused
with the reason.

**Cycles are refused.** A date can't depend on itself, directly or through a chain: if A starts
after B ends and you try to anchor B to A, the dialog says "This would make a cycle: …" with the
path. Remove one of the anchors, or make one of them a date.

If the target goes to the trash, dependents keep their moment and a warning finding says what is
anchored to a trashed record. If the target is deleted permanently, each dependent is frozen to
the moment it had, so nothing silently shifts.

On the timeline, an event with a relative start shows a lock: it can't be dragged, and its preview
offers **Edit offset** instead.

## 4. Choose how it ends

The **End** offers:

| Option | Meaning |
|--------|---------|
| **An end date** | a time point, typed like the start (dates, relative anchors, exact moments) |
| **A duration** | a length after the start, in base units or calendar units ("Lasts 2 months.") |
| **Instant (no duration)** | ends when it starts; the default; drawn as a diamond |
| **Until the end of time** | lasts until the dimension ends, and follows it if the dimension's duration changes |
| **Unknown** | the end isn't known: shown open ("1023 – ?") and faded out on the timeline |

An end before the start is refused. A calendar duration is applied with the calendar's rules (one
month after 31 January is the last day of February).

## 5. Sub-events

A sub-event belongs to a larger event: battles in a war, days of a festival. Set **Parent event**
in the dialog, or use **Create sub-event** in the parent page's **Sub-events** section (or **New
sub-event…** on the timeline). The parent must be visible from the sub-event's timeline.

A sub-event may start before or end after its parent; Lore warns about it
(`core.event.subevent_outside_parent`) without blocking you. The left sidebar's events section
lists top-level events by start and expands into their sub-events.

## 6. Causes, effects and participants

**Causes and effects.** In the event page's **Causes and effects** section, use **Add a cause** or
**Add an effect**: search for an event, optionally say how ("Description"), or choose **Create
“…”** to make the other event on the spot. Causes can sit in other timelines or dimensions. If an
effect starts before its cause, the pair gets an **Effect before cause** badge (a warning you can
suppress when it's intentional, such as time travel).

The section also shows a compact causality graph. **Full view** opens the causality page: the
chain around the event laid out left to right in time, with a **Depth** of 1 to 6 links, link
descriptions on the arrows, and **As a list** for keyboard and screen-reader use. Click a node to
open that event.

**Participants.** In **Participants**, use **Add a participant** to link any entity (characters,
groups, locations, …) with an optional **Role**: suggestions include attacker, defender, victim,
witness and leader, but any text works. On the timeline you can also drag an entity from the
sidebar, search or Recent onto an event to add it as a participant.

## 7. The timeline view

Open it with **Open the timeline** on the dimension's page, or "Open the timeline of …" in the
command palette (`Ctrl/Cmd+K`).

- **Zoom and pan:** the wheel zooms at the pointer and dragging pans (switch **Wheel** to **pans
  (Ctrl zooms)** if you prefer). The toolbar's zoom buttons, **Fit the dimension** and **Go to…**
  (a date in any calendar) do the same from buttons; on the focused timeline `+`/`−`, `Home`,
  `←`/`→` and `G` work too. The minimap shows the whole dimension: click or drag it to move there.
- **Log scale:** the toolbar's **Log scale** turns the axis logarithmic. Every power of ten of time
  since the dimension's inception takes the same width ("1 second", "10^9 years", …), so the first
  second, the age of stars and the heat death fit in one view. Zooming and panning move through
  decades; the button turns it back to a linear axis over the same range. The URL keeps it
  (`scale=log`).
- **What you see:** spans are bars whose edges fade over their uncertainty, instants are diamonds,
  eras and overlays (moon phases) appear along the axis. Where too many events crowd together, the
  less important ones become a density strip with "+N" counts; zoom in to see them.
- **Select and open:** click an event for a preview (dates, importance, participants, **Open**,
  **Edit time**); double-click or press Enter to open its page. `↑`/`↓` step through events.
- **Edit:** double-click empty space, or right-click it and choose **New event here…**, to create
  an event there. Drag an event to move it, or its edge to change the start or end; the new date is
  typed in the anchor's own calendar and precision. Right-click an event for **Edit time…**, **New
  sub-event…**, **Add a participant…** and **Link a cause or effect…**.
- **Sub-events:** right-click an event and choose **Expand its sub-events** (or press `E`) to show
  them in their own group below, or **Drill in** to show only its descendants, fitted to its span.
  The breadcrumb (**All events** › …) backs out.
- **Lanes and filters:** **Group lanes** offers **No grouping**, **By category**, **By importance**
  and **By participant** (a swimlane per participant chosen in the filters). **Filters** narrows by
  **Importance at least**, **Categories**, **Tags (all of them)**, **Participants (any of them)**
  and **With a participant who is** (a kind). **Clear the filters** resets them.
- **List view** opens the event outline: a tree table of events by start, with end, duration,
  importance and participant count. Expand rows with `→`, open with Enter, and create with **New
  event**. It is also linked as **Event outline** from the dimension's page and the sidebar.

## 8. Recurring events

Tick **Repeats** in the event dialog. The event becomes a **series**: its start is when the series
begins, and its end gives each occurrence's length (a duration, an instant or unknown; an end date
is turned into a duration from the start). Occurrences are computed when needed and never stored
in bulk, so a festival can repeat every year until the end of a dimension billions of years long.

**Pattern** offers presets built from the start date:

- **Every year on this date**, **Every month on this day**, **Every month on this weekday (e.g.
  the second Tuesday)**, **Every week on these days** (pick the **Days**), each with an **Every N**
  step;
- **Every N base units**, independent of any calendar (a comet every 75.3 years, exactly).

When the dimension has several calendars, choose which one the rule follows. Pick **Advanced** for
anything else: the **Period** (a calendar level or a continuous cycle such as the week) and
**Interval**; filters that keep only some periods (**Only periods that…**, e.g. odd years only),
positions inside each period (**At these positions in each period**, e.g. the last day of June),
**Time of day**, and what to do **When the position doesn't exist** (skip that period, or use the
nearest valid position). **Rule JSON** edits the rule directly.

The editor always shows a summary in words ("Every year on the last day of June, odd years only,
until …"), the **Next occurrences**, and any **Rule problems**. If the start doesn't match the
rule, it warns that the first occurrence comes later.

### Limits and exceptions

- **Ends:** **Never**, **After a number of occurrences**, or **At a time point (inclusive)**: an
  occurrence starting exactly then still happens. No occurrence starts after the dimension ends.
- **Exceptions:** under **Skip occurrences starting in…**, add ranges (with **Why (optional)**)
  in which nothing happens: the years of the plague, a war. Skipped occurrences still count
  toward **After a number of occurrences**, so an exception never adds one at the end.

## 9. Occurrences

A series' page has an **Occurrences** section: 20 at a time, with **Earlier**, **Later**, **From
the present** and **Show cancelled**. Each occurrence shows its number ("58th") and, if you
changed it, its state (**Customized**, **Moved** or **Cancelled**). On the timeline, a series with
too many occurrences to draw is a hatched band with its estimated count; zoom in to see them one
by one.

To work with one occurrence:

- **Open** it. This **materializes** it: Lore stores that one occurrence as its own event, linked
  to the series. Its page says "Occurrence #58 of …", and fields and participants it doesn't set
  come **From the series**. You can also materialize from the timeline's context menu
  (**Materialize this occurrence**), and double-clicking a computed occurrence does it too.
- **Modify time** gives it its own dates (the festival was held late that year).
- **Add sub-event** or **Add note** materializes it and lets you attach details to that occurrence
  only. A materialized occurrence with sub-events gets a dot on the timeline.
- **Cancel** marks that it didn't happen: it disappears from the timeline, and the list shows it
  only with **Show cancelled**. **Restore** takes it back.
- **Revert** turns a customized occurrence back into the computed one. If it has sub-events, Lore
  asks before moving them to the trash.

Other dates can anchor to one occurrence (the **Occurrence key** in §3); they read like "When the
3rd occurrence of … starts".

## 10. When the rule changes

Saving a changed rule, series start or duration keeps your materialized occurrences with their
numbers: they move with the rule. If the change would make some of them stop being occurrences
at all, Lore opens **Review the occurrences** instead. Each customized occurrence shows its
status (**Unchanged**, **Moves** or **No longer an occurrence**), its date before and after, and a
choice:

| Choice | Effect |
|--------|--------|
| **Move with the rule** | it keeps its number and moves to that occurrence's new date |
| **Stay at its date (re-key)** | it stays where it was and becomes whichever occurrence now falls there |
| **Detach (a standalone event)** | it becomes an ordinary event at its current date, with its sub-events |
| **Move to the trash** | it is removed (not offered for one with sub-events: detach it) |

Two occurrences can't be re-keyed onto the same one; pick another choice for one of them. Click
**Apply the change**. The rule change and every choice are one change, which the toast's **Undo**
reverts. If the series changed meanwhile, **Preview again**.

Editing the calendar a series follows moves its occurrences the same way; the calendar's impact
preview lists the series whose dates move.
