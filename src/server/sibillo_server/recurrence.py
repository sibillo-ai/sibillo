"""Schedules as iCalendar recurrences (TSK-003, ADR-0109).

A schedule is a start, a date and time in the task's time zone, and lines of
RFC 5545 recurrence, as an event of Google Calendar's API holds them:
`RRULE` lines, computed by `python-dateutil`, and `RDATE` and `EXDATE`
lines, read here, since `python-dateutil` does not take their time zones.
A date without `Z` is in the task's time zone, or in the one its `TZID`
names. Without lines, a schedule fires once, at its start.
"""

from __future__ import annotations

import datetime
import itertools
import re
import zoneinfo
from collections.abc import Sequence
from dataclasses import dataclass

from dateutil.rrule import rrule, rruleset, rrulestr

MAX_LINES = 5
# A schedule fires at most once every 15 minutes (TSK-003): checked over its first occurrences.
MIN_GAP = datetime.timedelta(minutes=15)
CHECKED_OCCURRENCES = 1000
_DATE_TIME = re.compile(r"^(\d{8})(T(\d{6})(Z?))?$")


@dataclass(frozen=True)
class RecurrenceError(Exception):
    """Why a schedule is refused: `invalid`, `too_often` or `never_fires`."""

    reason: str


def parse_start(value: str) -> datetime.datetime:
    """A schedule's start: a date and time without offset."""
    try:
        start = datetime.datetime.fromisoformat(value)
    except ValueError:
        raise RecurrenceError("invalid") from None
    if start.tzinfo is not None:
        raise RecurrenceError("invalid")
    return start


def _zone(name: str) -> zoneinfo.ZoneInfo:
    try:
        return zoneinfo.ZoneInfo(name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        raise RecurrenceError("invalid") from None


def _dates(value: str, zone: zoneinfo.ZoneInfo, start: datetime.datetime) -> list[datetime.datetime]:
    found: list[datetime.datetime] = []
    for item in value.split(","):
        match = _DATE_TIME.match(item.strip())
        if match is None:
            raise RecurrenceError("invalid")
        day, _, clock, utc = match.groups()
        try:
            when = datetime.datetime.strptime(day + (clock or start.strftime("%H%M%S")), "%Y%m%d%H%M%S")
        except ValueError:
            raise RecurrenceError("invalid") from None
        found.append(when.replace(tzinfo=datetime.UTC if utc else zone))
    return found


def occurrences(start: datetime.datetime, recurrence: Sequence[str], zone_name: str) -> rruleset:
    """The schedule's occurrences, as aware date and times."""
    if len(recurrence) > MAX_LINES:
        raise RecurrenceError("invalid")
    zone = _zone(zone_name)
    first = start.replace(tzinfo=zone)
    found = rruleset()
    if not recurrence:
        found.rdate(first)
        return found
    rules = 0
    for line in recurrence:
        name, separator, value = line.strip().partition(":")
        if not separator or not value:
            raise RecurrenceError("invalid")
        head, *parameters = name.split(";")
        head = head.upper()
        if head == "RRULE":
            if parameters:
                raise RecurrenceError("invalid")
            try:
                rule = rrulestr(f"RRULE:{value}", dtstart=first)
            except (ValueError, TypeError):
                raise RecurrenceError("invalid") from None
            if not isinstance(rule, rrule):
                raise RecurrenceError("invalid")
            found.rrule(rule)
            rules += 1
        elif head in ("RDATE", "EXDATE"):
            zone_of = zone
            for parameter in parameters:
                key, _, setting = parameter.partition("=")
                if key.upper() == "TZID":
                    zone_of = _zone(setting)
                elif key.upper() != "VALUE" or setting.upper() not in ("DATE", "DATE-TIME"):
                    raise RecurrenceError("invalid")
            for when in _dates(value, zone_of, start):
                if head == "RDATE":
                    found.rdate(when)
                else:
                    found.exdate(when)
        else:
            raise RecurrenceError("invalid")
    if rules == 0:
        # Extra dates alone fire besides the start, as an event's start is its first instance.
        found.rdate(first)
    return found


def check(start: datetime.datetime, recurrence: Sequence[str], zone_name: str, now: datetime.datetime) -> rruleset:
    """The schedule's occurrences, once checked: it parses, fires at most every 15 minutes, and fires again."""
    found = occurrences(start, recurrence, zone_name)
    try:
        previous: datetime.datetime | None = None
        for current in itertools.islice(iter(found), CHECKED_OCCURRENCES):
            if previous is not None and current - previous < MIN_GAP:
                raise RecurrenceError("too_often")
            previous = current
        upcoming = found.after(now)
    except (ValueError, TypeError, OverflowError):
        raise RecurrenceError("invalid") from None
    if upcoming is None:
        raise RecurrenceError("never_fires")
    return found


def next_occurrence(
    start: datetime.datetime, recurrence: Sequence[str], zone_name: str, after: datetime.datetime
) -> datetime.datetime | None:
    """The schedule's next firing time after `after`, as a UTC instant; `None` once it ended."""
    try:
        found = occurrences(start, recurrence, zone_name).after(after)
    except (RecurrenceError, ValueError, TypeError, OverflowError):
        return None
    return None if found is None else found.astimezone(datetime.UTC)
