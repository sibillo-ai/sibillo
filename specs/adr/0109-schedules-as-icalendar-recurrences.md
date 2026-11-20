# ADR-0109: Schedules as iCalendar recurrences

- **Status:** Proposed
- **Date:** 2026-11-20
- **Deciders:** @tapionx
- **Related:** TSK-003, TSK-006, TSK-012, UX-031, ADR-0106, ADR-0107

## Context

ADR-0106 made a schedule a cron expression. Cron repeats for ever: it cannot
say "once, next Tuesday at 9", "the first Monday of the month, for two
months" or "every weekday until March". People ask for exactly these, and
the model understands them; it needs a formal way to write them.

iCalendar (RFC 5545) is that way. Calendars, Google Calendar's API among
them, describe a repeating event as its start, in a time zone, and lines
of recurrence: `RRULE` for the rule, with `COUNT` or `UNTIL` to end it,
`RDATE` for more dates and `EXDATE` for dates left out. Models know it well,
and `python-dateutil`, already in the lock, computes it.

## Decision

1. **A schedule is a start and a recurrence, as an event of Google
   Calendar's API.** A schedule trigger is `{"kind": "schedule", "start":
   "<local date and time>", "recurrence": [<lines>]}`. `start` is a date and
   time without offset, in the task's time zone; `recurrence` holds up to 5
   lines of RFC 5545, each `RRULE:`, `RDATE` or `EXDATE`, as in that API.
   Without recurrence, the schedule fires once, at its start. Cron is no
   longer accepted: one syntax, which the model and the app both speak.
2. **The same rules as before.** A schedule fires at most once every 15
   minutes, checked over its first occurrences; firings missed while the
   instance was down fire once (TSK-003). A schedule that would never fire,
   such as a single start in the past, is refused.
3. **A schedule can end.** After its last occurrence, a trigger has no next
   firing and is shown as ended; the task keeps it, and its other triggers,
   until the user changes or deletes it. A task whose triggers all ended
   fires only when run at once (TSK-011).
4. **Said in words.** The app says a recurrence in the user's language from
   its own strings, for the forms people use: once, every day, week, month
   or year, on days of the week or of the month, the n-th weekday of a
   month, every n periods, for a number of times or until a date. Any other
   recurrence is shown as written.

## Consequences

- "Once, tomorrow at 8", "the first Monday of the month, twice" and "every
  weekday until March" are tasks.
- Existing cron schedules are not carried over: during the alpha the
  database is recreated (ADR-0071).
- The checks on a schedule iterate its occurrences: bounded to its first
  occurrences, and to occurrences within the next years, so that a rule
  with an end far away costs little.

## Alternatives considered

- **Cron, with a count and an end date of our own:** a syntax of our own
  that neither models nor calendars know, and still no "first Monday".
- **Both cron and iCalendar:** two syntaxes to check, describe and teach the
  model, for no gain the second does not give.
- **Free text interpreted by the model at each firing:** no checks
  possible, and a schedule that may change with the model.
