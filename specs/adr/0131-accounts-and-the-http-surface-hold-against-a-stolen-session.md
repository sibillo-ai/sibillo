# ADR-0131: Accounts and the HTTP surface hold against a stolen session

- **Status:** Accepted
- **Date:** 2026-11-23
- **Deciders:** @tapionx
- **Related:** ADR-0025, ADR-0046, ADR-0047, ADR-0049, ADR-0050, ADR-0067, ADR-0094, ADR-0105, AUTH-004, AUTH-005, AUTH-006, AUTH-008, AUTH-010, OBS-003, OPS-002, TEN-007, T-12, T-14, T-15, T-37

## Context

A security audit of accounts, sessions and the HTTP surface found, beside
what ADR-0105 has since fixed (initial passwords, password changes, sessions
of disabled accounts):

- **No way to disable an account or change a role** through the API,
  though AUTH-008 says who may; a tenant admin cannot shut out a member whose
  device was stolen, and nothing keeps a household from losing its last
  tenant admin.
- **A stolen admin session removes passkeys,** its own included, and a
  second admin of the first household can strip the instance admin's,
  though ADR-0094 says a stolen session cannot weaken its own account.
- **The source address of a sign-in** is read from the first
  `X-Forwarded-For` line only, which a proxy that adds its own line leaves
  to the client; IPv6 sources are counted one address at a time; failures
  for different usernames from one source race past the limit.
- **SQL parameters may reach the logs** with a database error.
- **Response headers are missing:** no HSTS, no `nosniff` or `no-store` on
  the API's answers, no `Permissions-Policy`, `Cross-Origin-Opener-Policy` or
  `Cross-Origin-Resource-Policy`; the session cookie has no `__Host-`
  prefix, so a sibling host can plant one.
- **Anonymous health checks** query the database and the driver at every
  request.
- **Smaller gaps:** sessions have no absolute lifetime nor a limit per
  user, and registering a first passkey revokes none; Argon2 parameters can
  never be raised; `SIBILLO_PUBLIC_ORIGIN` accepts an IP address, which
  passkeys refuse later; a NUL byte in a path of the web app answers 500,
  and the app's files are read with blocking calls.

## Decision

1. **Tenant admins disable accounts and change roles.**
   `PATCH /tenant/users/{user_id}` takes `role` and `disabled`. The database
   keeps enforcing AUTH-008; the API also refuses a change of one's own
   account, and one that leaves the tenant without an enabled tenant admin.
   Disabling revokes every session (AUTH-009).
2. **Passkeys are removed by another admin only.** A tenant admin may not
   remove their own passkeys through the admin route, which is for a user
   who lost theirs, nor an instance admin's unless they are one; the
   database's policy says the same.
3. **The source of a sign-in is the proxy's view.** Every `X-Forwarded-For`
   line is read, joined, as ADR-0050 reads one. An IPv6 source counts as its
   /64. The limit of a source is taken under a lock of that source too. The
   lockout of a known username by an attacker who fails on purpose is a
   residual risk, as ADR-0047 accepted.
4. **SQL parameters never reach the logs:** the engine hides them.
5. **Every answer carries the headers.** The API's answers carry
   `X-Content-Type-Options: nosniff` and `Cache-Control: no-store`; every
   answer carries `Referrer-Policy: no-referrer`, `Permissions-Policy`
   denying the camera, microphone, geolocation and payment to every origin but
   the app's own where it needs them, `Cross-Origin-Opener-Policy:
   same-origin` and `Cross-Origin-Resource-Policy: same-origin`; with an
   `https` public origin, `Strict-Transport-Security` for a year. The session
   cookie is `__Host-sibillo_session`.
6. **Health is cached.** An anonymous health check answers what was found
   at most five seconds before.
7. **Smaller gaps close.** A session ends a year after it was made, however
   it is used, and a user has at most 50: a new one ends the least recently
   used. Registering a first passkey ends every other session of the user. A
   password whose hash has older Argon2 parameters is hashed again at a
   sign-in. `SIBILLO_PUBLIC_ORIGIN` must name a host, not an address. A path
   of the web app with a NUL byte is not found, and its files are read
   outside the event loop.
8. **What remains is said.** Usernames are unique in the instance, so
   creating a user tells a tenant admin whether a name is taken elsewhere;
   members see the names and roles of their household's users. The threat
   model says so.

This amends ADR-0050 point 3, ADR-0049 and ADR-0067.

## Consequences

- A household can shut out a stolen device's account without the instance
  admin, and cannot lock itself out of administration.
- Signed-in users are signed out once, as the cookie's name changes.
- A user who registers their first passkey signs in again elsewhere.

## Alternatives considered

- **Usernames unique per household:** the sign-in form would need the
  household too; a later ADR can choose it.
- **Locking accounts after failures instead of slowing them:** ADR-0047's
  reasons hold.
