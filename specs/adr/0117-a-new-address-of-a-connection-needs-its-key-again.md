# ADR-0117: A new address of a connection needs its key again

- **Status:** Accepted
- **Date:** 2026-11-23
- **Deciders:** @tapionx
- **Related:** ADR-0051, ADR-0069, ADR-0099, AGT-030, MOD-002, MOD-008, MOD-009, MOD-013, UX-025

## Context

A connection's API key is write-only (MOD-008, ADR-0069): once given, no
admin can read it back. A tenant admin can change a connection's address,
and the server tests a new address before saving it (MOD-013). The test is
made with the stored key, so a change of the address alone sends the key, in
an `Authorization` header, to the new address, even when the test fails and
nothing is saved.

A household can have several tenant admins. One who never knew the key can
point the connection at a server of their own, read the key from its log,
and put the address back. The key is write-only only in name.

Remote MCP servers have the rule already: a new address makes every
credential given for the server unusable (AGT-030, ADR-0099).

## Decision

1. **A stored key is sent only to the address it was given for.** A change
   of a connection's address that has a stored key MUST also give the key:
   a new one, or `null` to remove it. Otherwise the change is refused with
   `request.validation_failed` at `/api_key`, code
   `required_with_new_address`, before anything leaves the server. An
   address equal to the stored one, after the trailing slash is removed, is
   no change.
2. **Nothing else changes.** A connection without a key moves as before; a
   new key alone is tested at the stored address; the test of a saved
   connection uses its stored address and key.
3. **Clients ask for the key again.** When a tenant admin changes the
   address of a connection that has a key, the key field is required unless
   they remove the key, and its hint says that a new address needs the key
   again (UX-025).

## Consequences

- No tenant admin can make the server send a key to an address the key was
  not given for. An admin who moves a connection must know its key, or
  remove it.
- Moving a server that needs a key is one field more for the admin who
  moves it.

## Alternatives considered

- **Testing the new address without the key, and removing the key when the
  change is saved:** no field more, but a server that needs no key answers,
  and the key disappears without the admin noticing; one that needs it fails
  with "the credentials were rejected", which does not say why.
- **Keeping the key bound to the connection, whatever its address,** as
  today: the key is write-only only against admins who do not try.
