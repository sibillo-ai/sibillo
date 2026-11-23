# Database contract

The PostgreSQL schema for phase 0. The schema is a contract (ADR-0003): it
changes only through `spec/*` pull requests, and migrations in `migrations/`
implement it. Background: ADR-0009, ADR-0025, ADR-0031, ADR-0033, ADR-0034,
ADR-0037, ADR-0042, ADR-0046, ADR-0047, ADR-0048, ADR-0049, ADR-0051,
ADR-0052, ADR-0068, ADR-0069, ADR-0071, ADR-0073, ADR-0094, ADR-0099, ADR-0100,
ADR-0106.

## Roles

| Role | Used by | Properties |
|---|---|---|
| `sibillo_owner` | Migrations, and the pre-authentication functions it owns | Owns every table and function. Never used by running services to connect. |
| `sibillo_app` | API and worker | `NOSUPERUSER`, `NOBYPASSRLS`, `NOCREATEDB`, `NOCREATEROLE`; owns nothing; granted only the privileges listed below (TEN-004). |

Every table below has row-level security **enabled and forced** (TEN-003),
including tables that are not tenant-scoped, so that no table is readable by
`sibillo_app` without an explicit policy. Forced row-level security applies to the
table owner too: `sibillo_owner` reaches rows only through the owner policies of
the pre-authentication functions. The policies of each table below are
created `TO sibillo_app`.

## Initialization

The schema targets PostgreSQL 17. Roles and the database are created once per
instance, before any migration, by a superuser: by the deployment's database
initialization and by the test harness ([test-harness.md](test-harness.md)).
Migrations never create roles, and the superuser is not used afterwards.

```sql
CREATE ROLE sibillo_owner LOGIN PASSWORD '...'
  NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
CREATE ROLE sibillo_app LOGIN PASSWORD '...'
  NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOINHERIT;
CREATE DATABASE sibillo OWNER sibillo_owner;
REVOKE ALL ON DATABASE sibillo FROM PUBLIC;
GRANT CONNECT ON DATABASE sibillo TO sibillo_app;
```

Migrations, run as `sibillo_owner`, create every schema object and grant
`sibillo_app` exactly the privileges this contract lists.

## Request context

At the start of every transaction, after authentication, the server sets
transaction-local settings derived only from the authenticated identity
(TEN-005):

| Setting | Value |
|---|---|
| `app.tenant_id` | Tenant of the authenticated user (UUID) |
| `app.user_id` | Authenticated user (UUID) |
| `app.role` | `member` or `tenant_admin` |
| `app.instance_admin` | `true` or `false` |

They are set with `set_config(name, value, true)`, so they vanish at the end
of the transaction. Policies read them with `current_setting(name, true)`;
when a setting is missing, the comparison is `NULL` and the policy denies
access.

Helper functions used in the policies below, all `STABLE`:

```sql
app_tenant_id()      -> current_setting('app.tenant_id', true)::uuid
app_user_id()        -> current_setting('app.user_id', true)::uuid
app_is_tenant_admin() -> current_setting('app.role', true) = 'tenant_admin'
app_is_instance_admin() -> current_setting('app.instance_admin', true) = 'true'
```

## Pre-authentication functions

Login and token verification happen before any context exists. Instead of
weakening policies, `sibillo_app` may call exactly these `SECURITY DEFINER`
functions, owned by `sibillo_owner`, with a fixed `search_path`. They return the
minimum needed and nothing else.

| Function | Returns | Purpose |
|---|---|---|
| `auth_find_login(username text)` | `user_id, tenant_id, password_hash, role, instance_admin, disabled` | Password verification (AUTH-001); matches the username ignoring case |
| `auth_find_session(token_hash bytea)` | `session_id, user_id, tenant_id, role, instance_admin, password_change_required, expires_at, revoked` | Token verification on every request (AUTH-004); no row for a session of a disabled account (AUTH-009, ADR-0105) |
| `auth_touch_session(session_id uuid)` | — | Sets `last_used_at` to now and `expires_at` to 90 days later, for a session that is neither revoked nor expired (ADR-0049) |
| `auth_record_login_attempt(username text, source inet, success boolean)` | `allowed boolean, retry_after_seconds integer` | Rate limiting (AUTH-006), by the rules below |
| `auth_check_login_attempt(username text, source inet)` | `allowed boolean, retry_after_seconds integer` | Whether an attempt would be refused now, by the same rules, recording and deleting nothing; called before a password is checked (AUTH-006, ADR-0118) |
| `default_model_configured()` | `boolean` | Whether any tenant has a default model, for `/health` before any sign-in (OPS-002, ADR-0054, ADR-0069) |
| `expired_temporary_conversations(hours integer)` | `conversation_id, tenant_id, owner_id` for every temporary conversation whose `updated_at` is more than `hours` hours ago and that has no `queued` or `running` run | Deletion of temporary conversations (CNV-011, ADR-0082): only identifiers, so the worker can delete each one under its owner's request context |
| `expired_approvals()` | `conversation_id, tenant_id, owner_id` for every conversation whose `approvals_expire_at` has passed and that has no `queued` or `running` run | Expiry of approval requests (AGT-007, ADR-0090): only identifiers, so the worker can deny them under the owner's request context |
| `abandoned_runs(hours integer)` | `run_id, tenant_id, owner_id` for every run `queued` or `running` created more than `hours` hours ago, or cancelled without `finished_at` that long ago | Failing runs a crash left active, so that backups and the conversation go on (OPS-006, ADR-0130): only identifiers, so the worker fails each under its owner's request context |
| `retention_expired_runs(days integer)` | `run_id` for every run whose `finished_at` is more than `days` days ago | Retention of durable workflows (TEN-009, ADR-0052): only identifiers, so the worker can delete their workflows across tenants |
| `auth_take_sign_in(token_hash bytea)` | `user_id, tenant_id, username, role, instance_admin, disabled, challenge, expires_at`, or no row | The passkey step of a sign-in (AUTH-010, ADR-0094): deletes the `sign_in` challenge with that token hash and returns it with its user, so that a token is used once whatever the outcome; also deletes every expired challenge |
| `due_task_triggers()` | `trigger_id, task_id, tenant_id, owner_id, work` for every trigger with work due, of a task that is not paused and whose owner's account is not disabled: `fire` for a schedule whose `next_fire_at` has passed, `poll` for an `mcp_event` trigger polled whose `next_poll_at` has passed, `renew` for an `mcp_event` trigger delivered by webhook whose `refresh_before` is less than 10 minutes away | Firing schedules and following event subscriptions (TSK-003, TSK-008, ADR-0106): only identifiers, so the worker does the work under the owner's request context |
| `waiting_task_firings()` | `firing_id, task_id, tenant_id, owner_id` for the oldest `waiting` firing of every task that has no `running` firing and whose owner's account is not disabled | Starting firings that wait their turn (TSK-009), as a sweep behind the worker's own start of the next firing when one ends |
| `find_webhook_trigger(token_hash bytea)` | `trigger_id, task_id, tenant_id, owner_id, paused`, or no row | A request to a webhook trigger (TSK-007): the trigger whose `token_hash` it is, of a user whose account is not disabled |
| `find_event_subscription(trigger_id uuid)` | `task_id, tenant_id, owner_id, paused, secret_ciphertext`, or no row | A delivery of MCP events by webhook (TSK-008): the `mcp_event` trigger delivered by webhook with that ID, of a user whose account is not disabled, with its encrypted secret to check the signature |
| `bootstrap_instance(tenant_name text, username text, display_name text, password_hash text)` | `tenant_id, user_id` | Creates the first tenant and its first user, who is instance admin and tenant admin; fails if any user exists (AUTH-007). Executable only by `sibillo_owner`, run by the setup command |
| `remove_passkeys(username text)` | `integer`, the number removed | Deletes every passkey of the user with that username, ignoring case, and fails when there is none such user (AUTH-010, ADR-0094). Executable only by `sibillo_owner`, run by the `remove-passkeys` command |

Rate limiting (ADR-0047): `auth_record_login_attempt` is called once per
login attempt, after the password is verified, with its outcome. It counts
the failed attempts recorded in the 15 minutes before the call. The attempt
is refused when 5 of them are for the same username, ignoring case, or 20 are
from the same source address. A refused attempt is not recorded, and the
server answers it the same whether or not the password was right; an allowed
attempt is recorded with its outcome. When refused, `retry_after_seconds` is
the time, rounded up to whole seconds, until the oldest failure counted toward
a reached limit leaves the window (the longer, when both are reached); when
allowed, it is 0. Each call deletes attempts older than the window.

Before verifying a password, the server calls `auth_check_login_attempt`
with the same username and source. It answers as `auth_record_login_attempt`
would for that attempt, but records and deletes nothing. When it refuses,
the password is not verified and the attempt is answered as refused
(ADR-0118).

The passkey step of a sign-in calls `auth_record_login_attempt` too, after
`auth_take_sign_in` and the check of the assertion, with the sign-in's
username, or an empty username when the token is unknown, so that it counts
only for the source address. Checking the password to register or remove a
passkey calls it with the user's own username (ADR-0094).

These functions run as `sibillo_owner`, which forced row-level security does not
exempt. They work through **owner policies**, created `TO sibillo_owner`, and
these are the only policies for that role:

| Table | Operations for `sibillo_owner` | Used by |
|---|---|---|
| `tenants` | `SELECT`, `INSERT` | `bootstrap_instance` |
| `users` | `SELECT`, `INSERT` | `auth_find_login`, `auth_find_session`, `auth_take_sign_in`, `bootstrap_instance`, `remove_passkeys`, and the task functions, for the account's state |
| `device_sessions` | `SELECT`, `UPDATE` | `auth_find_session`, `auth_touch_session`, `revoke_sessions_of_disabled_user` |
| `login_attempts` | `SELECT`, `INSERT`, `DELETE` | `auth_record_login_attempt`, which also deletes rows older than the rate-limit window, and `auth_check_login_attempt`, which only reads |
| `passkey_challenges` | `SELECT`, `DELETE` | `auth_take_sign_in` |
| `passkeys` | `SELECT`, `DELETE` | `remove_passkeys` |
| `runs` | `SELECT` | `retention_expired_runs`, `expired_temporary_conversations`, `expired_approvals` |
| `conversations` | `SELECT` | `expired_temporary_conversations`, `expired_approvals` |
| `connections` | `SELECT` | `default_model_configured` |
| `tasks` | `SELECT` | `due_task_triggers`, `waiting_task_firings`, `find_webhook_trigger`, `find_event_subscription` |
| `task_triggers` | `SELECT` | `due_task_triggers`, `find_webhook_trigger`, `find_event_subscription` |
| `task_firings` | `SELECT` | `waiting_task_firings` |

A webhook trigger's token, and a delivery's signature with its
subscription's secret, authenticate a request as that trigger: once
`find_webhook_trigger` or `find_event_subscription` found it, the API sets the
request context of the task's owner, with the role `member`, to record the
firing (or count it as skipped), and does nothing else under it (ADR-0106).

Owner policies have no condition (`USING (true)`): `sibillo_owner` is never used
by running services, so they open these tables only to the code of the
`SECURITY DEFINER` functions of this contract and to migrations.

## Tables

Conventions: identifiers are `uuid` (version 7); timestamps are
`timestamptz`; every foreign key to a tenant-scoped row also includes
`tenant_id`, so that a row can never reference another tenant's data; every
foreign key from a private table to another private table also includes the
owner column, so that a row can never be attached to another user's data. A
foreign key that sets null on delete lists the column it sets
(`ON DELETE SET NULL (column)`), so that the tenant and owner columns keep
their values.

### `tenants`

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | primary key |
| `name` | text | not null, unique |
| `created_at` | timestamptz | not null |

Policies: `SELECT` where `id = app_tenant_id()` or `app_is_instance_admin()`;
`INSERT` when `app_is_instance_admin()`. No `UPDATE` or `DELETE` in phase 0.

### `users`

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | primary key |
| `tenant_id` | uuid | not null, references `tenants` |
| `username` | text | not null, unique across the instance ignoring case |
| `display_name` | text | not null |
| `password_hash` | text | not null; Argon2id encoded hash (AUTH-001) |
| `role` | text | `member` or `tenant_admin` |
| `instance_admin` | boolean | not null, default false |
| `created_at` | timestamptz | not null |
| `disabled_at` | timestamptz | null while active |
| `password_change_required` | boolean | not null, default false; true while the password is an initial password (AUTH-012, ADR-0105) |

Policies:
- `SELECT` where `tenant_id = app_tenant_id()`.
- `INSERT` where `password_change_required` and ((`tenant_id =
  app_tenant_id()` and `app_is_tenant_admin()` and not `instance_admin`) or
  `app_is_instance_admin()`) (to create a new tenant's first admin). Only an
  instance admin creates instance admins (AUTH-008). Every account created
  through the application has an initial password (AUTH-012).
- `UPDATE` where `tenant_id = app_tenant_id()` and (`id = app_user_id()` or
  `app_is_tenant_admin()`).

Column privileges: `sibillo_app` cannot `SELECT` `password_hash`; only
`auth_find_login` reads it. `sibillo_app` may `UPDATE` only `display_name`,
`password_hash`, `password_change_required`, `role` and `disabled_at`;
identifiers, `username` and `instance_admin` never change through the
application.

Changing `role` or `disabled_at` requires `app_is_tenant_admin()`, so that
users cannot promote themselves or re-enable their account, and of an
instance admin's row also `app_is_instance_admin()` (AUTH-008). Changing
`password_hash` or `password_change_required` requires `id = app_user_id()`,
so that only the user changes their password, and `password_change_required`
never changes from false to true (AUTH-011, AUTH-012, ADR-0105). Row-level
security cannot compare a row's old and new values, so a `BEFORE UPDATE`
trigger on `users` enforces these rules.

Disabling an account revokes its sessions (AUTH-009, ADR-0048). When
`disabled_at` changes from null to a value, an `AFTER UPDATE` trigger on
`users` sets `revoked_at` to the current time on every session of that user
that is not yet revoked, in the same transaction. Its function,
`revoke_sessions_of_disabled_user()`, is `SECURITY DEFINER`, owned by
`sibillo_owner`, with a fixed `search_path`, and not executable by `sibillo_app`; it
changes `device_sessions` through the owner policies. Re-enabling an account
leaves its sessions revoked.

### `device_sessions` (private)

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | primary key |
| `tenant_id` | uuid | not null |
| `user_id` | uuid | not null; (`tenant_id`, `user_id`) references `users` |
| `token_hash` | bytea | not null, unique; SHA-256 of the token (AUTH-004) |
| `device_name` | text | not null |
| `created_at` | timestamptz | not null |
| `last_used_at` | timestamptz | not null |
| `expires_at` | timestamptz | not null; 90 days after the last use (ADR-0049) |
| `revoked_at` | timestamptz | null while valid |

Policies: all operations where `tenant_id = app_tenant_id()` and
`user_id = app_user_id()`. `INSERT` at login happens after the context is set
from the verified credentials.

### `notification_subscriptions` (private)

The Web Push subscription of a device session (UX-004, ADR-0101).

| Column | Type | Notes |
|---|---|---|
| `tenant_id`, `owner_id` | uuid | not null; (`tenant_id`, `owner_id`) references `users` |
| `device_session_id` | uuid | primary key; (`tenant_id`, `owner_id`, `device_session_id`) references `device_sessions` (`tenant_id`, `user_id`, `id`) on delete cascade |
| `endpoint` | text | not null; an `https` URL on a push service of ADR-0101 |
| `p256dh` | text | not null; the browser's public key, base64url |
| `auth` | text | not null; the browser's authentication secret, base64url |
| `created_at` | timestamptz | not null |

A subscription is used only while its device session is valid (ADR-0101).

### `login_attempts`

| Column | Type | Notes |
|---|---|---|
| `id` | bigint | identity |
| `username` | text | as submitted; compared ignoring case |
| `source` | inet | client address |
| `success` | boolean | not null |
| `created_at` | timestamptz | not null |

No policies for `sibillo_app`: accessed only through
`auth_record_login_attempt`. Rows older than the rate-limit window are deleted.

### `passkeys`

The passkeys of each user (AUTH-010, ADR-0094).

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | primary key |
| `tenant_id`, `user_id` | uuid | not null; (`tenant_id`, `user_id`) references `users` on delete cascade |
| `credential_id` | bytea | not null, unique across the instance |
| `public_key` | bytea | not null; the COSE public key |
| `sign_count` | bigint | not null; the last signature counter |
| `transports` | text[] | not null, default empty; as the device reported them |
| `name` | text | not null; given by the user, 1 to 100 characters |
| `created_at` | timestamptz | not null |
| `last_used_at` | timestamptz | null until the first sign-in with it |

Policies:
- `SELECT`, `DELETE` where `tenant_id = app_tenant_id()` and (`user_id =
  app_user_id()` or `app_is_tenant_admin()`): tenant admins count and remove
  a user's passkeys.
- `INSERT`, `UPDATE` where `tenant_id = app_tenant_id()` and `user_id =
  app_user_id()`. The passkey step of a sign-in sets the request context
  from the sign-in's user before reading the passkeys and updating
  `sign_count` and `last_used_at`.

### `passkey_challenges` (private)

WebAuthn challenges waiting for their answer, each valid for 5 minutes and
deleted when used (ADR-0094).

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | primary key |
| `tenant_id`, `user_id` | uuid | not null; (`tenant_id`, `user_id`) references `users` on delete cascade |
| `purpose` | text | `sign_in` or `registration` |
| `token_hash` | bytea | SHA-256 of the sign-in token; unique; not null exactly when `purpose` is `sign_in` |
| `challenge` | bytea | not null; 32 random bytes |
| `created_at` | timestamptz | not null |
| `expires_at` | timestamptz | not null; 5 minutes after `created_at` |

The `sign_in` row is inserted after the password is verified, with the
request context set from the verified credentials, like a device session.

### `folders` (private)

A user's groups of conversations (CNV-007, ADR-0073).

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | primary key |
| `tenant_id`, `owner_id` | uuid | not null; (`tenant_id`, `owner_id`) references `users` |
| `name` | text | not null |
| `pinned_at` | timestamptz | when it was pinned; null when not pinned |
| `collapsed` | boolean | not null, default false |
| `created_at`, `updated_at` | timestamptz | not null |

### `conversations` (private)

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | primary key; also Pydantic AI's `conversation_id` (ADR-0031) |
| `tenant_id` | uuid | not null |
| `owner_id` | uuid | not null; (`tenant_id`, `owner_id`) references `users` |
| `title` | text | not null; empty while untitled (ADR-0052), then named by its user or by its model (CNV-006); searched through a GIN index on its `simple` tsvector (CNV-009) |
| `active_run_id` | uuid | the last run of the active path (ADR-0037); null before the first run; (`tenant_id`, `owner_id`, `active_run_id`) references `runs` on delete set null (`active_run_id`) |
| `usage` | jsonb | Pydantic AI conversation usage |
| `pending_interrupts` | jsonb | serialized `DeferredToolRequests` while an interrupt is pending: questions to the user, and approvals (ADR-0033, ADR-0083), with, for each approval, what the server showed the user: its reason and the scopes it offered (ADR-0090), and, for a request for internet access, the calls that wait for it (AGT-034, ADR-0113); else null |
| `approvals_expire_at` | timestamptz | 24 hours after the interrupt was stored while approvals are pending (AGT-007, ADR-0090); null when none is, also while questions alone are pending; indexed for the expiry job |
| `allowed_internet_access` | boolean | not null, default false; the conversation has internet access (AGT-034, ADR-0113): the web tools run and its sandbox has network; set when a resume answers a request for internet access with scope `conversation`, or when its user turns it on, at creation too (ADR-0115); cleared when its user withdraws it; not copied into a fork. Replaces `allowed_web_and_commands`, whose values it takes |
| `leftovers_untrusted` | boolean | not null, default false; a rewind deleted a run holding untrusted content, so the conversation's task list and workspace may carry it: every later run has untrusted content from its start (CNV-004, ADR-0123); set on a fork whose conversation is marked or has runs holding untrusted content (CNV-005); never cleared |
| `allowed_tools` | text[] | not null, default empty; the tools whose approval is lifted in this conversation (AGT-006), set the same way; not copied into a fork |
| `folder_id` | uuid | its folder, or null; (`tenant_id`, `owner_id`, `folder_id`) references `folders` on delete set null (`folder_id`) |
| `pinned_at` | timestamptz | when it was pinned; null when not pinned (CNV-008) |
| `forked_from_conversation_id`, `forked_from_run_id` | uuid | where a fork came from (CNV-005); (`tenant_id`, `owner_id`, `forked_from_conversation_id`) references `conversations` on delete set null (`forked_from_conversation_id`); the run is kept as an identifier, without a reference, so that a fork stays one when its original is gone |
| `last_message_at` | timestamptz | not null; its creation, then the time a run last added messages; the list's order (CNV-008) |
| `connection_id`, `model` | uuid, text | the model of the conversation (MOD-012): set from the tenant's default model on creation, or chosen by its user; both null when the tenant had no default model; (`tenant_id`, `connection_id`) references `connections` on delete set null (`connection_id`), so a removed connection leaves `model` without a connection and runs fail |
| `reasoning` | text | not null, default `on`; `off`, `on` or `deep` (CNV-013, ADR-0081) |
| `disabled_tools` | text[] | not null, default empty; the tools that are off, each one of the names of `ToolName` in the API contract (CNV-013, ADR-0087) |
| `disabled_skills` | text[] | not null, default empty; the names of skills turned off in this conversation, built-in or the user's (AGT-017, ADR-0096); not copied from the user's settings, so that a skill turned on or added later is on; a name of no skill is ignored; copied into a fork |
| `disabled_servers` | uuid[] | not null, default empty; the remote MCP servers that are off (AGT-029, ADR-0099), without a reference: an ID of no server is ignored; copied from the user's settings on creation, and into a fork |
| `base_instructions`, `additional_instructions` | text | the conversation's own instructions; null to use the user's defaults (CNV-014) |
| `temporary` | boolean | not null, default false; set on creation and never changed (CNV-011, ADR-0082) |
| `task_id` | uuid | the task whose firing started it (TSK-002, ADR-0106); (`tenant_id`, `owner_id`, `task_id`) references `tasks` on delete set null (`task_id`); indexed; never set otherwise, and not copied into a fork |
| `task_name` | text | the task's name when it started the conversation, kept once the task is deleted; null when `task_id` was never set |
| `archived_at` | timestamptz | null when active |
| `created_at` | timestamptz | not null |
| `updated_at` | timestamptz | not null; updated when a run adds messages |

### `conversation_plans` (private)

The task list of a conversation (UX-009, ADR-0083); at most one row per
conversation, and none until the assistant writes one.

| Column | Type | Notes |
|---|---|---|
| `conversation_id` | uuid | primary key; (`tenant_id`, `owner_id`, `conversation_id`) references `conversations` on delete cascade |
| `tenant_id`, `owner_id` | uuid | not null |
| `items` | jsonb | not null; the steps, in order, each `{id, content, status, active_form}` as `Planning` writes them |
| `updated_at` | timestamptz | not null |

### `user_settings` (private)

A user's defaults for their conversations (CNV-013, CNV-014, ADR-0081); at
most one row per user, and none until they set one.

| Column | Type | Notes |
|---|---|---|
| `tenant_id`, `owner_id` | uuid | not null; primary key; (`tenant_id`, `owner_id`) references `users` |
| `connection_id`, `model` | uuid, text | the default model, both null when none; (`tenant_id`, `connection_id`) references `connections` on delete set null (`connection_id`), and a model without a connection is not offered |
| `reasoning` | text | `off`, `on` or `deep`; null when unset |
| `disabled_tools` | text[] | not null, default empty; as in `conversations` |
| `disabled_servers` | uuid[] | not null, default empty; as in `conversations` |
| `base_instructions`, `additional_instructions` | text | null when unset |
| `language` | text | the preferred language, a BCP 47 language tag of at most 35 characters that matches `^[a-z]{2,3}(-[A-Z][a-z]{3})?(-([A-Z]{2}|[0-9]{3}))?$`; null when unset (I18N-003, ADR-0103) |
| `memory_enabled` | boolean | not null, default true; whether memory is on for the user (MEM-006, ADR-0095); a user without a row has it on |
| `disabled_builtin_skills` | text[] | not null, default empty; the built-in skills the user turned off (AGT-024, ADR-0096) |
| `updated_at` | timestamptz | not null |

### `memory_items` (private)

A user's memory: the only copy of what the assistant remembers about them
(MEM-001 to MEM-008, ADR-0095).

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | primary key |
| `tenant_id`, `owner_id` | uuid | not null; (`tenant_id`, `owner_id`) references `users` on delete cascade |
| `text` | text | not null; 1 to 500 characters, checked; a user's items hold at most 10,000 characters in all, checked by the application under a lock on the user's items |
| `origin` | text | not null; `user` when the user wrote or last saved it, `assistant` when a memory tool did |
| `untrusted` | boolean | not null; true only when a memory tool wrote it in a run with untrusted content (MEM-008); false whenever `origin` is `user`, checked |
| `conversation_id` | uuid | the conversation of the memory tool call that last wrote it; null when `origin` is `user`; an identifier without a reference, so that the item outlives its conversation |
| `created_at` | timestamptz | not null |
| `updated_at` | timestamptz | not null; when it was last written; index on (`tenant_id`, `owner_id`, `updated_at`) |

### `skills` (private)

A user's skills (AGT-017, AGT-025, ADR-0096). Built-in skills are not rows:
they come with the server's package.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | primary key |
| `tenant_id`, `owner_id` | uuid | not null; (`tenant_id`, `owner_id`) references `users` on delete cascade |
| `name` | text | not null; the name of its `SKILL.md`, by the Agent Skills rules; unique on (`tenant_id`, `owner_id`, `name`); never the name of a built-in skill, checked by the application |
| `description` | text | not null; the description of its `SKILL.md`, 1 to 1,024 characters, checked |
| `enabled` | boolean | not null, default true; whether the skill is on for the user |
| `origin` | text | not null; `user`, `upload`, `import` or `assistant`, checked |
| `source_url` | text | the URL it was imported from; not null exactly when `origin` is `import`, checked |
| `conversation_id` | uuid | the conversation of the `save_skill` call that last wrote it; not null exactly when `origin` is `assistant`, checked; an identifier without a reference, so that the skill outlives its conversation |
| `untrusted` | boolean | not null; true when uploaded, imported, or saved in a run with untrusted content, until the user marks it trusted (AGT-025) |
| `size_bytes` | bigint | not null; the sum of its files' sizes, at most 10 MiB, checked; a user's skills hold at most 100 skills and 100 MiB in all, checked by the application under a lock on the user's skills |
| `created_at` | timestamptz | not null |
| `updated_at` | timestamptz | not null; when its files last changed |

### `skill_files` (private)

The files of a user's skill, `SKILL.md` included; at most 200 per skill,
checked by the application.

| Column | Type | Notes |
|---|---|---|
| `skill_id` | uuid | not null; (`tenant_id`, `owner_id`, `skill_id`) references `skills` on delete cascade |
| `tenant_id`, `owner_id` | uuid | not null |
| `path` | text | not null; relative to the skill's folder, `/`-separated, without empty, `.` or `..` segments, at most 255 characters, checked; primary key (`skill_id`, `path`) |
| `content` | bytea | not null |
| `executable` | boolean | not null, default false; whether the sandbox sees it executable |

### `conversation_messages` (private)

The source of truth of a conversation: Pydantic AI messages, grouped by the
run that produced them (ADR-0031, ADR-0037). The history of a conversation is
the messages of its runs, from the first run, each run's messages in order.
History served to clients is a projection of these rows.

| Column | Type | Notes |
|---|---|---|
| `run_id` | uuid | (`tenant_id`, `owner_id`, `run_id`) references `runs` on delete cascade |
| `seq` | integer | position within the run, starting at 1, no gaps |
| `tenant_id`, `owner_id` | uuid | as in `conversations` |
| `conversation_id` | uuid | (`tenant_id`, `owner_id`, `conversation_id`) references `conversations` on delete cascade |
| `message` | jsonb | one `ModelMessage`, serialized with Pydantic AI's `ModelMessagesTypeAdapter`; a request is stored without its instructions, which each run builds anew (ADR-0081, ADR-0095) |
| `text` | text | not null, default empty; the text a person reads in it: the user's prompt or the assistant's answer, never tool calls or results (CNV-009) |
| `search` | tsvector | generated from `text` with the `simple` configuration, stored; GIN index (ADR-0073) |
| `created_at` | timestamptz | not null |

Primary key (`run_id`, `seq`).

### `compaction_checkpoints` (private)

The history a model receives in place of the conversation up to a run, once
it was compacted (AGT-016, ADR-0041). The stored messages never change.

| Column | Type | Notes |
|---|---|---|
| `run_id` | uuid | primary key; the run at which compaction happened; (`tenant_id`, `owner_id`, `run_id`) references `runs` on delete cascade |
| `tenant_id`, `owner_id` | uuid | as in `conversations` |
| `conversation_id` | uuid | not null; (`tenant_id`, `owner_id`, `conversation_id`) references `conversations` on delete cascade |
| `messages` | jsonb | the compacted `ModelMessage`s that replace the history up to the run |
| `created_at` | timestamptz | not null |

### `runs` (private)

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | primary key; also Pydantic AI's `run_id` and the DBOS workflow ID (ADR-0034) |
| `tenant_id`, `owner_id` | uuid | as in `conversations` |
| `conversation_id` | uuid | not null; (`tenant_id`, `owner_id`, `conversation_id`) references `conversations` on delete cascade |
| `parent_run_id` | uuid | the run this run continues (ADR-0037); null for the first run; (`tenant_id`, `owner_id`, `parent_run_id`) references `runs` on delete cascade; indexed |
| `kind` | text | `message` (a new turn) or `resume` (answers to an interrupt, ADR-0033) |
| `turn_allows_internet_access` | boolean | not null, default false; the turn has internet access (AGT-034, ADR-0113): set on a resume run answering a request for internet access with scope `turn`, and copied from the parent by every resume run; cleared on the conversation's active run when its user turns internet access off (ADR-0115). Replaces `turn_allows_web_and_commands` |
| `turn_denied_internet_access` | boolean | not null, default false; internet access was denied in this turn, or its request expired, so later calls that need it are denied without asking (AGT-034): set on the resume run that carries the denial, and copied from the parent by every resume run |
| `task_grants` | boolean | not null, default false; the calls of the run follow its conversation's task's grants (TSK-004, ADR-0106): set on the run a firing starts, unless the task failed the check of TSK-005 at the firing, and copied from the parent by every resume run |
| `status` | text | `queued`, `running`, `interrupted`, `completed`, `failed`, `cancelled` |
| `error_code` | text | stable error code when failed (API-007) |
| `connection_id` | uuid | the connection that answered; (`tenant_id`, `connection_id`) references `connections` on delete set null (`connection_id`) |
| `model_provider`, `model_name` | text | set when known (MOD-005) |
| `last_event_seq` | integer | sequence number of the last event written to the run's stream |
| `created_at`, `started_at`, `finished_at` | timestamptz | `finished_at` of a cancelled run that had started is set when its workflow has ended, not when it is cancelled: until then a rewind or a deletion of its conversation waits (ADR-0132) |

Constraints:

- at most one run with status `queued` or `running` per conversation (partial
  unique index), in addition to the per-conversation queue partition of
  ADR-0034;
- a run's parent belongs to the same conversation;
- a run has at most one child, and a conversation at most one run without a
  parent, so its runs form one chain (ADR-0068); a run of kind `resume` has
  the interrupted run as parent.

### `run_followers` (private)

An open event stream of a run (UX-004, ADR-0101).

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | primary key |
| `tenant_id`, `owner_id` | uuid | as in `runs` |
| `run_id` | uuid | not null; (`tenant_id`, `owner_id`, `run_id`) references `runs` on delete cascade; indexed |
| `seen_at` | timestamptz | not null; when the stream opened, then refreshed at least every 10 seconds while it is open |

The API deletes the row when its stream closes.

### `usage_ledger` (private)

One entry per model request made by the model gateway (MOD-006, ADR-0042).
It never contains content.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | primary key |
| `tenant_id`, `owner_id` | uuid | the user the request was made for; (`tenant_id`, `owner_id`) references `users` |
| `conversation_id` | uuid | null for requests outside a conversation; (`tenant_id`, `owner_id`, `conversation_id`) references `conversations` on delete set null (`conversation_id`) |
| `run_id` | uuid | null outside a run; (`tenant_id`, `owner_id`, `run_id`) references `runs` on delete set null (`run_id`) |
| `purpose` | text | `run`, `title`, `compaction`, `speech` or `memory` |
| `provider`, `model` | text | not null; the host of the connection's address and the model's name (MOD-005) |
| `input_tokens`, `cached_input_tokens`, `cache_write_tokens`, `output_tokens` | bigint | not null, default 0 |
| `cost` | numeric(20, 10) | null when the price is unknown |
| `currency` | text | ISO 4217 code, such as `USD`; null when `cost` is null |
| `price_source` | text | `provider`, `catalog`, `free` or `unknown` |
| `created_at` | timestamptz | not null; indexed with `owner_id` |

Totals per run, conversation, the last 24 hours and the last 30 days are computed from these rows (MOD-007, ADR-0073).
Per-user totals for tenant admins arrive in phase 1, through a function that
returns only sums per user.

### `tool_permissions`

A tenant admin's settings of tools for each user (AGT-002, ADR-0090). No
row means the tool or class follows its approval default.

| Column | Type | Notes |
|---|---|---|
| `tenant_id`, `user_id` | uuid | not null; (`tenant_id`, `user_id`) references `users` |
| `subject_kind` | text | `tool`, `class` or `server` |
| `subject` | text | a name of `ToolName`, a `CapabilityClass` of the API contract, or the ID of a row of `mcp_servers` (AGT-029, ADR-0099) |
| `setting` | text | `allow`, `ask` or `deny`; only `deny` for a server |
| `updated_at` | timestamptz | not null |

Primary key (`tenant_id`, `user_id`, `subject_kind`, `subject`).
Removing a server deletes the rows whose subject is that server.

Policies:
- `SELECT` where `tenant_id = app_tenant_id()` and (`user_id = app_user_id()`
  or `app_is_tenant_admin()`): users read their own, so that runs and the
  tool switches apply them.
- `INSERT`, `UPDATE`, `DELETE` where `tenant_id = app_tenant_id()` and
  `app_is_tenant_admin()`.

### `egress_policies`

Data egress policies stricter than `any` (MOD-003, ADR-0091): the
household's, the one a tenant admin set for a user, and a user's own. No row
means `any`.

| Column | Type | Notes |
|---|---|---|
| `tenant_id` | uuid | not null, references `tenants` |
| `user_id` | uuid | null for the household's policy; (`tenant_id`, `user_id`) references `users` on delete cascade |
| `set_by` | text | not null; `admin`, or `user` for a user's own choice, which needs `user_id` |
| `policy` | text | not null; `local_only` |
| `updated_at` | timestamptz | not null |

Unique (`tenant_id`, `user_id`, `set_by`), with nulls not distinct.

Policies:
- `SELECT` where `tenant_id = app_tenant_id()` and (`user_id` is null or
  `user_id = app_user_id()` or (`set_by = 'admin'` and
  `app_is_tenant_admin()`)): every user reads the household's policy and
  their own, and tenant admins read what they set, never a user's own choice.
- `INSERT`, `UPDATE`, `DELETE` where `tenant_id = app_tenant_id()` and
  ((`set_by = 'admin'` and `app_is_tenant_admin()`) or (`set_by = 'user'`
  and `user_id = app_user_id()`)).

### `audit_events` (private)

One entry per tool call (AGT-008, ADR-0090). It never contains content: no
arguments and no results. Entries outlive the conversation and its runs,
which they name only by identifier, without references, so that deleting or
rewinding a conversation keeps them; they are deleted with their user.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | primary key |
| `tenant_id`, `owner_id` | uuid | the user the call acted for; (`tenant_id`, `owner_id`) references `users` on delete cascade |
| `conversation_id`, `run_id` | uuid | not null; identifiers only |
| `tool_call_id` | text | not null; unique with `run_id`: the idempotency key of the call |
| `tool` | text | not null; the tool's name: one of `ToolName`, or a tool without a switch, such as `read_tool_result` |
| `outcome` | text | `not_needed`, `allowed`, `approved`, `denied`, `expired`, `refused`, `granted` (a task grant covered it) or `not_granted` (it needed approval in a task's run and no grant covered it, ADR-0106) |
| `scope` | text | `once`, `turn` or `conversation`, else null |
| `reason` | text | `untrusted_content`, `tool_default`, `permission`, `consequential`, `device`, `task_proposal` or `internet_access`, else null |
| `attempts` | integer | not null, default 0; incremented before each start of a call of a tool in the `external_communication`, `irreversible` or `physical` class, outside any durable step, so that a run replayed after a crash, which calls its tools again, increments it again; more than one means it may have run twice (ADR-0034) |
| `created_at` | timestamptz | not null; indexed with `owner_id` |

### `connections`

A household's access to one provider (MOD-008, ADR-0069).

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | primary key |
| `tenant_id` | uuid | not null, references `tenants` |
| `name` | text | not null; unique within the tenant |
| `kind` | text | not null; `openrouter` or `openai` |
| `base_url` | text | not null; the address of the API |
| `location` | text | not null; `local` or `remote`, always `remote` for `openrouter` (MOD-010) |
| `api_key_ciphertext` | bytea | the API key, encrypted with AES-256-GCM under `SIBILLO_SECRET_KEY` (ADR-0051); null when the server needs no key |
| `private_network` | boolean | not null, default false; true when `base_url` was set by a user who is the instance admin (MOD-009) |
| `default_model` | text | the model of this connection that new conversations start with; at most one connection per tenant has one (MOD-012) |
| `transcription_model` | text | the model of this connection that transcribes the household's spoken turns; at most one connection per tenant has one (API-006, ADR-0088) |
| `speech_model` | text | the model of this connection that reads aloud for the household; at most one connection per tenant has one (API-006, ADR-0088) |
| `speech_voice` | text | the voice of `speech_model`; set exactly when it is |
| `context_window` | integer | for `openai`, the context window of its models in tokens, at least 512, 8192 unless set; null for `openrouter` (ADR-0073) |
| `image_models` | text[] | not null, default empty; for `openai`, the models a tenant admin says accept images, at most 200 names of at most 200 characters (MOD-020, ADR-0110) |
| `models_refreshed_at` | timestamptz | when its models were last listed |
| `server_product` | text | `ollama` when Sibillo recognized the server behind a connection of kind `openai`; else null (MOD-019, ADR-0093) |
| `server_version` | text | the recognized server's version; set exactly when `server_product` is |
| `created_at`, `updated_at` | timestamptz | not null |

Policies: `SELECT` where `tenant_id = app_tenant_id()`, since every user's
runs and model list need it; `INSERT`, `UPDATE` and `DELETE` where
`tenant_id = app_tenant_id()` and `app_is_tenant_admin()`.

A trigger keeps `private_network` honest: on `INSERT` it may be true only when
`app_is_instance_admin()`; on `UPDATE` it may become or stay true with a new
`base_url` only when `app_is_instance_admin()`, and otherwise a new
`base_url` sets it to false.

### `connection_models`

The models a connection offers, as last listed by its provider (MOD-011,
ADR-0069).

| Column | Type | Notes |
|---|---|---|
| `tenant_id` | uuid | not null |
| `connection_id` | uuid | not null; (`tenant_id`, `connection_id`) references `connections` on delete cascade |
| `model` | text | not null; the provider's name for the model |
| `name` | text | not null; the name to show |
| `position` | integer | not null; the provider's order, from 1: for OpenRouter, most used in the past week first |
| `context_window` | integer | null when unknown |
| `tools` | boolean | whether the model can call tools; null when unknown (MOD-014) |
| `reasoning` | boolean | whether the model can reason; null when unknown (CNV-013, ADR-0081) |
| `images` | boolean | whether the model accepts images, as its provider says; null when it does not say: the connection's `image_models` then decides (MOD-020, ADR-0110) |
| `kind` | text | not null, default `chat`; `chat`, `transcription` or `speech` (ADR-0088) |
| `voices` | text[] | a speech model's voices, when its provider lists them; else null (ADR-0088) |
| `input_price`, `cached_input_price`, `output_price` | numeric(20, 10) | price per million tokens, or null |
| `currency` | text | ISO 4217 code; not null exactly when a price is set |

Primary key (`connection_id`, `model`). Policies as for `connections`;
listing the models again replaces the rows of the connection.

### `mcp_servers`

A household's remote MCP servers (AGT-019, ADR-0064, ADR-0099).

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | primary key |
| `tenant_id` | uuid | not null, references `tenants` |
| `name` | text | not null; unique within the tenant; from 1 to 100 characters |
| `prefix` | text | not null; unique within the tenant; from 1 to 20 lowercase letters, digits and single underscores, starting with a letter; never changed |
| `url` | text | not null; the address of its Streamable HTTP endpoint |
| `auth` | text | not null; `none`, `token` or `oauth` (AGT-030, AGT-031) |
| `generation` | uuid | not null; a new random value whenever `url`, `auth` or the OAuth client changes; credentials and sign-ins of another generation are not used (ADR-0099) |
| `oauth` | jsonb | for `oauth`, what discovery found and the client (ADR-0100): `{issuer, authorization_endpoint, token_endpoint, iss_parameter_supported, scope, client_id, client_registration, token_endpoint_auth_method}`, where `client_registration` is `given`, `metadata_document` or `dynamic` and `token_endpoint_auth_method` is `none`, `client_secret_basic` or `client_secret_post`; null otherwise |
| `oauth_client_secret_ciphertext` | bytea | the OAuth client's secret, encrypted with AES-256-GCM under `SIBILLO_SECRET_KEY` with the server's ID as associated data (MOD-002); null when the client has none |
| `private_network` | boolean | not null, default false; true when `url` was set by a user who is the instance admin, as in `connections` |
| `enabled` | boolean | not null, default true; false when a tenant admin switched it off for everyone |
| `server_name`, `server_version` | text | what the server said of itself when last listed; null before |
| `listed_at` | timestamptz | when its tools were last listed |
| `created_at`, `updated_at` | timestamptz | not null |

At most 20 rows per tenant. Policies as for `connections`, and the same
trigger keeps `private_network` honest, with `url` for `base_url`. `oauth`
is not null exactly when `auth` is `oauth`.

### `mcp_server_tools`

The tools of a remote MCP server, as last listed and as accepted (AGT-028,
ADR-0099).

| Column | Type | Notes |
|---|---|---|
| `tenant_id` | uuid | not null |
| `server_id` | uuid | not null; (`tenant_id`, `server_id`) references `mcp_servers` on delete cascade |
| `name` | text | not null; the server's name for the tool, without the prefix |
| `listed` | jsonb | the tool as last listed, `{title, description, inputSchema, annotations}`; null when the last listing did not have it |
| `accepted` | jsonb | the tool as a tenant admin accepted it, `{title, description, inputSchema}`; null when not accepted |
| `problem` | text | why the listed tool cannot be accepted: `name`, `description_too_long`, `schema_too_large`, `too_many_tools`, `requires_tasks` or `hidden_characters` (ADR-0128); else null |
| `accepted_at` | timestamptz | set exactly when `accepted` is |

Primary key (`server_id`, `name`). Policies as for `connections`. Listing
the tools again sets `listed` and `problem` for every tool, and deletes the
rows that end with neither `listed` nor `accepted`; a new `url` sets
`accepted` to null in every row of the server.

### `mcp_credentials` (private)

Each user's own credential for a remote MCP server (AGT-030, AGT-031,
ADR-0099, ADR-0100). Tenant admins cannot read them.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | primary key |
| `tenant_id`, `owner_id` | uuid | not null; (`tenant_id`, `owner_id`) references `users` on delete cascade |
| `server_id` | uuid | not null; (`tenant_id`, `server_id`) references `mcp_servers` on delete cascade |
| `server_generation` | uuid | not null; the server's `generation` when the credential was given; a credential of another generation is not used, and is deleted when its owner's requests or runs meet it |
| `kind` | text | not null; `token` when entered by the user, `oauth` when obtained by signing in |
| `access_token_ciphertext` | bytea | not null; encrypted with AES-256-GCM under `SIBILLO_SECRET_KEY`, with the row's ID followed by `:access` as associated data (MOD-002) |
| `refresh_token_ciphertext` | bytea | the OAuth refresh token, encrypted likewise with the row's ID followed by `:refresh`; null when there is none |
| `expires_at` | timestamptz | when the access token expires; null when unknown |
| `status` | text | not null; `valid`, or `expired` once the server refused it or renewing it failed |
| `created_at`, `updated_at` | timestamptz | not null |

Unique (`server_id`, `owner_id`). Renewing a token locks its row (`SELECT …
FOR UPDATE`) until the new tokens are stored.

### `mcp_sign_ins` (private)

OAuth sign-ins to remote MCP servers waiting for their redirect, each valid
for 10 minutes and deleted when used (AGT-031, ADR-0100).

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | primary key |
| `tenant_id`, `owner_id` | uuid | not null; (`tenant_id`, `owner_id`) references `users` on delete cascade |
| `server_id` | uuid | not null; (`tenant_id`, `server_id`) references `mcp_servers` on delete cascade |
| `server_generation` | uuid | not null; the server's `generation` when the sign-in started |
| `state_hash` | bytea | not null; unique; SHA-256 of the `state` |
| `code_verifier` | text | not null; the PKCE code verifier |
| `created_at` | timestamptz | not null |
| `expires_at` | timestamptz | not null; 10 minutes after `created_at` |

Expired rows of a user are deleted when that user starts or completes a
sign-in.

### `served_context_windows`

The window each model of a recognized Ollama server last said it runs with
(MOD-019, ADR-0093). The worker records it after a response, for whichever
user of the household the run is for, so any user of the tenant may write it;
it only ever lowers the window Sibillo uses, and the model list itself stays
with tenant admins.

| Column | Type | Notes |
|---|---|---|
| `tenant_id` | uuid | not null |
| `connection_id` | uuid | not null; (`tenant_id`, `connection_id`) references `connections` on delete cascade |
| `model` | text | not null; the provider's name for the model |
| `context_window` | integer | not null; between 1 and 10000000 |
| `observed_at` | timestamptz | not null |

Primary key (`connection_id`, `model`). Policies: `SELECT`, `INSERT` and
`UPDATE` where `tenant_id = app_tenant_id()`; no `DELETE` but through its
connection.

### `mcp_server_events`

The event types of a remote MCP server, as last listed and as accepted
(TSK-008, ADR-0106).

| Column | Type | Notes |
|---|---|---|
| `tenant_id` | uuid | not null |
| `server_id` | uuid | not null; (`tenant_id`, `server_id`) references `mcp_servers` on delete cascade |
| `name` | text | not null; the server's name for the event type |
| `listed` | jsonb | the type as last listed, `{description, inputSchema, payloadSchema, delivery}`; null when the last listing did not have it |
| `accepted` | jsonb | the type as a tenant admin accepted it, `{description, inputSchema, payloadSchema}`; null when not accepted |
| `problem` | text | why the listed type cannot be accepted: `name`, `description_too_long`, `schema_too_large`, `too_many_events` or `no_supported_delivery` (neither `poll` nor `webhook`); else null |
| `accepted_at` | timestamptz | set exactly when `accepted` is |

Primary key (`server_id`, `name`). Policies as for `connections`. Listing
the server again lists its event types as it lists its tools, with the same
rules; a new `url` sets `accepted` to null in every row of the server.

### `tasks` (private)

A user's tasks (TSK-001, ADR-0106).

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | primary key |
| `tenant_id`, `owner_id` | uuid | not null; (`tenant_id`, `owner_id`) references `users` on delete cascade |
| `name` | text | not null; from 1 to 100 characters; unique for its owner |
| `instructions` | text | not null; from 1 to 20,000 characters |
| `connection_id`, `model` | uuid, text | the model of its conversations, as in `conversations`: set from its owner's default model, else the tenant's, when the task is created, or chosen by its owner; (`tenant_id`, `connection_id`) references `connections` on delete set null (`connection_id`) |
| `reasoning` | text | not null, default `on`; as in `conversations` |
| `disabled_tools`, `disabled_skills` | text[] | not null, default empty; as in `conversations` |
| `disabled_servers` | uuid[] | not null, default empty; as in `conversations` |
| `uses_memory` | boolean | not null, default false; whether its runs use memory, when memory is on for its owner |
| `internet_access` | boolean | not null, default false; the task's grant of internet access (TSK-004, AGT-034, ADR-0113). A task that had an open grant of `web_search` or `read_page` has it, and loses those grants |
| `time_zone` | text | not null; an IANA time zone name, such as `Europe/Rome` |
| `paused_at` | timestamptz | when it was paused; null while it fires |
| `skipped_count` | integer | not null, default 0; firings that did not run, over the limit or while paused (TSK-009) |
| `last_skipped_at` | timestamptz | when the latest of them arrived; null when none did |
| `created_at`, `updated_at` | timestamptz | not null |

At most 50 rows per owner. Copied into each conversation it starts: the
model, the reasoning, the disabled tools, skills and servers. Its
instructions become the first message.

### `task_grants` (private)

The task grants of a task (TSK-004, TSK-005, ADR-0106).

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | primary key |
| `tenant_id`, `owner_id` | uuid | not null |
| `task_id` | uuid | not null; (`tenant_id`, `owner_id`, `task_id`) references `tasks` on delete cascade |
| `tool` | text | not null; the name the model knows the tool by: a `ToolName` of the API contract, or `<prefix>__<name>` of a remote MCP server's tool |
| `server_id` | uuid | the server of a server's tool, else null; (`tenant_id`, `server_id`) references `mcp_servers` on delete cascade |
| `arguments` | jsonb | for a fixed grant, the call's arguments, a JSON object, at most 4 KiB; null for an open grant |
| `created_at` | timestamptz | not null |

Unique (`task_id`, `tool`, `arguments`), with nulls not distinct. At most 20
rows per task. A row with `server_id` has `arguments`: open grants never
cover a server's tool. No row names `web_search`, `read_page` or
`request_internet_access`, which follow the task's `internet_access`
(ADR-0113).

### `task_triggers` (private)

The triggers of a task (TSK-003, TSK-007, TSK-008, ADR-0106).

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | primary key |
| `tenant_id`, `owner_id` | uuid | not null |
| `task_id` | uuid | not null; (`tenant_id`, `owner_id`, `task_id`) references `tasks` on delete cascade |
| `kind` | text | not null; `schedule`, `webhook` or `mcp_event` |
| `schedule_start` | timestamp | for `schedule`, its start, a date and time without time zone, read in the task's time zone (ADR-0109); else null |
| `recurrence` | text[] | for `schedule`, its lines of RFC 5545 recurrence, at most 5; empty for once; else null |
| `next_fire_at` | timestamptz | for `schedule`, its next firing time, null once its last occurrence passed; indexed; else null |
| `token_hash` | bytea | for `webhook`, the SHA-256 of its token; unique; else null |
| `server_id` | uuid | for `mcp_event`, the server; (`tenant_id`, `server_id`) references `mcp_servers` on delete cascade; else null |
| `server_generation` | uuid | for `mcp_event`, the server's `generation` when the subscription was made; a subscription of another generation is made again, with the owner's credential of the new one |
| `event_name` | text | for `mcp_event`, the event type; else null |
| `event_arguments` | jsonb | for `mcp_event`, the subscription's arguments, a JSON object of at most 4 KiB; else null |
| `delivery` | text | for `mcp_event`, `poll` or `webhook`; else null |
| `cursor` | text | for `mcp_event`, the server's cursor after the last event received; null to start from now |
| `next_poll_at` | timestamptz | for `poll`, when to poll next: the server's `nextPollMs`, at least one minute after the last poll; indexed |
| `secret_ciphertext` | bytea | for `webhook` delivery, the subscription's secret (`whsec_` and 32 random bytes in base64), encrypted with AES-256-GCM under `SIBILLO_SECRET_KEY` with the row's ID followed by `:secret` as associated data (MOD-002); else null |
| `refresh_before` | timestamptz | for `webhook` delivery, the server's `refreshBefore` of the subscription |
| `problem` | text | for `mcp_event`, why it receives no events: `not_accepted` (the type is not, or no longer, an accepted event type), `credential_missing`, `unauthorized`, `unreachable` or `terminated`; else null |
| `created_at` | timestamptz | not null |

At most 5 rows per task, and at least one while the task exists. Resuming a
paused task sets `cursor` to null, so that events of the pause do not fire
it.

### `task_firings` (private)

The firings of a task that wait, run or ran (TSK-002, TSK-009, ADR-0106).
Firings over the limit or while the task is paused have no row; the task
counts them.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | primary key |
| `tenant_id`, `owner_id` | uuid | not null |
| `task_id` | uuid | not null; (`tenant_id`, `owner_id`, `task_id`) references `tasks` on delete cascade |
| `trigger_id` | uuid | (`tenant_id`, `owner_id`, `trigger_id`) references `task_triggers` on delete set null (`trigger_id`) |
| `trigger_kind` | text | not null; the trigger's `kind`, or `manual` when the user fired the task at once (TSK-011) |
| `fire_key` | text | not null; what makes a firing one: the trigger's ID followed by `:` and, for a schedule, the firing time it stands for, for an MCP event, its event ID, for a webhook request, a random UUID; `manual:` and a random UUID for a manual firing |
| `event` | jsonb | the event, `{name, data}` for an MCP event, `{content_type, body}` for a webhook request, at most 64 KiB; set to null when the firing is `done`, so that its first run can be queued again after a crash until then |
| `status` | text | not null; `waiting`, `running` (its conversation's first run has not ended) or `done` |
| `without_grants` | boolean | not null, default false; the task failed the check of TSK-005 at the firing |
| `conversation_id` | uuid | the conversation it started; (`tenant_id`, `owner_id`, `conversation_id`) references `conversations` on delete set null (`conversation_id`) |
| `created_at` | timestamptz | not null; when the trigger fired; indexed with `task_id` for the hourly limit |
| `started_at`, `finished_at` | timestamptz | when its conversation started, and when its first run ended |

Unique (`task_id`, `fire_key`): the worker inserts a firing with
`ON CONFLICT DO NOTHING` and starts its conversation in the transaction that
sets `status` to `running`, so that one firing starts one conversation
(TSK-003). At most one row per task is `running`. Rows are deleted with their
task: the task's list of conversations reads them (TSK-002).

### Change notifications

The API and the worker announce the changes of API-008 with
`pg_notify('sibillo_changes', payload)` in the transaction that makes them,
where the payload is a JSON object `{tenant_id, user_id, event}` and `event`
is a `ChangeEvent` of the API contract (ADR-0108): when a conversation is
created, a run starts or reaches a final status, or a task fires. Each API
process listens on the channel with one connection of `sibillo_app`, outside
any request context, and forwards an event only to the streams of that
tenant and user. Payloads carry no content.

### Policies for private tables

`device_sessions`, `notification_subscriptions`, `passkey_challenges`, `folders`, `user_settings`, `memory_items`, `skills`, `skill_files`, `conversations`,
`conversation_plans`, `conversation_messages`, `compaction_checkpoints`, `runs`, `run_followers`, `usage_ledger`,
`audit_events`, `mcp_credentials`, `mcp_sign_ins`, `tasks`, `task_grants`,
`task_triggers` and `task_firings` use the same policy for
every operation:

```sql
USING      (tenant_id = app_tenant_id() AND owner_id = app_user_id())
WITH CHECK (tenant_id = app_tenant_id() AND owner_id = app_user_id())
```

(`device_sessions` and `passkey_challenges` use `user_id` in place of
`owner_id`.)

## Privileges of `sibillo_app`

`sibillo_app` holds exactly these privileges, and nothing else (TEN-004). Rows
that a conversation's deletion removes or detaches are handled by the foreign
keys, not by privileges of `sibillo_app`.

| Object | Privileges |
|---|---|
| `tenants` | `SELECT`, `INSERT` |
| `users` | `SELECT` on every column except `password_hash`; `INSERT`; `UPDATE` of `display_name`, `password_hash`, `role`, `disabled_at` |
| `device_sessions` | `SELECT`, `INSERT`, `DELETE`; `UPDATE` of `revoked_at` |
| `notification_subscriptions` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` |
| `login_attempts` | none |
| `passkeys` | `SELECT`, `INSERT`, `DELETE`; `UPDATE` of `sign_count` and `last_used_at` |
| `passkey_challenges` | `SELECT`, `INSERT`, `DELETE` |
| `folders` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` |
| `user_settings` | `SELECT`, `INSERT`, `UPDATE` |
| `memory_items` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` |
| `skills` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` |
| `skill_files` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` |
| `conversations` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` |
| `conversation_plans` | `SELECT`, `INSERT`, `UPDATE` |
| `compaction_checkpoints` | `SELECT`, `INSERT`: checkpoints never change (ADR-0041) |
| `conversation_messages` | `SELECT`, `INSERT`: stored messages never change (ADR-0041) |
| `runs` | `SELECT`, `INSERT`, `UPDATE`, `DELETE`: rewinding deletes runs (ADR-0068) |
| `run_followers` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` |
| `usage_ledger` | `SELECT`, `INSERT`: entries never change (ADR-0042) |
| `tool_permissions` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` |
| `egress_policies` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` |
| `audit_events` | `SELECT`, `INSERT`; `UPDATE` of `outcome`, `scope`, `reason` and `attempts`: an event is written when the call is decided and completed as it runs |
| `connections` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` |
| `connection_models` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` |
| `mcp_servers` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` |
| `mcp_server_tools` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` |
| `mcp_credentials` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` |
| `mcp_sign_ins` | `SELECT`, `INSERT`, `DELETE` |
| `served_context_windows` | `SELECT`, `INSERT`, `UPDATE` |
| `mcp_server_events` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` |
| `tasks` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` |
| `task_grants` | `SELECT`, `INSERT`, `DELETE` |
| `task_triggers` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` |
| `task_firings` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` |
| Helper functions | `EXECUTE` on `app_tenant_id()`, `app_user_id()`, `app_is_tenant_admin()`, `app_is_instance_admin()` |
| Pre-authentication functions | `EXECUTE` on every function of that section except `bootstrap_instance` and `remove_passkeys` |

`EXECUTE` on functions is revoked from `PUBLIC`.

## Durable execution schema (`dbos`)

DBOS (ADR-0034) keeps its own tables in the `dbos` schema, created and
migrated by the DBOS system migrations, which the migration command runs as
`sibillo_owner` after the Alembic revisions, granting `sibillo_app` the access DBOS
needs (ADR-0052): workflow status, inputs and outputs, step outputs,
notifications and streams. They hold user content (prompts, model responses,
run events) **without row-level security**, which DBOS cannot apply. Rules
(TEN-009):

- Application code reads or writes DBOS data only for workflow IDs that are
  run IDs obtained from the row-level-secured `runs` table in the same
  request.
- Deleting a conversation deletes the DBOS workflows of its runs.
- Workflows of runs whose `finished_at` is more than `SIBILLO_RUN_RETENTION_DAYS`
  days ago (default 30) are deleted by the worker, when it starts and then
  every hour (ADR-0052).
- Temporary conversations whose last activity is more than 24 hours ago
  are deleted by the worker, with their workflows, every
  `SIBILLO_TEMPORARY_SWEEP_SECONDS` (CNV-011, ADR-0082).
- Workflow inputs carry the tenant and user IDs of the run; the worker sets
  the request context from them.

## Deletion

Deleting a conversation deletes its messages and runs in the same transaction,
and the DBOS workflows of those runs (API-003, TEN-009). Rewinding deletes the
runs after the turn it rewinds to, and their messages and workflows, the same
way (CNV-004, ADR-0068); the foreign key from a run to its parent cascades. Its entries in the
cost ledger are kept, detached from the conversation and its runs, so that
spending totals stay correct (ADR-0042), and so are its audit events
(ADR-0090), the memory items written in it (ADR-0095) and the skills saved
in it (ADR-0096). Deleting a task deletes its grants, triggers and firings,
and leaves the conversations it started, with their `task_name` (ADR-0106). Deletion is physical;
there is no soft delete for user content.

## Migrations

Until the first release, `migrations/` holds a single initial migration that
creates this schema, rewritten whenever the contract changes; existing
databases are recreated (ADR-0071). From the first release on, migrations
are only added, and upgrade every released version (OPS-005).

## Properties verified by design tests

- Every table of the application schema has row-level security enabled and
  forced (TEN-003); the `dbos` schema is the documented exception (TEN-009).
- Every table holding user data has `tenant_id`, and private tables have an
  owner column (TEN-002).
- `sibillo_app` is not a superuser, lacks `BYPASSRLS` and owns no table or
  function (TEN-004).
- Every `SECURITY DEFINER` function is a pre-authentication function or
  `revoke_sessions_of_disabled_user()`, is owned by `sibillo_owner` and has a fixed
  `search_path`.
- `sibillo_app` holds exactly the privileges listed in "Privileges of `sibillo_app`"
  (TEN-004).
- Policies for `sibillo_owner` are exactly the owner policies listed with the
  pre-authentication functions; every other policy is for `sibillo_app`.
- Every foreign key between tenant-scoped tables includes `tenant_id`, and
  every foreign key between private tables also includes the owner column.
- Users cannot change their own `role` or `disabled_at`, and only instance
  admins create instance admins (AUTH-008).
- Only a user who is the instance admin can set a connection's address while
  keeping `private_network` true (MOD-009).
- A tenant admin can neither read nor change a user's own data egress policy,
  and a user can change only their own (MOD-003).
- A tenant admin can read and remove the passkeys of the users of their
  tenant, but cannot add or change one; a user adds and changes only their
  own (AUTH-010).
