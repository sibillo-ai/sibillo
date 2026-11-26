# AUTH — Authentication and accounts

How people sign in and how accounts are created.

## AUTH-001: Local accounts

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

The system MUST support local accounts with passwords hashed using Argon2id.
Passwords MUST never be logged or stored in reversible form.

## AUTH-002: Accounts created by administrators

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

User accounts MUST be created by a tenant admin or the instance admin. Public
self-registration MUST be disabled by default.

## AUTH-003: OpenID Connect login

- **Status:** draft
- **Priority:** SHOULD
- **Phase:** 4
- **Verification:** integration

The system SHOULD support signing in through an external OpenID Connect
provider (e.g. a self-hosted identity provider), mapped to existing accounts.

## AUTH-004: Revocable device sessions

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

Authentication MUST use opaque, random session tokens of at least 256 bits,
stored only as hashes, each bound to one user and one device and carrying an
expiry. A user MUST be able to list their sessions and revoke any of them, and
a revoked or expired token MUST be rejected on the next request (ADR-0025).

## AUTH-005: Cookie sessions protected against CSRF

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** security

When a session token is carried in a cookie, the cookie MUST be `HttpOnly`,
`Secure` and `SameSite=Lax`, named with the `__Host-` prefix, and every
state-changing request authenticated by cookie MUST also carry a custom
request header that cross-site requests cannot set. Answers MUST carry
headers that keep them out of caches, frames and other origins (ADR-0131).

## AUTH-006: Login rate limiting

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

Login attempts MUST be rate-limited per account and per source address. An
attempt over a limit MUST be refused before its password is checked, and the
server MUST check a bounded number of passwords at a time (ADR-0047,
ADR-0118). The source MUST be read from every forwarding header line a
trusted proxy sent, and an IPv6 source MUST count as its /64 (ADR-0131).

## AUTH-007: First administrator without default credentials

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

The first instance admin MUST be created during setup by an explicit,
one-time command run by whoever operates the instance. The system MUST NOT
ship or accept any default credentials.

## AUTH-008: Privileges changed only by administrators

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** security

Changing a user's role, and disabling or re-enabling their account, MUST
require a tenant admin of the user's tenant; changing the role or the account
state of an instance admin MUST require an instance admin. Creating an
instance admin MUST require an instance admin. A user MUST NOT be able to
raise their own privileges or re-enable their own account. A tenant admin
MUST be able to disable and re-enable an account of their tenant and change
its role through the API, never their own, and never so that the tenant has
no enabled tenant admin left (ADR-0131).

## AUTH-009: Disabling an account ends its sessions

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** security

Disabling an account MUST revoke every session of that account in the same
change, so that none of its tokens is accepted afterwards, including a token
of a sign-in that was in progress as the account was disabled. Re-enabling
the account MUST NOT restore any session.

## AUTH-010: Passkeys as a second factor

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration, security

A user MUST be able to register any number of passkeys (WebAuthn), including
ones that use the device's biometrics. Once a user has a passkey, signing in
MUST require their password and one of their passkeys. A tenant admin MUST be
able to remove the passkeys of another user of their tenant, never their own
and never an instance admin's unless they are one, and an operator
command MUST be able to remove the instance admin's, so that a lost passkey
never locks a user out for good (ADR-0065). Passkeys MUST be bound to the
configured origin of the instance, and registering or removing one's own
passkey MUST require the user's password (ADR-0094).

## AUTH-011: Changing one's password

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration, security

A user MUST be able to change their own password by giving their current
one, which is checked and rate-limited like a sign-in. The change MUST
revoke every other session of the user. Only the user MUST be able to choose
their password: no tenant admin and no other user. A tenant admin MAY only
give a new initial password, which the user then replaces (AUTH-013,
ADR-0105, ADR-0144).

## AUTH-012: An initial password is replaced at the first sign-in

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration, security

An account created by a tenant admin or the instance admin MUST have its
user choose a new password at their first sign-in. Until they do, every
request of their sessions MUST be refused, except reading their own account,
changing their password and signing out (ADR-0105).

## AUTH-013: A new initial password from an administrator

- **Status:** accepted
- **Priority:** MUST
- **Phase:** 3
- **Verification:** integration, security

A tenant admin MUST be able to give an account of their tenant a new
initial password, never their own and never an instance admin's unless
they are one. Its user MUST then replace it at their next sign-in, as at
the first (AUTH-012). The change MUST revoke every session of the account
and forget its notification subscriptions in the same change, and MUST
keep its passkeys, so that a user who has one still needs it to sign in
(ADR-0144).

Rationale: a user who forgets their password is otherwise locked out for
good, since only they can change it (AUTH-011).

## AUTH-014: Deleting an account

- **Status:** accepted
- **Priority:** MUST
- **Phase:** 3
- **Verification:** integration, security

A tenant admin MUST be able to delete a disabled account of their tenant,
never their own and never an instance admin's. Deleting an account MUST
delete for good everything that is its user's: their conversations with
their runs, messages, workflows and workspaces, their folders, memory,
skills, tasks and settings, their sessions, passkeys and notification
subscriptions, their credentials for remote MCP servers, the tool
permissions, data egress policies and budget set for them, their audit
events and their entries in the cost ledger. An account that is not
disabled, or that has a run queued or running, MUST NOT be deleted
(ADR-0144).

Rationale: a member who leaves the household otherwise leaves everything
they had behind, disabled but kept.
