# ADR-0105: Passwords belong to their users

- **Status:** Proposed
- **Date:** 2026-11-18
- **Deciders:** @tapionx
- **Related:** ADR-0009, ADR-0011, ADR-0025, ADR-0046, ADR-0047, ADR-0048, ADR-0069, ADR-0094, AUTH-001, AUTH-002, AUTH-006, AUTH-008, AUTH-009, AUTH-010, AUTH-011, AUTH-012, TEN-007, TEN-008, T-01, T-41

## Context

ADR-0009 makes data private by default, with sharing as an explicit act
within shared spaces. TEN-007 and TEN-008 were written for that model.
Shared spaces were later set aside with what would use them: copies sent to
another user, the file library and the egress policy of a space (CNV-010,
CNV-012, MOD-016, ROADMAP "Later"). What remains of TEN-007 is that a user's
data is theirs alone, and of TEN-008 that their files are kept apart.

Row-level security already keeps every private table to its owner, and the
tables a tenant shares are only its configuration, written by tenant admins
(ADR-0069). The sandbox driver names each workspace, disk and skills volume
from the tenant, the user and the conversation, and takes them only as UUIDs
in its paths.

One gap remains. A tenant admin creates an account with a password of their
choosing (AUTH-002), and nothing lets the user replace it: the API has no
password change, and the database lets a tenant admin set the password hash
of any user of the tenant, the instance admin included. The admin can sign
in as the member at any time and read everything that is theirs, which is
what TEN-007 forbids. The instance admin is trusted (ADR-0011); a tenant
admin is not, for the private data of others.

## Decision

We will:

1. **Keep TEN-007 and TEN-008 without shared spaces.** A user's data is
   private to them; the users of a tenant share only its configuration. If
   shared spaces return, they will come with requirements of their own.
2. **Let the user change their password.** `POST /me/password` takes the
   current password and the new one. The current one is checked and
   rate-limited like a sign-in, with the user's own username (ADR-0047,
   ADR-0094); a wrong one answers `403` and leaves the session valid. The
   new one has from 12 to 1024 characters, as when an account is created,
   and differs from the current one. The change replaces the hash, revokes
   every other session of the user, forgets their notification
   subscriptions, and answers `204`; the session that made it stays.
3. **Mark an initial password.** `users.password_change_required` is true
   for every account created through the API: the row-level security policy
   on inserts by `sibillo_app` requires it. The first instance admin, created
   by the setup command with a password they chose, does not have it.
4. **Make the user replace it.** `auth_find_session` returns the mark. While
   it is set, every request of the user's sessions answers `403` with
   `auth.password_change_required`, except `GET /me`, `POST /me/password` and
   `POST /auth/logout`. Signing in works as usual, passkeys included, so that
   the user can reach the change. `User` carries `password_change_required`,
   and the web app shows the change instead of the app while it is set.
   Changing the password clears the mark.
5. **Only the user changes their password.** The `users` guard trigger
   refuses a change of `password_hash` or `password_change_required` unless
   the row is the caller's own, and refuses to set the mark again. No
   endpoint lets an admin set another user's password.
6. **Protect the instance admin and disabled accounts** (AUTH-008,
   AUTH-009). The guard refuses a change of the role or the account state of
   an instance admin unless the caller is one. `auth_find_session` returns no
   session of a disabled account, so a sign-in that was in progress as the
   account was disabled yields no usable token.

## Consequences

- A tenant admin who wants to read a member's data must sign in first with
  the initial password and change it, which locks the member out: the
  member notices, and the household can tell. This is accepted, as it is
  for any administrator who creates accounts (T-41).
- A user who forgets their password cannot recover it. An administrator
  setting a new initial password, which the user must replace, is a
  follow-up with a requirement of its own.
- Clients other than the web app get `403 auth.password_change_required`
  for an account created by an admin, until the password is changed.
- Existing accounts created by an admin before this change have no mark;
  in the alpha the database is recreated rather than migrated.

## Alternatives considered

- **A sign-in step instead of a restricted session**, like the passkey step
  of ADR-0094: no session until the password is changed. It needs a second
  kind of sign-in token and duplicates the session delivery, for the same
  protection: a restricted session reaches nothing but the change.
- **An invitation link instead of an initial password:** the admin never
  knows a password. It needs mail or another channel to deliver the link, or
  the admin passes the link on, and whoever opens it first sets the
  password, which is the same exposure.
- **Trusting tenant admins like the instance admin:** simpler, but against
  ADR-0009, which keeps a parent's data private from the other parent who
  administers the household, and a teenager's from both.
