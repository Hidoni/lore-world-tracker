# Calendars

In Lore, time itself is a single number: every moment is a count of **base units** since the
dimension's inception. A **calendar** is a lens over that number. It turns a moment into a date
people can read ("3 Frostfall 1023 AF") and a typed date back into a moment. A dimension can have
any number of calendars, and every date can be shown in any of them, so the elves' reckoning and
the empire's can sit side by side over the same history.

This guide covers presets, the calendar editor, the display calendar, and how to change a
calendar without breaking the dates you have already entered.

## How dates are stored

Two product decisions shape how calendars behave (`docs/plan/planning-log.md`):

- **Your typed dates are kept (D1).** When you enter "3 Frostfall 1023", Lore remembers the date
  as you typed it, in that calendar, and works out the moment from it. If you later change the
  calendar (make Frostfall a day longer, say), the date stays "3 Frostfall 1023" and its moment
  moves, unless you choose to pin it (§6).
- **Dates have a precision (D2).** "1023" is a date known to the year, "Frostfall 1023" to the
  month. Lore stores the start of that unit and shows the date at its precision. Tick **Circa
  (approximate)** in a date picker to mark it uncertain ("c. 1023").

Dates can also be **relative** ("three days after the coronation starts") or **absolute** (a
raw number of base units). The date picker's **Date**, **Relative** and **Absolute** tabs choose
between them.

On the **Date** tab you can also **type a date** the way the calendar writes it: "12 Frostfall
1023 AF", "15 mar 2024, 14:30", "c. 44 BC". Lore reads it with the calendar's own formats
(**Formats** in §3), fills in the era, precision and fields, and ticks **Circa** for the circa
prefix. Case and extra spaces don't matter, and month or day names, abbreviations and numbers all
work. A text that names no date of the calendar is flagged and leaves the fields as they were.

## 1. Start from a preset

A dimension's first calendar comes from the dimension wizard (`getting-started.md` §3), from a
preset or designed in the calendar editor right there. To add
another, open the dimension's page (from the vault home or the dimension switcher) and click
**New calendar** under its calendars. **Start from** a preset or **Blank** (a 360-day year).

| Preset | What it is |
|--------|------------|
| Gregorian | The proleptic Gregorian calendar, BC/AD, a seven-day week |
| Julian | The proleptic Julian calendar |
| Julian → Gregorian | Julian until 4 October 1582, Gregorian from 15 October 1582 (a reform) |
| 360-day | Twelve 30-day months, no leap years, no eras |
| Alternating years | Odd and even years with different months |
| Lunisolar (Metonic) | Lunar months with leap months on a 19-year cycle |
| Shire Reckoning | Twelve 30-day months plus Yule and Lithe days outside the months |
| Maya Long Count | kʼin, winal, tun, kʼatun and bakʼtun |

A preset is a starting point: once created, the calendar is yours to edit.

The first calendar of a dimension is its **default**: the one dates are typed in unless you pick
another, and the one used in places that show a single calendar. **Make default** on the
dimension's page switches it.

## 2. Pick the display calendar

The calendar selector in the top bar sets the **display calendar**: every date on screen,
including dates written inside text, is shown in it. It lists the dimension's calendars (the
default first) and **Absolute**, which shows raw base units. The choice is kept in your browser
for each vault and dimension, and is part of the page's address, so a link you copy opens in the
same calendar. Hover over a date to see it in every calendar at once.

Readers of a shared vault pick their own display calendar.

## 3. The calendar editor

Click **Edit** next to a calendar on the dimension's page. The editor has a **Structure** tab, a
**JSON** tab with the whole definition as text (for power users), and a **Preview** that checks
every change as you make it: problems are listed in words (click one to jump to its field), the
year grid shows any year's units and their lengths, and the converter turns a date into a moment
and back.

The **Structure** tab has these sections:

- **Levels**: the units of the calendar, coarsest first (year, month, day, hour, …), with their
  names and abbreviations and the number the first one gets (days start at 1, hours at 0). The
  finest level is made of base units. The coarsest one doesn't have to be a year.
- **Templates**: the layout of one unit, as the units inside it. A template is either
  **Uniform** (n equal units: a day of 24 hours) or a **Sequence** of listed units (a year of
  named months of different lengths). Each named unit has a slot id; reusing a slot id across
  templates (the same "Frostfall" in common and leap years) keeps typed dates attached to it.
- **Years**: which template each year uses. **Every year alike**, **A cycle of templates** (odd
  and even years), or **Rules** for leap years: combine **Year divisible…** with **All of**, **Any
  of** and **Not** (Gregorian: divisible by 4, not by 100, unless by 400). Under **Exceptions**,
  give single years a template of their own, for a one-off reform year or a year the gods
  lengthened.
- **Alignment**: which moment a given date begins at, which places the calendar on the time
  axis. It can be a moment or another time point, such as the start of an event ("year 1 begins
  at the Founding").
- **Rules and reforms**: see §4.
- **Cycles**: repeating sequences that run alongside the dates, such as a seven-day week, a
  market cycle or a 60-year cycle. Set the level, length, names, and whether it **Counts on
  forever** or **Restarts every…** coarser unit.
- **Eras**: year numbering such as BC/AD or "Third Age". Each era after the first **Begins at** a
  time point (which may be an event), and its years count up from or down to a number, with the
  abbreviation before or after the year.
- **Overlays**: astronomical cycles shown next to dates without changing them, such as moons or
  seasons. Give the period in base units (or use the helper in days), when **Phase 0 begins at**,
  and the phases. Recurring events can follow them ("every full moon").
- **Markers**: named parts of every year, such as seasons or festival weeks, from a date to
  another (the end is not included; an end before the start runs into the next year, like a winter
  from 21 December to 20 March). Choose the precision (month or day), then the dates without the
  year. Recurring events can fall on a marker's first or last day, or on every day in it.
- **Formats** and **Display**: how dates are written at each level, the circa prefix, digit
  grouping and how huge numbers are shortened.

### Intercalary days

Some calendars have days outside the months, such as Midyear's Day or the Egyptian epagomenal
days. In a sequence template, tick **Intercalary** on such a unit: it exists in the year but
isn't numbered like the others. To keep it out of the week as well, tick **Skips** for that
cycle on the unit.

## 4. Calendar reforms

A real-world calendar can change its rules at some point, as the Julian calendar did in 1582. In
**Rules and reforms**, click **Reform**: it copies the selected rules into a new set that **Takes
effect at** a date you choose. Edit the templates, years, alignment and cycles of the new set;
the old rules still apply before that date. A week cycle can continue from the previous rules so
weekdays run on across the reform.

Dates that fall in the gap of a reform (10 October 1582 in the Julian → Gregorian preset) don't
exist. Where a date is ambiguous across a reform, the date picker asks which **Calendar rules**
you mean.

## 5. Save a new calendar

For a new calendar, give it a name and click **Create calendar**. Nothing depends on it yet, so
it is saved directly.

## 6. Edit a calendar safely

Changing a calendar that dates already use can move them. Lore never does that silently: when
you click **Save**, it previews the change first. If nothing is affected, the change is applied
at once. Otherwise **Review the calendar change** opens with:

- how many time points change, how many of them are broken, and which recurring series move;
- a row per affected record: its date **Now**, its date **After** the change, and your
  **Choice** for it.

The choices are:

- **Keep the date** (the default): the record keeps the date you typed, and its moment moves to
  wherever that date now falls.
- **Keep the moment**: the record stays at the same moment. Its date is rewritten as an absolute
  moment, so it won't follow later calendar edits either.
- **Nearest valid date**: only for dates that no longer exist (day 31 of a month cut to 30). The
  record moves to the nearest date that does.

**Keep all dates** and **Keep all moments** set every row at once. A broken date (one that no
longer exists, or now falls outside the dimension) must get a choice before you can **Apply the
change**; choosing **Keep the date (accept the problem)** keeps it and lists it among the
vault's consistency findings.

Applying is one change: the toast's **Undo** reverts the calendar and every date with it. Before
a change that affects more than 100 records, Lore also writes a backup of the vault
(`backups.md`).

If something else changed the calendar or its dates while the preview was open, or the preview
is more than an hour old, you get **Preview again** instead.

### Which choice to make

- Your dates were typed in this calendar and you are fixing the calendar's rules: **Keep the
  date**. "The battle was on 3 Frostfall" stays true.
- Your events are fixed in time and the calendar is only how one culture labels it (for example
  you are moving its year 1): **Keep the moment** for the records whose position matters more
  than their label.
