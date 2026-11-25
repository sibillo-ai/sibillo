"""Attempts to read, add, change or remove other users' passkeys as `sibillo_app`.

The policies of `passkeys` in specs/contracts/database.md (AUTH-010,
ADR-0094): a user reaches only their own passkeys; a tenant admin also
counts and removes those of the users of their tenant, but never adds or
changes one.
"""

from __future__ import annotations

import secrets

import pytest

from tests.support.assertions import assert_changes_nothing, assert_denied
from tests.support.database import Context, Database, app_transaction, uuid7
from tests.support.world import User, World

INSERT = (
    "INSERT INTO passkeys (id, tenant_id, user_id, credential_id, public_key, sign_count, name, created_at)"
    " VALUES (%s, %s, %s, %s, 'key', 0, 'Intruder', now())"
)


def _context(user: User) -> Context:
    return Context(user.tenant_id, user.id, user.role)


def _visible(database: Database, actor: User) -> set[object]:
    with app_transaction(database, _context(actor)) as conn:
        return {user_id for (user_id,) in conn.execute("SELECT user_id FROM passkeys").fetchall()}


def _passkeys_left(database: Database, user: User) -> int:
    with database.superuser() as conn:
        (count,) = conn.execute("SELECT count(*) FROM passkeys WHERE user_id = %s", (user.id,)).fetchone() or (0,)
    return int(count)


@pytest.mark.spec("AUTH-010", "TEN-006")
def test_members_see_only_their_own_passkeys(database: Database, world: World) -> None:
    assert _visible(database, world.alice) == {world.alice.id}
    assert _visible(database, world.bob) == {world.bob.id}


@pytest.mark.spec("AUTH-010", "TEN-006")
def test_tenant_admins_see_the_passkeys_of_their_tenant_only(database: Database, world: World) -> None:
    assert _visible(database, world.anna) == {world.alice.id, world.anna.id}


@pytest.mark.spec("AUTH-010", "TEN-006")
def test_members_cannot_remove_or_change_the_passkeys_of_others(database: Database, world: World) -> None:
    with app_transaction(database, _context(world.alice)) as conn:
        for victim in (world.anna, world.bob):
            assert_changes_nothing(conn, "DELETE FROM passkeys WHERE user_id = %s", (victim.id,))
            assert_changes_nothing(conn, "UPDATE passkeys SET sign_count = 99 WHERE user_id = %s", (victim.id,))
        conn.commit()
    assert _passkeys_left(database, world.anna) == _passkeys_left(database, world.bob) == 1


@pytest.mark.spec("AUTH-010", "TEN-006")
def test_tenant_admins_remove_but_never_add_or_change_the_passkeys_of_a_user(database: Database, world: World) -> None:
    with app_transaction(database, _context(world.anna)) as conn:
        assert_denied(conn, INSERT, (uuid7(), world.alice.tenant_id, world.alice.id, secrets.token_bytes(32)))
        assert_changes_nothing(conn, "UPDATE passkeys SET sign_count = 99 WHERE user_id = %s", (world.alice.id,))
        assert_changes_nothing(conn, "DELETE FROM passkeys WHERE user_id = %s", (world.bob.id,))
        # Control: the admin's removal of a member's passkeys goes through.
        removed = conn.execute("DELETE FROM passkeys WHERE user_id = %s", (world.alice.id,)).rowcount
        assert removed == 1


@pytest.mark.spec("AUTH-010", "TEN-006")
def test_nobody_adds_a_passkey_for_someone_else(database: Database, world: World) -> None:
    for actor, victim in ((world.alice, world.anna), (world.alice, world.bob), (world.anna, world.bob)):
        with app_transaction(database, _context(actor)) as conn:
            assert_denied(conn, INSERT, (uuid7(), victim.tenant_id, victim.id, secrets.token_bytes(32)))
    # Control: a user adds their own.
    with app_transaction(database, _context(world.alice)) as conn:
        conn.execute(INSERT, (uuid7(), world.alice.tenant_id, world.alice.id, secrets.token_bytes(32)))
