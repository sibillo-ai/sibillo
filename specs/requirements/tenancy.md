# TEN — Tenancy and data isolation

How data is organized and how users and tenants are isolated from each
other. Background: ADR-0009, ADR-0011.

## TEN-001: Tenant hierarchy

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** design

The data model MUST organize data as one instance containing tenants, each
tenant containing users. Every user belongs to exactly one tenant. Shared
spaces, which a tenant would also contain, are set aside (ROADMAP, Later).

## TEN-002: Ownership columns

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** design

Every row of tenant-scoped data in the application schema MUST carry the
identifier of its tenant.
Every row of private data MUST also carry the identifier of the user who owns
it.

## TEN-003: Row-level security on every tenant-scoped table

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** design

Every tenant-scoped table of the application schema MUST have PostgreSQL
row-level security enabled and forced, with policies restricting access to the current tenant and, for
private data, to the owning user. A design test MUST fail when a
tenant-scoped table lacks enabled and forced row-level security.

## TEN-004: Unprivileged application database role

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

The application MUST connect to the database with a role that is not a
superuser, does not have `BYPASSRLS` and does not own any tenant-scoped
table. Schema migrations MUST run with a separate role.

## TEN-005: Tenant context from the authenticated identity

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

The tenant and user context of every database transaction MUST be derived
only from the authenticated identity and set with transaction-local settings
at the start of the transaction. It MUST NOT be taken from request
parameters, and it MUST NOT persist across transactions on a pooled
connection.

## TEN-006: No cross-user or cross-tenant access

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** security

A user MUST NOT be able to read, list, modify or delete another user's
private data, or any data of another tenant, through any API endpoint.
Security tests MUST attempt such access for every endpoint that handles
tenant-scoped data.

## TEN-007: Private by default

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** security

Data a user creates MUST be private to them: no other user of their tenant,
a tenant admin included, may read, list, change or delete it. A tenant admin
MUST NOT be able to reach it by signing in as the user with a password the
admin chose (AUTH-011, AUTH-012). The only data that the users of a tenant
share MUST be the tenant's configuration that its tenant admins manage
(ADR-0069). Sharing a user's data with other users is not offered
(ADR-0105). A tenant admin MAY only see the sums of a user's usage
(MOD-021) and delete a disabled account with everything it holds
(AUTH-014, ADR-0144, ADR-0145).

## TEN-008: Partitioned file storage

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** security

Files stored for a user — a conversation's workspace, its disk, and the
skills given to its sandbox — MUST be kept apart per tenant, user and
conversation. The names of their storage MUST be built only from the
identifiers of the tenant, the user and the conversation, which the control
plane takes from the authenticated identity and from rows it reads under
row-level security, or, to delete an account, from the function of the
database contract that returns them only to a tenant admin of its tenant
(AUTH-014, ADR-0144), and which the sandbox driver accepts only as UUIDs. A
file operation MUST NOT reach outside the conversation's own workspace
(SBX-014).

## TEN-009: Durable execution data

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** security, design

Data stored by the durable execution engine outside the application schema
(ADR-0034) MUST be reached by application code only through run identifiers
read from row-level-secured tables, or, to delete an account, from the
function of the database contract that returns them only to a tenant admin
of its tenant (AUTH-014, ADR-0144), MUST be deleted together with the
conversation or the account it belongs to, and MUST be deleted once its
run has finished and the retention period configured by the instance admin
has passed. Row-level security does not cover it, so a run MUST take its
user's role from the database when it starts, never from its stored input
(ADR-0132).
