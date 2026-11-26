# ADR-0144: Accounts that admins reset and delete

- **Status:** Accepted
- **Date:** 2026-11-26
- **Deciders:** @tapionx
- **Related:** AUTH-008, AUTH-009, AUTH-011, AUTH-012, AUTH-013, AUTH-014, TEN-007, TEN-008, TEN-009, UX-044, ADR-0046, ADR-0048, ADR-0105

## Context

A tenant admin creates accounts and disables them through the API
(AUTH-002, AUTH-008), but the web app offers neither: the household's
settings list its members only to remove their passkeys (UX-026). Two needs
have nothing at all:

- **A forgotten password.** Only the user changes their password
  (AUTH-011, ADR-0105), so a user who forgets it is locked out for good.
  ADR-0105 left "an administrator setting a new initial password, which the
  user must replace" to a requirement of its own.
- **A member who leaves.** Nothing deletes an account (threat model,
  residual risks). A disabled account keeps everything it had: its
  conversations and workspaces, its memory, its tasks and its spending.

ADR-0105 keeps a member's data private from a tenant admin: an admin who
wants to read it must sign in with the initial password and change it,
which locks the member out, so that the member notices (T-41). Whatever
resets a password must keep that property.

Deleting an account reaches rows that row-level security keeps from the
tenant admin (TEN-007), the durable execution engine's workflows (TEN-009),
and the conversations' workspaces in the sandbox driver (TEN-008), whose
names the control plane builds from identifiers read under row-level
security.

## Decision

We will:

1. **Let a tenant admin give a new initial password.**
   `POST /tenant/users/{user_id}/password` takes the new password, with the
   rules of an account's creation (12 to 1024 characters), and answers the
   user. It sets the password's hash and `password_change_required`, so
   that the user chooses their own at the next sign-in (AUTH-012). It is
   refused for the admin's own account, which they change with
   `POST /me/password`, and for an instance admin's unless the caller is
   one, as for roles (AUTH-008).
2. **End what the old password opened.** The reset revokes every session
   of the account and forgets its notification subscriptions in the same
   transaction, through a trigger, as disabling revokes sessions
   (AUTH-009, ADR-0048). The trigger function becomes
   `revoke_sessions_of_user()`, called on both changes.
3. **Keep the passkeys.** A user who has a passkey still needs it after a
   reset. An admin who resets a password to read a member's data must also
   remove the member's passkeys, which the member sees as well; an admin
   who does both for a user who lost both is doing what the user asked.
4. **Relax the `users` guard by exactly that much.** The trigger that
   refuses a change of `password_hash` or `password_change_required` by
   anyone but the user (ADR-0105) allows it from a tenant admin when the
   change sets a new hash and marks the row `password_change_required`,
   and, for an instance admin's row, only from an instance admin. Setting
   the mark alone, without a new hash, stays refused to everyone, and the
   user themself never sets it.
5. **Delete only a disabled account.** `DELETE /tenant/users/{user_id}`
   answers `409 resource.conflict` for an account that is not disabled, and
   `409 run.in_progress` while one of its runs is queued or running. The
   two steps, disabling then deleting, make an irreversible change
   deliberate, and a disabled account starts nothing new: its sessions are
   gone, its tasks do not fire (TSK-010). It is refused for the admin's own
   account and for any instance admin's: the instance admin is the
   operator, removed only by the operator.
6. **Delete through two functions of the database contract.** Both are
   `SECURITY DEFINER`, owned by `sibillo_owner`, and check the request
   context themselves: the caller is a tenant admin of the account's
   tenant, the account is disabled, it is not the caller's and not an
   instance admin's.
   - `account_storage(user_id)` returns the identifiers of what lives
     outside the application's tables: the account's conversations, for
     their workspaces, and its runs and task firings, for their workflows.
     It raises `object_in_use` while a run is queued or running.
   - `delete_account(user_id)` deletes the account's row. Every foreign key
     to `users` cascades, so its rows in every table go with it in the same
     statement: foreign key actions are not subject to row-level security.
   The API calls the first, deletes the workflows, then each
   conversation's workspace through the sandbox driver, then calls the
   second. A failure leaves the account disabled with less storage, and
   the deletion can be repeated: deleting a workspace or a workflow that is
   gone succeeds.
7. **Delete everything of the user.** Their cost ledger entries and audit
   events go too: the household's totals lose them, and nothing of the
   member remains to be read or restored. Their username is free again.
   A backup made before keeps them, as it keeps every deleted conversation
   (OPS-006).

## Consequences

- A user who forgot their password asks an admin, who gives a new initial
  one and passes it on; the user replaces it at once.
- TEN-007 and TEN-008 change: a tenant admin deletes a member's data by
  deleting their account, and the sandbox driver deletes workspaces whose
  identifiers come from `account_storage`, not from rows the admin reads
  under row-level security.
- The `users` table gains an owner policy for `DELETE`, and
  `notification_subscriptions` owner policies for `SELECT` and `DELETE`,
  used by `delete_account` and `revoke_sessions_of_user()`.
- Foreign keys to `users` that did not cascade now do. No code of the
  application deletes a user's row, so nothing else changes: `sibillo_app`
  has no `DELETE` on `users`.
- Deleting a household, and a member's export of their own data before
  they leave, remain future work.

## Alternatives considered

- **A reset link instead of a password the admin passes on:** it needs mail
  or another channel, which Sibillo does not have, and gives the same
  exposure as an initial password (ADR-0105).
- **A reset that also removes the passkeys:** one step for the admin, but
  it would let an admin who resets a password sign in as a member who has
  a passkey without the member's device.
- **Deleting an enabled account:** one step, but a run or a sign-in in
  progress would race with the deletion, and an irreversible change would
  be one click away.
- **Deleting under the member's request context:** the API would set the
  context of the account it deletes, which TEN-005 forbids: the context
  comes from the authenticated identity.
- **Owner policies for `DELETE` on every private table:** the same effect
  as cascading foreign keys, with some thirty policies to keep in step with
  the tables.
- **Keeping the ledger entries for the household's totals:** they would
  outlive the member whose activity they describe, with nobody left who may
  read them.
