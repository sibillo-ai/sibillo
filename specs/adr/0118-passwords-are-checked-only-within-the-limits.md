# ADR-0118: Passwords are checked only within the limits, two at a time

- **Status:** Accepted
- **Date:** 2026-11-23
- **Deciders:** @tapionx
- **Related:** ADR-0025, ADR-0047, ADR-0094, AUTH-001, AUTH-006, T-14, T-15

## Context

ADR-0047 counts failed sign-ins per username and per source address, and
refuses an attempt over either limit. The server records an attempt after
checking its password, so that the record holds the outcome: a refused
attempt has had its password checked all the same.

Checking a password runs Argon2id, which takes about 64 MiB of memory and
tens of milliseconds of a core, in the thread pool every request shares.
Anyone who can reach the sign-in endpoint, without an account, can send as
many attempts as they like, and every one of them costs that, whether the
limits stopped it or not. A few hundred at once exhaust the memory of a
small home server, and slow every other request.

## Decision

1. **The limits are checked before the password.** Before checking a
   password, the server asks the database, without recording anything,
   whether an attempt for that username and source address would be
   refused now. If it would, the attempt is refused at once with the same
   answer as ADR-0047's, and nothing is recorded. Otherwise the password is
   checked and the attempt recorded with its outcome as before, which
   checks the limits again, so that attempts racing past the first check
   are still refused. This holds wherever a password is checked: signing
   in, and confirming a password to change it or a passkey (ADR-0094).
2. **Two passwords at a time.** The server hashes and checks at most two
   passwords at once, in each API process; others wait their turn. Setting
   a password waits the same way.
3. **The answer does not change.** A refused attempt is answered with
   `auth.rate_limited` and its `Retry-After`, whether the password was right
   or not, as ADR-0047 decided.

This amends ADR-0047 point 1, on when a refused attempt is answered.

## Consequences

- An attempt over a limit costs a database query, not a password check.
- At most two password checks use memory and CPU at once, about 128 MiB;
  a flood of attempts from many addresses, each under its limit, delays
  sign-ins instead of exhausting the host.
- A sign-in may wait behind others under such a flood: sessions already
  open are not affected (ADR-0025).
- The database has one more pre-authentication function, read-only.

## Alternatives considered

- **Recording the attempt before checking the password, and updating its
  outcome after:** one call fewer, but a crash between the two leaves a
  failure counted that never happened, and the function would need a row to
  update.
- **A limit kept in the API's memory:** no query, but each API process would
  count apart, and the limits are already in the database.
- **Lighter Argon2 parameters:** cheaper per attempt, weaker against an
  attacker who steals the hashes, and still unbounded in number.
