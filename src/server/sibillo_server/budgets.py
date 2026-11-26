"""Budgets per user, checked before each model request, and usage over time (MOD-004, MOD-021, ADR-0145).

A budget holds up to two limits: a cost limit on the requests to remote
models and a token limit on the requests to local ones, each counted over a
calendar day, week from Monday or month in its time zone. The model gateway,
the start of a run and speech check the limit for where their model runs;
the user and their tenant admins see the sums of `usage_of_user`, never an
entry of the cost ledger.
"""

from __future__ import annotations

import datetime
import uuid
import zoneinfo
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from sibillo_server import errors, schemas
from sibillo_server.auth import Authenticated, Engine
from sibillo_server.costs import amount
from sibillo_server.database import INSUFFICIENT_PRIVILEGE, Identity, sqlstate, transaction

router = APIRouter()

type Kind = Literal["cost", "tokens"]

# The kind of limit that applies to a model, by where its inference runs (MOD-010).
KIND_OF_LOCATION: dict[str, Kind] = {"remote": "cost", "local": "tokens"}
# The days of usage shown one by one.
DAYS = 30
NO_DATA_FOUND = "P0002"


class BudgetExhaustedError(Exception):
    """A model request the user's budget refuses; it is never sent."""


def exhausted() -> errors.ApiError:
    return errors.ApiError(409, "budget.exhausted", "The budget is used up")


@dataclass(frozen=True)
class Limit:
    kind: Kind
    amount: Decimal
    currency: str | None
    period: schemas.BudgetPeriod
    time_zone: str

    def bounds(self, now: datetime.datetime) -> tuple[datetime.datetime, datetime.datetime]:
        """When the current period started and when it ends, at midnight in the limit's time zone (ADR-0145)."""
        zone = zoneinfo.ZoneInfo(self.time_zone)
        today = now.astimezone(zone).date()
        if self.period == "day":
            first, after = today, today + datetime.timedelta(days=1)
        elif self.period == "week":
            first = today - datetime.timedelta(days=today.weekday())
            after = first + datetime.timedelta(days=7)
        else:
            first = today.replace(day=1)
            after = (first + datetime.timedelta(days=32)).replace(day=1)
        midnight = datetime.time()
        return datetime.datetime.combine(first, midnight, zone), datetime.datetime.combine(after, midnight, zone)


def zone(name: str, location: str) -> str:
    """An IANA time zone name, or a validation failure at `location`."""
    try:
        zoneinfo.ZoneInfo(name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        raise errors.invalid(location, "unknown") from None
    return name


def _limit(row: Any) -> Limit:
    return Limit(row.kind, Decimal(row.amount), row.currency, row.period, row.time_zone)


async def limits_of(connection: AsyncConnection, user_id: uuid.UUID) -> list[Limit]:
    """The user's limits, as row-level security lets the caller read them: their own, or as a tenant admin."""
    rows = (
        await connection.execute(
            text("SELECT kind, amount, currency, period, time_zone FROM budgets WHERE user_id = :id ORDER BY kind"),
            {"id": user_id},
        )
    ).all()
    return [_limit(row) for row in rows]


async def _own_use(connection: AsyncConnection, limit: Limit, start: datetime.datetime) -> Decimal:
    """What the user of the request context used since `start`, as the limit counts it; the ledger is theirs."""
    if limit.kind == "cost":
        query = (
            "SELECT coalesce(sum(cost), 0) FROM usage_ledger"
            " WHERE owner_id = app_user_id() AND currency = :currency AND created_at >= :start"
        )
    else:
        query = (
            "SELECT coalesce(sum(input_tokens + output_tokens), 0) FROM usage_ledger"
            " WHERE owner_id = app_user_id() AND price_source = 'free' AND created_at >= :start"
        )
    used = (await connection.execute(text(query), {"currency": limit.currency, "start": start})).scalar_one()
    return Decimal(used)


async def refusing(connection: AsyncConnection, location: str) -> bool:
    """Whether the limit of the user of the request context for a model at `location` is reached in its current
    period (MOD-004)."""
    kind = KIND_OF_LOCATION.get(location)
    row = (
        await connection.execute(
            text(
                "SELECT kind, amount, currency, period, time_zone FROM budgets"
                " WHERE user_id = app_user_id() AND kind = :kind"
            ),
            {"kind": kind},
        )
    ).one_or_none()
    limit = None if row is None else _limit(row)
    if limit is None:
        return False
    start, _ = limit.bounds(datetime.datetime.now(datetime.UTC))
    return await _own_use(connection, limit, start) >= limit.amount


async def check(engine: AsyncEngine, identity: Identity, location: str) -> None:
    """Refuse a model request the user's budget does not allow, before it is sent (MOD-004, ADR-0145)."""
    async with transaction(engine, identity) as connection:
        refused = await refusing(connection, location)
    if refused:
        raise BudgetExhaustedError(f"the {KIND_OF_LOCATION[location]} limit is reached")


async def refuse(connection: AsyncConnection, location: str) -> None:
    """The same, for the API, as `budget.exhausted`."""
    if await refusing(connection, location):
        raise exhausted()


# --- Budgets of the household's users (MOD-004) ---


def _budget(limits: Iterable[Limit]) -> schemas.Budget:
    budget = schemas.Budget(cost=None, tokens=None)
    for limit in limits:
        if limit.kind == "cost":
            budget.cost = schemas.CostLimit(
                amount=amount(limit.amount),
                currency=limit.currency or "USD",
                period=limit.period,
                time_zone=limit.time_zone,
            )
        else:
            budget.tokens = schemas.TokenLimit(tokens=int(limit.amount), period=limit.period, time_zone=limit.time_zone)
    return budget


async def _find_user(connection: AsyncConnection, user_id: uuid.UUID) -> Any:
    """A user of the caller's tenant, which row-level security decides, or `404`."""
    row = (
        await connection.execute(text("SELECT id, created_at FROM users WHERE id = :id"), {"id": user_id})
    ).one_or_none()
    if row is None:
        raise errors.not_found()
    return row


@router.get("/tenant/users/{user_id}/budget", response_model=schemas.Budget)
async def get_budget(user_id: uuid.UUID, identity: Authenticated, engine: Engine) -> schemas.Budget:
    if not identity.tenant_admin:
        raise errors.permission_denied()
    async with transaction(engine, identity) as connection:
        await _find_user(connection, user_id)
        return _budget(await limits_of(connection, user_id))


@router.put("/tenant/users/{user_id}/budget", response_model=schemas.Budget)
async def set_budget(
    user_id: uuid.UUID, body: schemas.Budget, identity: Authenticated, engine: Engine
) -> schemas.Budget:
    """Replace a user's limits; a `null` limit is removed. Applies from the next model request."""
    if not identity.tenant_admin:
        raise errors.permission_denied()
    limits: list[Limit] = []
    if body.cost is not None:
        cost = Decimal(body.cost.amount)
        if cost <= 0:
            raise errors.invalid("/cost/amount", "not_positive")
        zone(body.cost.time_zone, "/cost/time_zone")
        limits.append(Limit("cost", cost, body.cost.currency, body.cost.period, body.cost.time_zone))
    if body.tokens is not None:
        zone(body.tokens.time_zone, "/tokens/time_zone")
        limits.append(Limit("tokens", Decimal(body.tokens.tokens), None, body.tokens.period, body.tokens.time_zone))
    async with transaction(engine, identity) as connection:
        user = await _find_user(connection, user_id)
        await connection.execute(text("DELETE FROM budgets WHERE user_id = :id"), {"id": user.id})
        for limit in limits:
            await connection.execute(
                text(
                    "INSERT INTO budgets (tenant_id, user_id, kind, amount, currency, period, time_zone, updated_at)"
                    " VALUES (:tenant_id, :user_id, :kind, :amount, :currency, :period, :time_zone, now())"
                ),
                {
                    "tenant_id": identity.tenant_id,
                    "user_id": user.id,
                    "kind": limit.kind,
                    "amount": limit.amount,
                    "currency": limit.currency,
                    "period": limit.period,
                    "time_zone": limit.time_zone,
                },
            )
        return _budget(await limits_of(connection, user_id))


# --- Usage over time (MOD-021) ---


@dataclass
class _Totals:
    cost: dict[str, Decimal]
    local_tokens: int = 0
    remote_tokens: int = 0
    requests: int = 0
    unpriced_requests: int = 0

    def add(self, row: Any) -> None:
        tokens = int(row.input_tokens) + int(row.output_tokens)
        if row.price_source == "free":
            self.local_tokens += tokens
        else:
            self.remote_tokens += tokens
        if row.cost is not None and row.currency is not None:
            self.cost[row.currency] = self.cost.get(row.currency, Decimal(0)) + Decimal(row.cost)
        else:
            self.unpriced_requests += int(row.requests)
        self.requests += int(row.requests)

    def fields(self) -> dict[str, Any]:
        return {
            "cost": [
                schemas.Money(amount=amount(total), currency=currency) for currency, total in sorted(self.cost.items())
            ],
            "local_tokens": self.local_tokens,
            "remote_tokens": self.remote_tokens,
            "requests": self.requests,
            "unpriced_requests": self.unpriced_requests,
        }


def _totals() -> _Totals:
    return _Totals(cost={})


async def _usage_rows(connection: AsyncConnection, user_id: uuid.UUID, time_zone: str) -> list[Any]:
    """The user's sums per day in `time_zone`, from the function that returns only those (ADR-0145)."""
    try:
        return list(
            (
                await connection.execute(
                    text("SELECT * FROM usage_of_user(:id, :zone)"), {"id": user_id, "zone": time_zone}
                )
            ).all()
        )
    except DBAPIError as error:
        if sqlstate(error) == NO_DATA_FOUND:
            raise errors.not_found() from None
        if sqlstate(error) == INSUFFICIENT_PRIVILEGE:
            raise errors.permission_denied() from None
        raise


def _state(limit: Limit, rows: list[Any], now: datetime.datetime) -> schemas.LimitState:
    start, end = limit.bounds(now)
    used = Decimal(0)
    for row in rows:
        if not start.date() <= row.day < end.date():
            continue
        if limit.kind == "cost":
            if row.currency == limit.currency and row.cost is not None:
                used += Decimal(row.cost)
        elif row.price_source == "free":
            used += int(row.input_tokens) + int(row.output_tokens)
    return schemas.LimitState(
        kind=limit.kind,
        period=limit.period,
        time_zone=limit.time_zone,
        limit=amount(limit.amount),
        used=amount(used),
        currency=limit.currency,
        share=float(used / limit.amount),
        exhausted=used >= limit.amount,
        starts_at=start,
        ends_at=end,
    )


async def overview(connection: AsyncConnection, user: Any, time_zone: str) -> schemas.UsageOverview:
    """A user's usage since their account was created, per month, per day and per model, and their limits."""
    now = datetime.datetime.now(datetime.UTC)
    rows = await _usage_rows(connection, user.id, time_zone)
    total = _totals()
    months: dict[str, _Totals] = defaultdict(_totals)
    days: dict[datetime.date, _Totals] = defaultdict(_totals)
    models: dict[tuple[str, str], _Totals] = defaultdict(_totals)
    first_day = now.astimezone(zoneinfo.ZoneInfo(time_zone)).date() - datetime.timedelta(days=DAYS - 1)
    for row in rows:
        total.add(row)
        months[row.day.strftime("%Y-%m")].add(row)
        models[(row.provider, row.model)].add(row)
        if row.day >= first_day:
            days[row.day].add(row)
    by_zone = {time_zone: rows}
    states: list[schemas.LimitState] = []
    for limit in await limits_of(connection, user.id):
        if limit.time_zone not in by_zone:
            by_zone[limit.time_zone] = await _usage_rows(connection, user.id, limit.time_zone)
        states.append(_state(limit, by_zone[limit.time_zone], now))
    return schemas.UsageOverview(
        since=user.created_at,
        time_zone=time_zone,
        total=schemas.UsageTotals(**total.fields()),
        months=[schemas.UsageMonth(month=month, **sums.fields()) for month, sums in sorted(months.items())],
        days=[schemas.UsageDay(day=day, **sums.fields()) for day, sums in sorted(days.items())],
        models=[
            schemas.UsageModel(provider=provider, model=model, **sums.fields())
            for (provider, model), sums in sorted(models.items())
        ],
        limits=states,
    )


# The time zone the days and months of a usage overview are counted in; UTC when absent.
type UsageTimeZone = Annotated[str | None, Query(max_length=64)]


@router.get("/me/usage/overview", response_model=schemas.UsageOverview)
async def own_usage(identity: Authenticated, engine: Engine, time_zone: UsageTimeZone = None) -> schemas.UsageOverview:
    name = zone(time_zone or "UTC", "/time_zone")
    async with transaction(engine, identity) as connection:
        return await overview(connection, await _find_user(connection, identity.user_id), name)


@router.get("/tenant/users/{user_id}/usage", response_model=schemas.UsageOverview)
async def user_usage(
    user_id: uuid.UUID,
    identity: Authenticated,
    engine: Engine,
    time_zone: UsageTimeZone = None,
) -> schemas.UsageOverview:
    """A user's usage, for a tenant admin of their tenant: only sums (MOD-021, TEN-007)."""
    if not identity.tenant_admin:
        raise errors.permission_denied()
    name = zone(time_zone or "UTC", "/time_zone")
    async with transaction(engine, identity) as connection:
        return await overview(connection, await _find_user(connection, user_id), name)
