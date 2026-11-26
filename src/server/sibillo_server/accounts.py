"""A tenant admin gives a user a new initial password, and deletes a disabled account (AUTH-013, AUTH-014,
ADR-0144).

The database decides too: the `users` guard allows a new password from a
tenant admin only as an initial one, and the administration functions check
the request context themselves; the checks here choose the answer.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from sibillo_server import errors, schemas
from sibillo_server.auth import USER_COLUMNS, Authenticated, Engine, user_response
from sibillo_server.conversations import Durable
from sibillo_server.credentials import hash_password
from sibillo_server.database import INSUFFICIENT_PRIVILEGE, sqlstate, transaction
from sibillo_server.sandbox import SandboxDriver, delete_account_workspace

router = APIRouter()

OBJECT_IN_USE = "55006"
NO_DATA_FOUND = "P0002"


def _in_progress() -> errors.ApiError:
    return errors.ApiError(409, "run.in_progress", "Run in progress")


@router.post("/tenant/users/{user_id}/password", response_model=schemas.User)
async def reset_password(
    user_id: uuid.UUID, body: schemas.ResetPasswordRequest, identity: Authenticated, engine: Engine
) -> schemas.User:
    """A new initial password, which ends the account's sessions and keeps its passkeys (AUTH-013, ADR-0144)."""
    # Their own is changed with the current password (AUTH-011).
    if not identity.tenant_admin or user_id == identity.user_id:
        raise errors.permission_denied()
    async with transaction(engine, identity) as connection:
        target = (
            await connection.execute(text("SELECT instance_admin FROM users WHERE id = :id"), {"id": user_id})
        ).one_or_none()
    if target is None:
        raise errors.not_found()
    if target.instance_admin and not identity.instance_admin:
        raise errors.permission_denied()
    password_hash = await hash_password(body.password)
    try:
        async with transaction(engine, identity) as connection:
            # The trigger of the `users` table revokes the sessions and forgets the subscriptions.
            changed = await connection.execute(
                text("UPDATE users SET password_hash = :hash, password_change_required = true WHERE id = :id"),
                {"hash": password_hash, "id": user_id},
            )
            if changed.rowcount == 0:
                raise errors.not_found()
            row = (
                await connection.execute(text(f"SELECT {USER_COLUMNS} FROM users WHERE id = :id"), {"id": user_id})  # noqa: S608
            ).one()
    except DBAPIError as error:
        if sqlstate(error) == INSUFFICIENT_PRIVILEGE:
            raise errors.permission_denied() from None
        raise
    return user_response(row)


@router.delete("/tenant/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_user(
    user_id: uuid.UUID, identity: Authenticated, engine: Engine, durable: Durable, request: Request
) -> Response:
    """Delete a disabled account and everything of its user, for good (AUTH-014, ADR-0144).

    What lives outside the tables goes first, from the identifiers `account_storage` returns: the workflows,
    which hold content without row-level security (TEN-009), and the workspaces (TEN-008); then the row, with
    every row of the user by cascade. When a step fails, the account stays disabled, and deleting it again
    finishes the work.
    """
    if not identity.tenant_admin or user_id == identity.user_id:
        raise errors.permission_denied()
    async with transaction(engine, identity) as connection:
        target = (
            await connection.execute(
                text("SELECT tenant_id, instance_admin, disabled_at FROM users WHERE id = :id"), {"id": user_id}
            )
        ).one_or_none()
        if target is None:
            raise errors.not_found()
        if target.instance_admin:
            raise errors.permission_denied()
        if target.disabled_at is None:
            raise errors.conflict()
        storage = await _storage(connection, user_id)
    workflows = [str(item) for kind, item in storage if kind == "run"]
    workflows += [f"firing-{item}" for kind, item in storage if kind == "firing"]
    if workflows:
        await durable.delete_workflows_async(workflows)
    configuration = request.app.state.configuration
    driver = SandboxDriver(configuration.sandboxd_url, configuration.sandboxd_token)
    for kind, item in storage:
        if kind == "conversation":
            await delete_account_workspace(driver, target.tenant_id, user_id, item)
    try:
        async with transaction(engine, identity) as connection:
            await connection.execute(text("SELECT delete_account(:id)"), {"id": user_id})
    except DBAPIError as error:
        _refused(error)
        raise
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _storage(connection: AsyncConnection, user_id: uuid.UUID) -> list[tuple[str, uuid.UUID]]:
    """The account's conversations, runs and task firings, or the answer for what the function refuses."""
    try:
        rows = (await connection.execute(text("SELECT kind, id FROM account_storage(:id)"), {"id": user_id})).all()
    except DBAPIError as error:
        _refused(error)
        raise
    return [(row.kind, row.id) for row in rows]


def _refused(error: DBAPIError) -> None:
    """The answer for what the administration functions refuse."""
    code = sqlstate(error)
    if code == OBJECT_IN_USE:
        raise _in_progress() from None
    if code == INSUFFICIENT_PRIVILEGE:
        raise errors.permission_denied() from None
    if code == NO_DATA_FOUND:
        raise errors.not_found() from None
