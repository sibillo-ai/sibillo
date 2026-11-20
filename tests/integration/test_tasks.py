"""Tasks: conversations that start on a schedule, each firing a new one (TSK-001 to TSK-003, TSK-009, TSK-010).

ADR-0106. Tests move a schedule's next firing into the past instead of
waiting for it (tests/support/tasks.py); the worker sweeps every second. The
model the tests serve answers a task's instructions as it answers any user
message (tests/support/model.py).
"""

from __future__ import annotations

import datetime
import time
import uuid
import zoneinfo

import pytest

from tests.support.accounts import assert_problem, body, create_account, disable_account, login
from tests.support.database import Database
from tests.support.fixtures import HarnessModel
from tests.support.households import Member, new_member
from tests.support.runs import start_run, wait_for_run
from tests.support.server import Server
from tests.support.tasks import (
    DAILY,
    arrange_done_firings,
    conversations_of,
    create_task,
    fire_schedule,
    firings,
    get_task,
    hook,
    schedule,
    stays_quiet,
    task_request,
    trigger_of,
    try_create,
    update_task,
    wait_for_conversations,
    webhook,
)


@pytest.fixture
def member(database: Database, server: Server, default_model: HarnessModel) -> Member:
    return new_member(database, server, default_model)


def _conversation(server: Server, token: str, conversation_id: str) -> dict[str, object]:
    with server.client(token) as client:
        response = client.get(f"/conversations/{conversation_id}")
    assert response.status_code == 200, response.text
    return body(response)


# --- TSK-001: tasks ---


@pytest.mark.spec("TSK-001")
def test_a_user_creates_lists_changes_and_deletes_their_task(server: Server, member: Member) -> None:
    task = create_task(server, member.token, "Summarize the news.", name="Morning review")
    assert task["name"] == "Morning review"
    assert task["instructions"] == "Summarize the news."
    assert task["time_zone"] == "Europe/Rome"
    assert task["paused"] is False
    assert task["uses_memory"] is False
    assert task["grants"] == []
    assert task["grant_check"]["passes"] is True
    assert task["skipped"] == {"count": 0, "last_at": None}
    assert task["last_fired_at"] is None
    # Settings left out come from the user's defaults: the household's default model.
    assert task["model"] == {"connection_id": member.model.connection_id, "model": "test-model"}
    (trigger,) = task["triggers"]
    assert trigger["kind"] == "schedule"
    assert trigger["schedule"] == DAILY
    assert trigger["next_fire_at"] is not None

    with server.client(member.token) as client:
        listed = body(client.get("/tasks"))["items"]
    assert [item["id"] for item in listed] == [task["id"]]

    changed = update_task(server, member.token, task["id"], name="Evening review", instructions="Summarize the day.")
    assert (changed["name"], changed["instructions"]) == ("Evening review", "Summarize the day.")
    assert get_task(server, member.token, task["id"])["name"] == "Evening review"

    with server.client(member.token) as client:
        assert client.delete(f"/tasks/{task['id']}").status_code == 204
        assert_problem(client.get(f"/tasks/{task['id']}"), 404, "resource.not_found")
        assert body(client.get("/tasks"))["items"] == []


@pytest.mark.spec("TSK-001")
def test_task_names_are_unique_for_their_user(server: Server, member: Member) -> None:
    create_task(server, member.token, name="Weekly report")
    assert_problem(try_create(server, member.token, task_request(name="Weekly report")), 409, "resource.conflict")


@pytest.mark.spec("TSK-001")
def test_a_task_keeps_at_least_one_trigger(server: Server, member: Member) -> None:
    assert_problem(try_create(server, member.token, task_request(triggers=[])), 422, "request.validation_failed")
    task = create_task(server, member.token)
    (only,) = task["triggers"]
    with server.client(member.token) as client:
        assert_problem(client.delete(f"/tasks/{task['id']}/triggers/{only['id']}"), 409, "resource.conflict")
        added = client.post(f"/tasks/{task['id']}/triggers", json=schedule("30 18 * * 5"))
        assert added.status_code == 201, added.text
        assert client.delete(f"/tasks/{task['id']}/triggers/{only['id']}").status_code == 204
    assert [trigger["schedule"] for trigger in get_task(server, member.token, task["id"])["triggers"]] == [
        "30 18 * * 5"
    ]


@pytest.mark.spec("TSK-001", "TEN-007")
def test_a_task_belongs_to_its_user_alone(database: Database, server: Server, member: Member) -> None:
    task = create_task(server, member.token)
    # The household's tenant admin, also the instance admin, and another member of it.
    others = [member.model.admin_token, login(server, create_account(database, member.account.tenant_id))]
    for token in others:
        with server.client(token) as client:
            assert_problem(client.get(f"/tasks/{task['id']}"), 404, "resource.not_found")
            assert_problem(client.patch(f"/tasks/{task['id']}", json={"paused": True}), 404, "resource.not_found")
            assert_problem(client.delete(f"/tasks/{task['id']}"), 404, "resource.not_found")
            assert_problem(client.get(f"/tasks/{task['id']}/conversations"), 404, "resource.not_found")
            assert task["id"] not in [item["id"] for item in body(client.get("/tasks"))["items"]]
    assert get_task(server, member.token, task["id"])["paused"] is False


@pytest.mark.spec("TSK-001", "TSK-003")
def test_a_paused_task_does_not_fire(database: Database, server: Server, member: Member) -> None:
    task = create_task(server, member.token)
    assert update_task(server, member.token, task["id"], paused=True)["paused"] is True
    fire_schedule(database, trigger_of(task, "schedule")["id"])
    stays_quiet(server, member.token, task["id"])

    resumed = update_task(server, member.token, task["id"], paused=False)
    assert resumed["paused"] is False
    # Resuming does not fire it for the time that passed while it was paused.
    next_fire_at = datetime.datetime.fromisoformat(trigger_of(resumed, "schedule")["next_fire_at"])
    assert next_fire_at > datetime.datetime.now(datetime.UTC)
    stays_quiet(server, member.token, task["id"])


# --- TSK-002: every firing is a new conversation ---


@pytest.mark.spec("TSK-002", "TSK-003")
def test_every_firing_starts_a_new_conversation_listed_under_its_task(
    database: Database, server: Server, member: Member, default_model: HarnessModel
) -> None:
    instructions = f"Morning review {uuid.uuid4().hex[:8]}"
    task = create_task(server, member.token, instructions, name="Morning review")
    trigger_id = trigger_of(task, "schedule")["id"]

    fire_schedule(database, trigger_id)
    (first,) = wait_for_conversations(server, member.token, task["id"], 1)
    fire_schedule(database, trigger_id)
    second, again = wait_for_conversations(server, member.token, task["id"], 2)

    # Newest first, each its own conversation, each run to its end.
    assert again["conversation_id"] == first["conversation_id"]
    assert second["conversation_id"] != first["conversation_id"]
    assert second["started_at"] >= first["started_at"]
    for item in (first, second):
        assert item["outcome"] == "completed"
        assert item["trigger_kind"] == "schedule"
        assert item["without_grants"] is False
        conversation = _conversation(server, member.token, item["conversation_id"])
        assert conversation["task"] == {"id": task["id"], "name": "Morning review"}
        assert conversation["temporary"] is False
    # The instructions reached the model as the first message, once per firing.
    assert len(default_model.endpoint.requests_with(instructions)) >= 2
    assert get_task(server, member.token, task["id"])["last_fired_at"] is not None

    # The conversations are listed with the user's others.
    with server.client(member.token) as client:
        listed = body(client.get("/conversations", params={"limit": 100}))["items"]
    assert {first["conversation_id"], second["conversation_id"]} <= {item["id"] for item in listed}


@pytest.mark.spec("TSK-002")
def test_a_conversation_a_task_started_continues_like_any_other(
    database: Database, server: Server, member: Member
) -> None:
    task = create_task(server, member.token, name="Weekly report")
    fire_schedule(database, trigger_of(task, "schedule")["id"])
    (started,) = wait_for_conversations(server, member.token, task["id"])
    conversation_id = started["conversation_id"]

    run_id, _ = start_run(server, member.token, conversation_id, "And what about tomorrow?")
    assert wait_for_run(server, member.token, run_id)["status"] == "completed"

    # A fork is not the task's.
    with server.client(member.token) as client:
        fork = client.post(f"/conversations/{conversation_id}/fork", json={"run_id": run_id})
    assert fork.status_code == 201, fork.text
    assert body(fork)["task"] is None

    # Deleting the task leaves its conversations, with its name.
    with server.client(member.token) as client:
        assert client.delete(f"/tasks/{task['id']}").status_code == 204
    assert _conversation(server, member.token, conversation_id)["task"] == {"id": None, "name": "Weekly report"}

    # Deleting a conversation takes it out of its task's list.
    other = create_task(server, member.token)
    fire_schedule(database, trigger_of(other, "schedule")["id"])
    (item,) = wait_for_conversations(server, member.token, other["id"])
    with server.client(member.token) as client:
        assert client.delete(f"/conversations/{item['conversation_id']}").status_code == 204
    assert conversations_of(server, member.token, other["id"]) == []


# --- TSK-003: schedules ---


@pytest.mark.spec("TSK-003")
@pytest.mark.parametrize("expression", ["*/5 * * * *", "* * * * *", "0,10 * * * *", "not a schedule", "0 7 * *"])
def test_schedules_that_fire_too_often_or_do_not_parse_are_refused(
    server: Server, member: Member, expression: str
) -> None:
    response = try_create(server, member.token, task_request(triggers=[schedule(expression)]))
    assert_problem(response, 422, "request.validation_failed")


@pytest.mark.spec("TSK-003")
@pytest.mark.parametrize("expression", ["*/15 * * * *", "0 7 * * 1-5", "30 6 1 * *"])
def test_schedules_that_fire_at_most_every_15_minutes_are_accepted(
    server: Server, member: Member, expression: str
) -> None:
    response = try_create(server, member.token, task_request(triggers=[schedule(expression)]))
    assert response.status_code == 201, response.text


@pytest.mark.spec("TSK-003")
def test_unknown_time_zones_are_refused(server: Server, member: Member) -> None:
    response = try_create(server, member.token, task_request(time_zone="Europe/Atlantis"))
    assert_problem(response, 422, "request.validation_failed")


@pytest.mark.spec("TSK-003")
@pytest.mark.parametrize("time_zone", ["Europe/Rome", "America/New_York", "Asia/Tokyo"])
def test_a_schedule_fires_at_its_time_in_the_tasks_time_zone(server: Server, member: Member, time_zone: str) -> None:
    task = create_task(server, member.token, time_zone=time_zone, triggers=[schedule("0 7 * * *")])
    next_fire_at = datetime.datetime.fromisoformat(trigger_of(task, "schedule")["next_fire_at"])
    local = next_fire_at.astimezone(zoneinfo.ZoneInfo(time_zone))
    assert (local.hour, local.minute) == (7, 0)
    now = datetime.datetime.now(datetime.UTC)
    assert now < next_fire_at <= now + datetime.timedelta(days=1, hours=1)


@pytest.mark.spec("TSK-003")
def test_firings_missed_while_down_fire_once(database: Database, server: Server, member: Member) -> None:
    task = create_task(server, member.token, triggers=[schedule("0 * * * *")])
    trigger_id = trigger_of(task, "schedule")["id"]
    # Five hourly firings were missed.
    fire_schedule(database, trigger_id, datetime.timedelta(hours=5, minutes=1))
    wait_for_conversations(server, member.token, task["id"], 1)
    stays_quiet(server, member.token, task["id"], 1)
    (firing,) = firings(database, task["id"])
    assert firing["status"] == "done"
    next_fire_at = datetime.datetime.fromisoformat(
        trigger_of(get_task(server, member.token, task["id"]), "schedule")["next_fire_at"]
    )
    assert next_fire_at > datetime.datetime.now(datetime.UTC)


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


# --- TSK-009: limits on firing ---


@pytest.mark.spec("TSK-009")
def test_a_task_starts_at_most_10_conversations_an_hour(database: Database, server: Server, member: Member) -> None:
    task = create_task(server, member.token)
    arrange_done_firings(database, task["id"], 10)
    before = datetime.datetime.now(datetime.UTC)
    fire_schedule(database, trigger_of(task, "schedule")["id"])
    deadline = time.monotonic() + 10
    while get_task(server, member.token, task["id"])["skipped"]["count"] == 0:
        assert time.monotonic() < deadline, "the firing over the limit was not counted"
        time.sleep(0.2)
    skipped = get_task(server, member.token, task["id"])["skipped"]
    assert skipped["count"] == 1
    assert datetime.datetime.fromisoformat(skipped["last_at"]) >= before - datetime.timedelta(seconds=1)
    stays_quiet(server, member.token, task["id"])
    assert len(firings(database, task["id"])) == 10


@pytest.mark.spec("TSK-009")
def test_one_firing_of_a_task_runs_at_a_time(database: Database, server: Server, member: Member) -> None:
    # Two schedules of the task come due together; its runs take a few seconds.
    task = create_task(server, member.token, "slow:6", triggers=[schedule("0 7 * * *"), schedule("0 8 * * *")])
    for trigger in task["triggers"]:
        fire_schedule(database, trigger["id"])
    deadline = time.monotonic() + 10
    while len(firings(database, task["id"])) < 2:
        assert time.monotonic() < deadline, "the task did not fire twice"
        time.sleep(0.1)
    statuses = sorted(firing["status"] for firing in firings(database, task["id"]))
    # Never two at once: both may still wait, one runs while the other waits, or the first is done.
    assert statuses in (["waiting", "waiting"], ["running", "waiting"], ["done", "running"], ["done", "waiting"])
    first, second = wait_for_conversations(server, member.token, task["id"], 2, timeout=40)[::-1]
    done = firings(database, task["id"])
    assert [firing["status"] for firing in done] == ["done", "done"]
    # The second started only once the first had ended.
    assert done[1]["started_at"] >= done[0]["finished_at"]
    assert first["conversation_id"] != second["conversation_id"]


@pytest.mark.spec("TSK-009")
def test_events_of_a_paused_task_are_counted_and_not_run(server: Server, member: Member) -> None:
    task = create_task(server, member.token, triggers=[webhook()])
    path = trigger_of(task, "webhook")["webhook_path"]
    update_task(server, member.token, task["id"], paused=True)
    assert hook(server, path, "The door opened.").status_code == 202
    assert hook(server, path, "The door closed.").status_code == 202
    skipped = get_task(server, member.token, task["id"])["skipped"]
    assert skipped["count"] == 2
    assert skipped["last_at"] is not None
    stays_quiet(server, member.token, task["id"])


# --- TSK-010: tasks need no one to be signed in ---


@pytest.mark.spec("TSK-010")
def test_a_task_fires_while_its_user_is_signed_out(database: Database, server: Server, member: Member) -> None:
    task = create_task(server, member.token)
    with server.client(member.token) as client:
        assert client.post("/auth/logout").status_code == 204
    fire_schedule(database, trigger_of(task, "schedule")["id"])
    deadline = time.monotonic() + 20
    while not [firing for firing in firings(database, task["id"]) if firing["status"] == "done"]:
        assert time.monotonic() < deadline, "the task did not fire"
        time.sleep(0.2)
    token = login(server, member.account)
    (item,) = conversations_of(server, token, task["id"])
    assert item["outcome"] == "completed"


@pytest.mark.spec("TSK-010")
def test_a_disabled_account_s_tasks_stop_firing(database: Database, server: Server, member: Member) -> None:
    task = create_task(server, member.token, triggers=[schedule(), webhook()])
    disable_account(database, member.account)
    fire_schedule(database, trigger_of(task, "schedule")["id"])
    assert hook(server, trigger_of(task, "webhook")["webhook_path"], "Hello").status_code == 202
    time.sleep(3)
    assert firings(database, task["id"]) == []


@pytest.mark.spec("TSK-010")
def test_a_task_s_runs_are_in_the_cost_ledger_and_the_activity(
    database: Database, server: Server, member: Member
) -> None:
    task = create_task(server, member.token, 'tool:web_search {"query": "weather"}')
    fire_schedule(database, trigger_of(task, "schedule")["id"])
    (item,) = wait_for_conversations(server, member.token, task["id"])
    with database.superuser() as conn:
        spent = conn.execute(
            "SELECT count(*) FROM usage_ledger WHERE conversation_id = %s AND owner_id = %s",
            (uuid.UUID(item["conversation_id"]), member.account.id),
        ).fetchone()
    assert spent is not None
    assert spent[0] >= 1
    with server.client(member.token) as client:
        events = body(client.get("/me/activity", params={"conversation_id": item["conversation_id"]}))["items"]
    assert [event["tool"] for event in events] == ["web_search"]
