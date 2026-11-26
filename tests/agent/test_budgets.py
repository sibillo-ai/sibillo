"""Budgets per user, checked before each model request, and usage over time (MOD-004, MOD-021, ADR-0145).

Each household reaches the model the tests serve through two connections: a
server whose inference runs locally, and OpenRouter, which runs remotely
(tests/support/model.py). Earlier usage is arranged in the cost ledger.
"""

from __future__ import annotations

import datetime
import json
import secrets
import uuid
import zoneinfo
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest

from tests.support.accounts import Account, assert_problem, body, create_account, create_tenant, login
from tests.support.database import Database, uuid7
from tests.support.fixtures import HarnessModel, HouseholdModel
from tests.support.model import OPENROUTER_COST
from tests.support.runs import create_conversation, messages, run_input, start_run, text_of, wait_for_run
from tests.support.server import Server
from tests.support.tasks import create_task, path_runs, wait_for_conversations

NO_BUDGET = {"cost": None, "tokens": None}
RECORDING = b"\x1aE\xdf\xa3" + bytes(range(256)) * 8


@dataclass(frozen=True)
class Household:
    member: Account
    token: str
    model: HouseholdModel
    openrouter_id: str

    @property
    def admin_token(self) -> str:
        return self.model.admin_token

    @property
    def remote(self) -> dict[str, str]:
        return {"connection_id": self.openrouter_id, "model": "test/popular"}


@pytest.fixture
def household(database: Database, server: Server, default_model: HarnessModel) -> Household:
    member = create_account(database, create_tenant(database))
    model = default_model.connect(member.tenant_id)
    with server.client(model.admin_token) as client:
        response = client.post(
            "/tenant/connections",
            json={
                "name": "OpenRouter",
                "kind": "openrouter",
                "base_url": model.endpoint.openrouter_url,
                "api_key": f"sk-or-v1-{secrets.token_hex(8)}",
            },
        )
    assert response.status_code == 201, response.text
    return Household(member, login(server, member), model, body(response)["id"])


def _budget(server: Server, household: Household, budget: dict[str, Any], user_id: uuid.UUID | None = None) -> None:
    with server.client(household.admin_token) as client:
        response = client.put(f"/tenant/users/{user_id or household.member.id}/budget", json=budget)
    assert response.status_code == 200, response.text


def _cost(amount: str, period: str = "week", time_zone: str = "Europe/Rome") -> dict[str, Any]:
    return {"cost": {"amount": amount, "currency": "USD", "period": period, "time_zone": time_zone}, "tokens": None}


def _tokens(tokens: int, period: str = "day", time_zone: str = "UTC") -> dict[str, Any]:
    return {"cost": None, "tokens": {"tokens": tokens, "period": period, "time_zone": time_zone}}


def _spent(
    database: Database,
    account: Account,
    *,
    cost: str | None = "0",
    currency: str | None = "USD",
    source: str = "provider",
    tokens: tuple[int, int] = (0, 0),
    at: datetime.datetime | None = None,
    model: str = "test/arranged",
) -> None:
    """An entry of the cost ledger, as the gateway would have written it, `at` a time or now."""
    with database.superuser() as conn:
        conn.execute(
            "INSERT INTO usage_ledger (id, tenant_id, owner_id, purpose, provider, model, input_tokens, output_tokens,"
            " cost, currency, price_source, created_at) VALUES (%s, %s, %s, 'run', 'test', %s, %s, %s, %s, %s, %s,"
            " coalesce(%s, now()))",
            (uuid7(), account.tenant_id, account.id, model, *tokens, cost and Decimal(cost), currency, source, at),
        )


def _on_remote_model(server: Server, household: Household) -> str:
    # Named, so that no title is asked for (CNV-006).
    conversation = create_conversation(server, household.token, "Remote")
    with server.client(household.token) as client:
        response = client.patch(f"/conversations/{conversation['id']}", json={"model": household.remote})
    assert response.status_code == 200, response.text
    return str(conversation["id"])


def _refused(server: Server, household: Household, conversation_id: str, text: str) -> None:
    with server.client(household.token) as client:
        response = client.post(f"/conversations/{conversation_id}/runs", json=run_input(conversation_id, text))
    assert_problem(response, 409, "budget.exhausted")
    assert household.model.endpoint.requests_with(text) == [], "the request was sent"


def _answered(server: Server, household: Household, conversation_id: str, text: str) -> None:
    run_id, events = start_run(server, household.token, conversation_id, text)
    assert wait_for_run(server, household.token, run_id)["status"] == "completed"
    assert text_of(events) == f"Echo: {text}"


def _overview(server: Server, token: str, path: str = "/me/usage/overview", **params: str) -> dict[str, Any]:
    with server.client(token) as client:
        response = client.get(path, params=params)
    assert response.status_code == 200, response.text
    return body(response)


# --- MOD-004: setting budgets ---


@pytest.mark.spec("MOD-004")
def test_a_tenant_admin_sets_changes_and_removes_a_members_budget(server: Server, household: Household) -> None:
    path = f"/tenant/users/{household.member.id}/budget"
    both = {
        "cost": {"amount": "5", "currency": "USD", "period": "week", "time_zone": "Europe/Rome"},
        "tokens": {"tokens": 2000000, "period": "month", "time_zone": "America/New_York"},
    }
    with server.client(household.admin_token) as client:
        assert body(client.get(path)) == NO_BUDGET
        response = client.put(path, json=both)
        assert response.status_code == 200, response.text
        assert body(response) == both
        assert body(client.get(path)) == both
        assert body(client.put(path, json=_cost("2.5", "day", "UTC"))) == _cost("2.5", "day", "UTC")
        assert body(client.put(path, json=NO_BUDGET)) == NO_BUDGET
        assert body(client.get(path)) == NO_BUDGET


@pytest.mark.spec("MOD-004", "TEN-006")
def test_only_a_tenant_admin_of_the_household_sets_a_budget(
    database: Database, server: Server, household: Household
) -> None:
    path = f"/tenant/users/{household.member.id}/budget"
    with server.client(household.token) as client:
        assert_problem(client.get(path), 403, "permission.denied")
        assert_problem(client.put(path, json=NO_BUDGET), 403, "permission.denied")
    elsewhere = create_account(database, create_tenant(database), "tenant_admin")
    with server.client(login(server, elsewhere)) as client:
        assert_problem(client.get(path), 404, "resource.not_found")
        assert_problem(client.put(path, json=_cost("1")), 404, "resource.not_found")
    with server.client(household.admin_token) as client:
        assert_problem(client.get(f"/tenant/users/{uuid7()}/budget"), 404, "resource.not_found")


@pytest.mark.spec("MOD-004")
@pytest.mark.parametrize(
    "budget",
    [
        _cost("0"),
        _cost("-1"),
        _cost("1.12345"),
        _cost("1", period="year"),
        _cost("1", time_zone="Mars/Olympus_Mons"),
        {"cost": {"amount": "1", "currency": "usd", "period": "day", "time_zone": "UTC"}, "tokens": None},
        _tokens(0),
        _tokens(1, period="hour"),
        {"cost": None},
    ],
    ids=[
        "zero",
        "negative",
        "too-precise",
        "unknown-period",
        "unknown-zone",
        "currency",
        "no-tokens",
        "hour",
        "partial",
    ],
)
def test_invalid_budgets_are_refused(server: Server, household: Household, budget: dict[str, Any]) -> None:
    with server.client(household.admin_token) as client:
        response = client.put(f"/tenant/users/{household.member.id}/budget", json=budget)
        assert_problem(response, 422, "request.validation_failed")
        assert body(client.get(f"/tenant/users/{household.member.id}/budget")) == NO_BUDGET


# --- MOD-004: the gateway's check ---


@pytest.mark.spec("MOD-004", "MOD-010")
def test_a_token_limit_refuses_runs_on_local_models_only(
    database: Database, server: Server, household: Household
) -> None:
    _spent(database, household.member, cost="0", source="free", tokens=(60, 40))
    _budget(server, household, _tokens(100))
    local = str(create_conversation(server, household.token, "Local")["id"])
    _refused(server, household, local, f"local {secrets.token_hex(4)}")
    # Remote models are not limited by tokens.
    _answered(server, household, _on_remote_model(server, household), f"remote {secrets.token_hex(4)}")


@pytest.mark.spec("MOD-004", "MOD-010")
def test_a_cost_limit_counts_its_currency_and_refuses_runs_on_remote_models_only(
    database: Database, server: Server, household: Household
) -> None:
    _spent(database, household.member, cost="4.99")
    _spent(database, household.member, cost="100", currency="EUR")
    _budget(server, household, _cost("5"))
    remote = _on_remote_model(server, household)
    # 4.99 US dollars, and euros that do not count: under the limit.
    _answered(server, household, remote, f"under {secrets.token_hex(4)}")
    _spent(database, household.member, cost="0.01")
    _refused(server, household, remote, f"over {secrets.token_hex(4)}")
    # Local models are not limited by cost.
    _answered(server, household, str(create_conversation(server, household.token, "Local")["id"]), "local")


@pytest.mark.spec("MOD-004")
def test_a_run_in_progress_fails_before_its_next_request_never_during_a_tool_call(
    server: Server, household: Household
) -> None:
    # The first request finds nothing used; its tokens reach the limit before the second.
    _budget(server, household, _tokens(10))
    conversation_id = str(create_conversation(server, household.token, "Midway")["id"])
    marker = f"midway-{secrets.token_hex(4)}"
    text = f"run:echo {marker}"
    run_id, _ = start_run(server, household.token, conversation_id, text)
    run = wait_for_run(server, household.token, run_id)
    assert (run["status"], run["error_code"]) == ("failed", "budget.exhausted")
    # One request reached the model; the command it asked for ran to its end.
    assert len(household.model.endpoint.requests_with(text)) == 1
    page = messages(server, household.token, conversation_id)
    assert marker in json.dumps(page)
    assert page["runs"][0]["error"]["code"] == "budget.exhausted"


@pytest.mark.spec("MOD-004", "TSK-010")
def test_a_tasks_run_fails_on_its_budget(database: Database, server: Server, household: Household) -> None:
    _spent(database, household.member, cost="0", source="free", tokens=(5, 5))
    _budget(server, household, _tokens(10))
    task = create_task(server, household.token)
    with server.client(household.token) as client:
        assert client.post(f"/tasks/{task['id']}/fire").status_code == 202
    (conversation,) = wait_for_conversations(server, household.token, task["id"])
    assert conversation["outcome"] == "failed"
    (run,) = path_runs(server, household.token, conversation["conversation_id"])
    assert run["error"]["code"] == "budget.exhausted"


@pytest.mark.spec("MOD-004", "API-006")
def test_speech_is_refused_once_its_limit_is_reached(database: Database, server: Server, household: Household) -> None:
    with server.client(household.admin_token) as client:
        response = client.put(
            "/tenant/speech",
            json={
                "transcription": {"connection_id": household.openrouter_id, "model": "test/transcribe"},
                "speech": {"connection_id": household.openrouter_id, "model": "test/voice", "voice": "nova"},
            },
        )
    assert response.status_code == 200, response.text
    _spent(database, household.member, cost="1")
    _budget(server, household, _cost("1", "month"))
    endpoint = household.model.endpoint
    transcriptions, syntheses = len(endpoint.speech("/audio/transcriptions")), len(endpoint.speech("/audio/speech"))
    with server.client(household.token) as client:
        heard = client.post("/speech/transcriptions", files={"audio": ("turn.webm", RECORDING, "audio/webm")})
        assert_problem(heard, 409, "budget.exhausted")
        assert_problem(client.post("/speech/synthesis", json={"text": "Hello"}), 409, "budget.exhausted")
    assert len(endpoint.speech("/audio/transcriptions")) == transcriptions
    assert len(endpoint.speech("/audio/speech")) == syntheses
    # The admin, who has no budget, still speaks.
    with server.client(household.admin_token) as client:
        assert client.post("/speech/synthesis", json={"text": "Hello"}).status_code == 200


def _week_start(zone: str) -> datetime.datetime:
    now = datetime.datetime.now(zoneinfo.ZoneInfo(zone))
    monday = (now - datetime.timedelta(days=now.weekday())).date()
    return datetime.datetime.combine(monday, datetime.time(), zoneinfo.ZoneInfo(zone))


@pytest.mark.spec("MOD-004", "MOD-021")
def test_a_period_counts_from_its_first_moment_in_its_time_zone(
    database: Database, server: Server, household: Household
) -> None:
    start = _week_start("Europe/Rome")
    end = datetime.datetime.combine(
        (start + datetime.timedelta(days=7)).date(), datetime.time(), zoneinfo.ZoneInfo("Europe/Rome")
    )
    # Just before the week started: not counted.
    _spent(database, household.member, cost="100", at=start - datetime.timedelta(minutes=1))
    _spent(database, household.member, cost="1.5")
    _budget(server, household, _cost("5"))
    _answered(server, household, _on_remote_model(server, household), f"this week {secrets.token_hex(4)}")
    (limit,) = _overview(server, household.token)["limits"]
    used = Decimal("1.5") + Decimal(str(OPENROUTER_COST))
    assert {key: limit[key] for key in ("kind", "period", "time_zone", "limit", "currency", "exhausted")} == {
        "kind": "cost",
        "period": "week",
        "time_zone": "Europe/Rome",
        "limit": "5",
        "currency": "USD",
        "exhausted": False,
    }
    assert Decimal(limit["used"]) == used
    assert limit["share"] == pytest.approx(float(used / 5))
    assert datetime.datetime.fromisoformat(limit["starts_at"]) == start
    assert datetime.datetime.fromisoformat(limit["ends_at"]) == end


@pytest.mark.spec("MOD-004", "MOD-021")
def test_an_exhausted_limit_says_so_until_its_period_ends(
    database: Database, server: Server, household: Household
) -> None:
    _spent(database, household.member, cost="0", source="free", tokens=(700, 300))
    _budget(server, household, _tokens(1000, "day", "UTC"))
    (limit,) = _overview(server, household.token)["limits"]
    today = datetime.datetime.now(datetime.UTC).date()
    assert (limit["kind"], limit["used"], limit["limit"], limit["currency"]) == ("tokens", "1000", "1000", None)
    assert (limit["share"], limit["exhausted"]) == (1, True)
    assert datetime.datetime.fromisoformat(limit["ends_at"]) == datetime.datetime.combine(
        today + datetime.timedelta(days=1), datetime.time(), datetime.UTC
    )


# --- MOD-021: usage over time ---


@pytest.mark.spec("MOD-021")
def test_usage_sums_since_the_account_was_created_per_month_day_and_model(
    database: Database, server: Server, household: Household
) -> None:
    now = datetime.datetime.now(datetime.UTC)
    member = household.member
    _spent(database, member, cost="0.5", tokens=(100, 50), model="test/paid")
    _spent(database, member, cost="0.25", tokens=(10, 5), model="test/paid", at=now - datetime.timedelta(days=3))
    _spent(database, member, cost="0", source="free", tokens=(1000, 500), model="test/local")
    _spent(database, member, cost=None, currency=None, source="unknown", tokens=(7, 3), model="test/unpriced")
    _spent(database, member, cost="2", tokens=(1, 1), model="test/paid", at=now - datetime.timedelta(days=45))
    overview = _overview(server, household.token, time_zone="UTC")
    with database.superuser() as conn:
        created = conn.execute("SELECT created_at FROM users WHERE id = %s", (member.id,)).fetchone()
    assert created is not None
    assert datetime.datetime.fromisoformat(overview["since"]) == created[0]
    assert overview["time_zone"] == "UTC"
    assert overview["total"] == {
        "cost": [{"amount": "2.75", "currency": "USD"}],
        "local_tokens": 1500,
        "remote_tokens": 177,
        "requests": 5,
        "unpriced_requests": 1,
    }
    days = {day["day"]: day for day in overview["days"]}
    # The last 30 days only, and only days with usage.
    assert set(days) == {now.date().isoformat(), (now - datetime.timedelta(days=3)).date().isoformat()}
    assert days[now.date().isoformat()]["requests"] == 3
    months = {month["month"]: month for month in overview["months"]}
    assert sum(month["requests"] for month in months.values()) == 5
    assert (now - datetime.timedelta(days=45)).strftime("%Y-%m") in months
    models = {item["model"]: item for item in overview["models"]}
    assert set(models) == {"test/paid", "test/local", "test/unpriced"}
    assert models["test/paid"]["cost"] == [{"amount": "2.75", "currency": "USD"}]
    assert (models["test/local"]["local_tokens"], models["test/local"]["remote_tokens"]) == (1500, 0)
    assert models["test/unpriced"]["unpriced_requests"] == 1
    assert overview["limits"] == []


@pytest.mark.spec("MOD-021")
def test_days_are_those_of_the_time_zone_the_client_gives(
    database: Database, server: Server, household: Household
) -> None:
    yesterday = datetime.datetime.now(datetime.UTC).date() - datetime.timedelta(days=1)
    # Half past eleven in the evening in UTC is already the next day in Rome, in summer and in winter.
    late = datetime.datetime.combine(yesterday, datetime.time(23, 30), datetime.UTC)
    _spent(database, household.member, cost="1", at=late)
    in_utc = _overview(server, household.token, time_zone="UTC")["days"]
    in_rome = _overview(server, household.token, time_zone="Europe/Rome")["days"]
    assert [day["day"] for day in in_utc] == [yesterday.isoformat()]
    assert [day["day"] for day in in_rome] == [(yesterday + datetime.timedelta(days=1)).isoformat()]
    with server.client(household.token) as client:
        assert_problem(
            client.get("/me/usage/overview", params={"time_zone": "Nowhere/Land"}), 422, "request.validation_failed"
        )


@pytest.mark.spec("MOD-021", "TEN-006", "TEN-007")
def test_a_tenant_admin_sees_a_members_usage_and_nobody_else_does(
    database: Database, server: Server, household: Household
) -> None:
    _spent(database, household.member, cost="0.5", model="test/paid")
    _budget(server, household, _cost("10", "month"))
    own = _overview(server, household.token, time_zone="UTC")
    path = f"/tenant/users/{household.member.id}/usage"
    assert _overview(server, household.admin_token, path, time_zone="UTC") == own
    other = create_account(database, household.member.tenant_id)
    with server.client(login(server, other)) as client:
        assert_problem(client.get(path), 403, "permission.denied")
    elsewhere = create_account(database, create_tenant(database), "tenant_admin")
    with server.client(login(server, elsewhere)) as client:
        assert_problem(client.get(path), 404, "resource.not_found")
    # Only sums: nothing names a conversation or a run.
    assert "conversation" not in json.dumps(own)
    assert "run_id" not in json.dumps(own)
