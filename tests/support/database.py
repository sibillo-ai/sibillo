"""Database under test, set up as the test harness contract prescribes.

See specs/contracts/test-harness.md: PostgreSQL 17 in a container, the
initialization of the database contract run as superuser, migrations run as
`sibillo_owner`, assertions made as `sibillo_app`.
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
import time
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

ROOT = Path(__file__).resolve().parents[2]
POSTGRES_IMAGE = "postgres:17.6"
DATABASE_NAME = "sibillo"
MIGRATION_TIMEOUT_SECONDS = 300

# Tables of the database contract, by kind.
PRIVATE_TABLES = (
    "device_sessions",
    "passkey_challenges",
    "folders",
    "user_settings",
    "memory_items",
    "skills",
    "skill_files",
    "conversations",
    "conversation_plans",
    "conversation_messages",
    "compaction_checkpoints",
    "delegations",
    "runs",
    "usage_ledger",
    "audit_events",
    # Each user's own credential for a remote MCP server, and their sign-ins (AGT-030, AGT-031, ADR-0099).
    "mcp_credentials",
    "mcp_sign_ins",
    # A device session's notification subscription, and the open event streams of runs (UX-004, ADR-0101).
    "notification_subscriptions",
    "run_followers",
    # A user's tasks, their grants, triggers and firings (TSK-001, ADR-0106).
    "tasks",
    "task_grants",
    "task_triggers",
    "task_firings",
)
# Configuration of the instance, without a tenant.
INSTANCE_TABLES = ("tenants",)
# Tables of a tenant that are not private to one user (ADR-0069).
TENANT_TABLES = (
    "users",
    "connections",
    "connection_models",
    "served_context_windows",
    "tool_permissions",
    "egress_policies",
    # A tenant admin's limits on a user's model requests (MOD-004, ADR-0145).
    "budgets",
    "passkeys",
    # A household's remote MCP servers and their tools (AGT-019, AGT-028, ADR-0099).
    "mcp_servers",
    "mcp_server_tools",
    # The event types of a household's remote MCP servers (TSK-008, ADR-0106).
    "mcp_server_events",
)
CONTRACT_TABLES = ("tenants", "login_attempts", *TENANT_TABLES, *PRIVATE_TABLES)
# Column holding the owning user of each private table.
OWNER_COLUMN = {
    table: "user_id" if table in ("device_sessions", "passkey_challenges") else "owner_id" for table in PRIVATE_TABLES
}
# Schemas that are not part of the application schema.
SYSTEM_SCHEMAS = ("pg_catalog", "information_schema", "pg_toast")
DURABLE_EXECUTION_SCHEMA = "dbos"

SECURITY_DEFINER_FUNCTIONS = (
    "auth_find_login",
    "auth_find_session",
    "auth_touch_session",
    "auth_record_login_attempt",
    # Read-only, before a password is checked (ADR-0118).
    "auth_check_login_attempt",
    # Runs a crash left active (ADR-0130).
    "abandoned_runs",
    "auth_take_sign_in",
    "bootstrap_instance",
    "remove_passkeys",
    # Disabling an account and giving it a new initial password end its sessions (AUTH-009, AUTH-013, ADR-0144).
    "revoke_sessions_of_user",
    # What a tenant admin does with another user's private rows (ADR-0144, ADR-0145).
    "usage_of_user",
    "account_storage",
    "delete_account",
    "retention_expired_runs",
    "expired_temporary_conversations",
    "expired_approvals",
    "default_model_configured",
    # The work of tasks, found before any request context (ADR-0106).
    "due_task_triggers",
    "waiting_task_firings",
    "find_webhook_trigger",
    "find_event_subscription",
)


@dataclass(frozen=True)
class Database:
    host: str
    port: int
    superuser_url: str
    app_url: str
    # Only for operator commands that tests run, such as `remove-passkeys` (test-harness.md).
    owner_url: str = ""

    def superuser(self) -> psycopg.Connection:
        """Connection for catalog inspection and arranging data, never for assertions on `sibillo_app`."""
        return psycopg.connect(self.superuser_url, autocommit=True)

    def app(self) -> psycopg.Connection:
        """Connection as the application role, in a transaction."""
        return psycopg.connect(self.app_url)


def uuid7() -> uuid.UUID:
    """A version 7 UUID, as the database contract prescribes for identifiers."""
    value = (time.time_ns() // 1_000_000) << 80 | secrets.randbits(80)
    value = (value & ~(0xF << 76)) | (0x7 << 76)
    value = (value & ~(0x3 << 62)) | (0x2 << 62)
    return uuid.UUID(int=value)


def _initialize(superuser_url: str, owner_password: str, app_password: str) -> None:
    # The initialization of specs/contracts/database.md, with test passwords.
    with psycopg.connect(superuser_url, autocommit=True) as conn:
        conn.execute(
            sql.SQL(
                "CREATE ROLE sibillo_owner LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE"
            ).format(sql.Literal(owner_password))
        )
        conn.execute(
            sql.SQL(
                "CREATE ROLE sibillo_app LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOINHERIT"
            ).format(sql.Literal(app_password))
        )
        conn.execute(f"CREATE DATABASE {DATABASE_NAME} OWNER sibillo_owner")
        conn.execute(f"REVOKE ALL ON DATABASE {DATABASE_NAME} FROM PUBLIC")
        conn.execute(f"GRANT CONNECT ON DATABASE {DATABASE_NAME} TO sibillo_app")


def _migrate(owner_url: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "migrations/alembic.ini", "upgrade", "head"],
        cwd=ROOT,
        env={**os.environ, "SIBILLO_DATABASE_URL": owner_url},
        capture_output=True,
        text=True,
        timeout=MIGRATION_TIMEOUT_SECONDS,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"migrations failed (exit {result.returncode}):\n{result.stdout}\n{result.stderr}")


_DATABASE = pytest.StashKey[Database | BaseException]()


def start_database(config: pytest.Config) -> Database:
    """Start the database once per test session; later calls return the same one."""
    cached = config.stash.get(_DATABASE, None)
    if isinstance(cached, BaseException):
        raise cached
    if cached is not None:
        return cached

    from testcontainers.community.postgres import PostgresContainer

    container = PostgresContainer(POSTGRES_IMAGE, password=secrets.token_hex(16), driver=None)
    try:
        container.start()
        config.add_cleanup(container.stop)
        host = container.get_container_host_ip()
        port = int(container.get_exposed_port(5432))
        superuser_url = container.get_connection_url()
        owner_password, app_password = secrets.token_hex(16), secrets.token_hex(16)
        _initialize(superuser_url, owner_password, app_password)
        _migrate(f"postgresql://sibillo_owner:{owner_password}@{host}:{port}/{DATABASE_NAME}")
        database = Database(
            host=host,
            port=port,
            superuser_url=f"postgresql://{container.username}:{container.password}@{host}:{port}/{DATABASE_NAME}",
            app_url=f"postgresql://sibillo_app:{app_password}@{host}:{port}/{DATABASE_NAME}",
            owner_url=f"postgresql://sibillo_owner:{owner_password}@{host}:{port}/{DATABASE_NAME}",
        )
    except BaseException as exc:
        config.stash[_DATABASE] = exc
        raise
    config.stash[_DATABASE] = database
    return database


@dataclass(frozen=True)
class Context:
    """The request context of the database contract."""

    tenant_id: uuid.UUID
    user_id: uuid.UUID
    role: str = "member"
    instance_admin: bool = False


@contextmanager
def app_transaction(database: Database, context: Context | None) -> Generator[psycopg.Connection]:
    """A transaction as `sibillo_app` with the given request context, rolled back at the end."""
    with database.app() as conn:
        if context is not None:
            conn.execute(
                "SELECT set_config('app.tenant_id', %s, true), set_config('app.user_id', %s, true),"
                " set_config('app.role', %s, true), set_config('app.instance_admin', %s, true)",
                (str(context.tenant_id), str(context.user_id), context.role, str(context.instance_admin).lower()),
            )
        try:
            yield conn
        finally:
            conn.rollback()
