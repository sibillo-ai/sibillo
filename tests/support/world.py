"""Test data: two tenants and their users, each user with one row in every private table.

Rows are arranged as superuser, which bypasses row-level security, with the
columns of specs/contracts/database.md. Every call creates fresh identifiers,
so tests never share data.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import psycopg
from psycopg.types.json import Jsonb

from tests.support.database import PRIVATE_TABLES, Database, uuid7

# A serialized Pydantic AI user message; its content does not matter here.
MESSAGE = {"kind": "request", "parts": [{"part_kind": "user-prompt", "content": "hello"}]}
# An Argon2id encoded hash; no password matches it.
ARGON2_HASH = "$argon2id$v=19$m=65536,t=3,p=4$c2FsdA$aGFzaA"
# Primary key columns of each private table.
KEY_COLUMNS: dict[str, tuple[str, ...]] = {
    "device_sessions": ("id",),
    "passkey_challenges": ("id",),
    "folders": ("id",),
    "user_settings": ("owner_id",),
    "memory_items": ("id",),
    "skills": ("id",),
    "skill_files": ("skill_id", "path"),
    "conversations": ("id",),
    "conversation_plans": ("conversation_id",),
    "compaction_checkpoints": ("run_id",),
    "runs": ("id",),
    "conversation_messages": ("run_id", "seq"),
    "usage_ledger": ("id",),
    "audit_events": ("id",),
    "mcp_credentials": ("id",),
    "mcp_sign_ins": ("id",),
    "notification_subscriptions": ("device_session_id",),
    "run_followers": ("id",),
    "tasks": ("id",),
    "task_grants": ("id",),
    "task_triggers": ("id",),
    "task_firings": ("id",),
}


@dataclass(frozen=True)
class User:
    id: uuid.UUID
    tenant_id: uuid.UUID
    username: str
    role: str
    # Hash of the token of the user's device session.
    token_hash: bytes
    conversation_id: uuid.UUID
    run_id: uuid.UUID
    # A remote MCP server of the user's tenant, which their credential and sign-in are for (ADR-0099).
    mcp_server_id: uuid.UUID
    # Primary key value of the user's row in each private table, as a tuple.
    rows: dict[str, tuple[object, ...]]


@dataclass(frozen=True)
class World:
    tenant_a: uuid.UUID
    tenant_b: uuid.UUID
    alice: User  # member of tenant A
    anna: User  # tenant admin of tenant A
    bob: User  # member of tenant B

    def users(self) -> tuple[User, ...]:
        return (self.alice, self.anna, self.bob)


def create_tenant(conn: psycopg.Connection) -> uuid.UUID:
    tenant_id = uuid7()
    conn.execute(
        "INSERT INTO tenants (id, name, created_at) VALUES (%s, %s, now())",
        (tenant_id, f"tenant-{tenant_id}"),
    )
    return tenant_id


def create_user(conn: psycopg.Connection, tenant_id: uuid.UUID, role: str) -> User:
    (
        user_id,
        conversation_id,
        run_id,
        session_id,
        ledger_id,
        folder_id,
        audit_id,
        challenge_id,
        passkey_id,
        memory_id,
        skill_id,
        mcp_server_id,
        credential_id,
        sign_in_id,
        follower_id,
        task_id,
        grant_id,
        trigger_id,
        firing_id,
    ) = (uuid7() for _ in range(19))
    username, token_hash = f"user-{user_id}", user_id.bytes * 2
    conn.execute(
        "INSERT INTO users (id, tenant_id, username, display_name, password_hash, role, instance_admin, created_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, false, now())",
        (user_id, tenant_id, username, "Test user", ARGON2_HASH, role),
    )
    conn.execute(
        "INSERT INTO device_sessions (id, tenant_id, user_id, token_hash, device_name, created_at, last_used_at,"
        " expires_at) VALUES (%s, %s, %s, %s, %s, now(), now(), now() + interval '1 day')",
        (session_id, tenant_id, user_id, token_hash, "test device"),
    )
    conn.execute(
        "INSERT INTO passkeys (id, tenant_id, user_id, credential_id, public_key, sign_count, name, created_at)"
        " VALUES (%s, %s, %s, %s, %s, 0, 'Test passkey', now())",
        (passkey_id, tenant_id, user_id, user_id.bytes, b"test key"),
    )
    conn.execute(
        "INSERT INTO passkey_challenges (id, tenant_id, user_id, purpose, token_hash, challenge, created_at,"
        " expires_at) VALUES (%s, %s, %s, 'sign_in', %s, %s, now(), now() + interval '5 minutes')",
        (challenge_id, tenant_id, user_id, challenge_id.bytes * 2, challenge_id.bytes * 2),
    )
    conn.execute(
        "INSERT INTO folders (id, tenant_id, owner_id, name, created_at, updated_at)"
        " VALUES (%s, %s, %s, %s, now(), now())",
        (folder_id, tenant_id, user_id, "Test folder"),
    )
    conn.execute(
        "INSERT INTO user_settings (tenant_id, owner_id, additional_instructions, updated_at)"
        " VALUES (%s, %s, %s, now())",
        (tenant_id, user_id, "Test instructions"),
    )
    conn.execute(
        "INSERT INTO memory_items (id, tenant_id, owner_id, text, origin, untrusted, created_at, updated_at)"
        " VALUES (%s, %s, %s, %s, 'user', false, now(), now())",
        (memory_id, tenant_id, user_id, "Test memory item"),
    )
    conn.execute(
        "INSERT INTO skills (id, tenant_id, owner_id, name, description, origin, untrusted, size_bytes,"
        " created_at, updated_at) VALUES (%s, %s, %s, %s, 'A test skill.', 'user', false, 4, now(), now())",
        (skill_id, tenant_id, user_id, f"test-{skill_id.hex[:8]}"),
    )
    conn.execute(
        "INSERT INTO skill_files (skill_id, tenant_id, owner_id, path, content) VALUES (%s, %s, %s, 'SKILL.md', %s)",
        (skill_id, tenant_id, user_id, b"test"),
    )
    conn.execute(
        "INSERT INTO conversations (id, tenant_id, owner_id, title, folder_id, last_message_at, created_at, updated_at)"
        " VALUES (%s, %s, %s, %s, %s, now(), now(), now())",
        (conversation_id, tenant_id, user_id, "Test conversation", folder_id),
    )
    conn.execute(
        "INSERT INTO conversation_plans (conversation_id, tenant_id, owner_id, items, updated_at)"
        " VALUES (%s, %s, %s, %s, now())",
        (conversation_id, tenant_id, user_id, Jsonb([{"id": "a", "content": "Test step", "status": "pending"}])),
    )
    conn.execute(
        "INSERT INTO runs (id, tenant_id, owner_id, conversation_id, parent_run_id, kind, status, created_at)"
        " VALUES (%s, %s, %s, %s, NULL, 'message', 'completed', now())",
        (run_id, tenant_id, user_id, conversation_id),
    )
    conn.execute(
        "INSERT INTO conversation_messages (run_id, seq, tenant_id, owner_id, conversation_id, message, created_at)"
        " VALUES (%s, 1, %s, %s, %s, %s, now())",
        (run_id, tenant_id, user_id, conversation_id, Jsonb(MESSAGE)),
    )
    conn.execute(
        "INSERT INTO compaction_checkpoints (run_id, tenant_id, owner_id, conversation_id, messages, created_at)"
        " VALUES (%s, %s, %s, %s, %s, now())",
        (run_id, tenant_id, user_id, conversation_id, Jsonb([MESSAGE])),
    )
    conn.execute(
        "INSERT INTO usage_ledger (id, tenant_id, owner_id, conversation_id, run_id, purpose, provider, model,"
        " price_source, created_at) VALUES (%s, %s, %s, %s, %s, 'run', 'test', 'test-model', 'free', now())",
        (ledger_id, tenant_id, user_id, conversation_id, run_id),
    )
    conn.execute(
        "INSERT INTO tool_permissions (tenant_id, user_id, subject_kind, subject, setting, updated_at)"
        " VALUES (%s, %s, 'tool', 'web_search', 'ask', now())",
        (tenant_id, user_id),
    )
    # World tenants have no connections, so the policy changes nothing they do.
    conn.execute(
        "INSERT INTO egress_policies (tenant_id, user_id, set_by, policy, updated_at)"
        " VALUES (%s, %s, 'user', 'local_only', now())",
        (tenant_id, user_id),
    )
    conn.execute(
        "INSERT INTO audit_events (id, tenant_id, owner_id, conversation_id, run_id, tool_call_id, tool, outcome,"
        " created_at) VALUES (%s, %s, %s, %s, %s, 'call-1', 'web_search', 'not_needed', now())",
        (audit_id, tenant_id, user_id, conversation_id, run_id),
    )
    # A server of the tenant, with one tool, for the user's credential and sign-in (AGT-030, AGT-031).
    conn.execute(
        "INSERT INTO mcp_servers (id, tenant_id, name, prefix, url, auth, generation, private_network, enabled,"
        " created_at, updated_at) VALUES (%s, %s, %s, %s, 'https://mcp.example/mcp', 'token', %s, false, true,"
        " now(), now())",
        (mcp_server_id, tenant_id, f"Server {mcp_server_id}", f"w{mcp_server_id.hex[-8:]}", mcp_server_id),
    )
    conn.execute(
        "INSERT INTO mcp_server_tools (tenant_id, server_id, name, listed) VALUES (%s, %s, 'turn_on', %s)",
        (tenant_id, mcp_server_id, Jsonb({"title": None, "description": "x", "inputSchema": {}, "annotations": None})),
    )
    conn.execute(
        "INSERT INTO mcp_credentials (id, tenant_id, owner_id, server_id, server_generation, kind,"
        " access_token_ciphertext, status, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, 'token', %s, 'valid',"
        " now(), now())",
        (credential_id, tenant_id, user_id, mcp_server_id, mcp_server_id, b"ciphertext"),
    )
    conn.execute(
        "INSERT INTO mcp_sign_ins (id, tenant_id, owner_id, server_id, server_generation, state_hash, code_verifier,"
        " created_at, expires_at) VALUES (%s, %s, %s, %s, %s, %s, 'verifier', now(), now() + interval '10 minutes')",
        (sign_in_id, tenant_id, user_id, mcp_server_id, mcp_server_id, sign_in_id.bytes * 2),
    )
    # The device session's notification subscription, and a stream that follows the run (UX-004, ADR-0101).
    conn.execute(
        "INSERT INTO notification_subscriptions (tenant_id, owner_id, device_session_id, endpoint, p256dh, auth,"
        " created_at) VALUES (%s, %s, %s, %s, 'p256dh', 'auth', now())",
        (tenant_id, user_id, session_id, f"https://fcm.googleapis.com/fcm/send/{session_id}"),
    )
    conn.execute(
        "INSERT INTO run_followers (id, tenant_id, owner_id, run_id, seen_at) VALUES (%s, %s, %s, %s, now())",
        (follower_id, tenant_id, user_id, run_id),
    )
    # A task with a grant and a schedule, which fired once and started the user's conversation (ADR-0106).
    conn.execute(
        "INSERT INTO tasks (id, tenant_id, owner_id, name, instructions, time_zone, created_at, updated_at)"
        " VALUES (%s, %s, %s, 'Test task', 'Say hello.', 'Europe/Rome', now(), now())",
        (task_id, tenant_id, user_id),
    )
    conn.execute(
        "INSERT INTO task_grants (id, tenant_id, owner_id, task_id, tool, created_at)"
        " VALUES (%s, %s, %s, %s, 'web_search', now())",
        (grant_id, tenant_id, user_id, task_id),
    )
    conn.execute(
        "INSERT INTO task_triggers (id, tenant_id, owner_id, task_id, kind, schedule_start, recurrence, next_fire_at,"
        " created_at)"
        " VALUES (%s, %s, %s, %s, 'schedule', '2026-01-01 07:00', '{RRULE:FREQ=DAILY}',"
        " now() + interval '1 day', now())",
        (trigger_id, tenant_id, user_id, task_id),
    )
    conn.execute(
        "INSERT INTO task_firings (id, tenant_id, owner_id, task_id, trigger_id, trigger_kind, fire_key, status,"
        " conversation_id, created_at, started_at, finished_at) VALUES (%s, %s, %s, %s, %s, 'schedule', %s, 'done',"
        " %s, now(), now(), now())",
        (firing_id, tenant_id, user_id, task_id, trigger_id, f"{trigger_id}:fired", conversation_id),
    )
    rows: dict[str, tuple[object, ...]] = {
        "device_sessions": (session_id,),
        "passkey_challenges": (challenge_id,),
        "folders": (folder_id,),
        "user_settings": (user_id,),
        "memory_items": (memory_id,),
        "skills": (skill_id,),
        "skill_files": (skill_id, "SKILL.md"),
        "conversations": (conversation_id,),
        "conversation_plans": (conversation_id,),
        "compaction_checkpoints": (run_id,),
        "runs": (run_id,),
        "conversation_messages": (run_id, 1),
        "usage_ledger": (ledger_id,),
        "audit_events": (audit_id,),
        "mcp_credentials": (credential_id,),
        "mcp_sign_ins": (sign_in_id,),
        "notification_subscriptions": (session_id,),
        "run_followers": (follower_id,),
        "tasks": (task_id,),
        "task_grants": (grant_id,),
        "task_triggers": (trigger_id,),
        "task_firings": (firing_id,),
    }
    assert set(rows) == set(PRIVATE_TABLES)
    return User(user_id, tenant_id, username, role, token_hash, conversation_id, run_id, mcp_server_id, rows)


def disable_user(database: Database, user: User) -> None:
    """Mark a user disabled, as a tenant admin would."""
    with database.superuser() as conn:
        # Triggers enforce the application's rules on changes to users, and
        # arranging data is not subject to them.
        conn.execute("SET session_replication_role = replica")
        conn.execute("UPDATE users SET disabled_at = now() WHERE id = %s", (user.id,))


def create_world(database: Database) -> World:
    with database.superuser() as conn:
        tenant_a, tenant_b = create_tenant(conn), create_tenant(conn)
        return World(
            tenant_a=tenant_a,
            tenant_b=tenant_b,
            alice=create_user(conn, tenant_a, "member"),
            anna=create_user(conn, tenant_a, "tenant_admin"),
            bob=create_user(conn, tenant_b, "member"),
        )
