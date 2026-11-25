"""Tasks: conversations that start on a schedule, each firing a new one (TSK-001 to TSK-003, TSK-009, TSK-010).

ADR-0106. Tests move a schedule's next firing into the past instead of
waiting for it (tests/support/tasks.py); the worker sweeps every second. The
model the tests serve answers a task's instructions as it answers any user
message (tests/support/model.py).
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from tests.support.database import Database
from tests.support.fixtures import HarnessModel
from tests.support.households import Member, new_member
from tests.support.server import Server
from tests.support.tasks import (
    create_task,
    fire_schedule,
    firings,
    once,
    schedule,
    stays_quiet,
    trigger_of,
    wait_for_conversations,
)


@pytest.fixture
def member(database: Database, server: Server, default_model: HarnessModel) -> Member:
    return new_member(database, server, default_model)


REFUSED: dict[str, dict[str, Any]] = {
    "every five minutes": schedule("RRULE:FREQ=MINUTELY;INTERVAL=5"),
    "twice an hour, ten minutes apart": schedule("RRULE:FREQ=HOURLY;BYMINUTE=0,10"),
    "an extra date too close": schedule("RRULE:FREQ=DAILY", "RDATE:20260101T071000"),
    "not a rule": schedule("RRULE:FREQ=SOMETIMES"),
    "not a recurrence line": schedule("EVERY:DAY"),
    "once, in the past": once("2020-01-01T07:00:00"),
    "ended before now": schedule("RRULE:FREQ=DAILY;COUNT=3", start="2020-01-01T07:00:00"),
    "a start that is no date": schedule(start="2026-02-30T07:00:00"),
}


ACCEPTED: dict[str, list[str]] = {
    "every fifteen minutes": ["RRULE:FREQ=MINUTELY;INTERVAL=15"],
    "weekdays until a date": ["RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;UNTIL=20991231T235959Z"],
    "first Monday, twice": ["RRULE:FREQ=MONTHLY;BYDAY=1MO;COUNT=2"],
    "monthly with an exception": ["RRULE:FREQ=MONTHLY;BYMONTHDAY=1", "EXDATE:20270101T070000"],
}


@pytest.mark.spec("TSK-003")
def test_a_firing_starts_one_conversation_across_a_crash_of_the_worker(
    database: Database, server: Server, member: Member
) -> None:
    task = create_task(server, member.token, "slow:4")
    fire_schedule(database, trigger_of(task, "schedule")["id"])
    deadline = time.monotonic() + 10
    while not firings(database, task["id"]):
        assert time.monotonic() < deadline, "the task did not fire"
        time.sleep(0.1)
    server.crash_and_restart_worker()
    wait_for_conversations(server, member.token, task["id"], 1, timeout=60)
    stays_quiet(server, member.token, task["id"], 1)
    assert len(firings(database, task["id"])) == 1
