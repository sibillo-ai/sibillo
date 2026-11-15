# ADR-0094: How passkeys are checked

- **Status:** Proposed
- **Date:** 2026-11-15
- **Deciders:** @tapionx
- **Related:** ADR-0025, ADR-0047, ADR-0049, ADR-0050, ADR-0065, ADR-0067, AUTH-004, AUTH-005, AUTH-006, AUTH-008, AUTH-010, UX-026

## Context

ADR-0065 decided that passkeys are a second factor on top of the password,
that a tenant admin or an operator command removes a lost one, and that
approvals do not use them. It left open how the server knows which site a
passkey belongs to, how a sign-in in two steps works with device sessions,
cookies and rate limits, what protects a user's passkeys from someone who
holds only their session, and what an administrator sees.

WebAuthn binds each passkey to a relying party, identified by a domain, and
the server must check that each response comes from the expected origin.
Browsers offer passkeys only in a secure context: an `https://` origin, or
`http://localhost`.

## Decision

1. **The origin is configured.** The API reads `SIBILLO_PUBLIC_ORIGIN`, the
   origin users open, such as `https://sibillo.example.org`. Its host is the
   relying party ID, and every registration and assertion must come from
   exactly that origin. Without it, passkeys are unavailable: none can be
   registered, and a user who has some cannot sign in until the operator sets
   it or removes their passkeys. Request headers never decide the origin.
2. **Signing in takes two steps.** `POST /auth/login` checks the password as
   today. For a user without passkeys it creates the device session as
   today. For a user with passkeys it creates no session: it answers with a
   sign-in token and the WebAuthn request options, which allow only that
   user's passkeys. `POST /auth/login/passkey` takes the token and the
   assertion and creates the device session, by token or cookie
   (ADR-0067). The token is 256 random bits, stored as a hash with its
   challenge, valid for 5 minutes and usable once, whether the assertion is
   right or wrong: a failed passkey means entering the password again.
3. **Rate limits cover both steps.** The password step counts as today
   (ADR-0047). A wrong, expired or used sign-in token and a passkey that does
   not verify each count as a failed attempt for the username and the source
   address, and the passkey step is refused over the limits like the password
   step.
4. **The password again to change passkeys.** Registering a passkey and
   removing one of one's own passkeys both need the user's password in the
   request, checked and rate-limited like a sign-in. A stolen session cookie
   then cannot add a passkey of the attacker's or remove the user's own. A
   wrong password is answered with `403`, not `401`, so that clients do not
   take it for an ended session.
5. **Registration is a ceremony of two requests.** The first, with the
   password, returns creation options with a fresh challenge, valid for 5
   minutes and usable once, that exclude the user's existing passkeys; the
   second returns the device's response with a name the user gives the
   passkey. The server asks for no attestation, prefers user verification,
   such as a fingerprint, without requiring it, and accepts ES256, EdDSA and
   RS256 keys. The WebAuthn user handle is the user's identifier, never their
   username.
6. **What is stored.** For each passkey: its credential ID, unique across the
   instance, its public key, its signature counter, its transports, its name,
   when it was created and when it was last used. A counter that goes
   backwards fails the assertion; a counter that stays at zero, as with many
   passkeys that sync, is accepted.
7. **Administrators remove all of a user's passkeys at once,** and see only
   how many there are, not their names. Removing them ends no session.
   The operator command `remove-passkeys USERNAME` removes every passkey of
   any user, the instance admin included, through a function only
   `sibillo_owner` may run, like `setup`.
8. **Sessions already open stay open** when a user registers their first
   passkey. A user who fears their password was stolen revokes their other
   sessions (AUTH-004).
9. **The library.** The server verifies WebAuthn with `webauthn` (py_webauthn),
   a pure Python library maintained by Duo Labs; the web app calls the
   browser's WebAuthn API directly, with no library.

## Consequences

- An instance served at an address other than `SIBILLO_PUBLIC_ORIGIN`, such
  as a LAN address while the origin is the public name, cannot use passkeys
  there; passkeys registered under one origin do not work under another.
- A typo in the origin, or a change of domain, keeps users with passkeys out
  until it is fixed or their passkeys are removed; the operator command is
  the way back.
- A user who signs in with a password and a passkey types the password
  first, every time.
- Two requests and a short-lived row per sign-in: one more table, one more
  pre-authentication function.

## Alternatives considered

- **The origin from the `Host` header or a trusted proxy's
  `X-Forwarded-Host`:** no configuration, but the check that protects against
  phishing would trust what the request says.
- **A signed, stateless sign-in token:** no table, but it could be replayed
  until it expires.
- **Only the session to change passkeys:** simpler forms, but a stolen
  session could replace the second factor.
- **Removing passkeys one by one as an administrator:** finer, but shows the
  admin the names of a member's devices, and a lost phone only needs them
  all gone.
