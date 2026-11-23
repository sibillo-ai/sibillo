# ADR-0122: A redirect address and a client document for each MCP server

- **Status:** Accepted
- **Date:** 2026-11-23
- **Deciders:** @tapionx
- **Related:** ADR-0099, ADR-0100, AGT-019, AGT-030, AGT-031, T-37, T-38

## Context

ADR-0100 gives every `oauth` server of every household one redirect
address, `/mcp-sign-in`, and one Client ID Metadata Document,
`/v1/mcp-client`. A sign-in is found by its `state` alone, and the issuer is
checked only when the authorization server returns it.

That allows a mix-up. A malicious server M of the household, whose
authorization endpoint the attacker controls, sends a user who signs in to
M on to the authorization server H of an honest server S, with Sibillo's
client ID, the shared redirect address, M's `state`, `resource` set to S and
a PKCE challenge of the attacker's. The user approves Sibillo at H, whose
page they trust. H redirects to Sibillo with a code and M's `state`, and
Sibillo sends the code to M's token endpoint. The attacker holds a code of
H and its verifier, and redeems it for a token to S. RFC 9207's `iss`
parameter stops this, but not every authorization server sends it.

RFC 9700 (section 4.4.2) gives the other defense: a redirect address for
each authorization server, and a check that the answer came back at the
address of the server the sign-in was for.

## Decision

1. **A redirect address for each server.** The redirect address of a
   server is `SIBILLO_PUBLIC_ORIGIN` followed by `/mcp-sign-in/{server_id}`.
   Sign-ins of that server send it, and exchange their codes with it. The
   web app's page at that address sends the server's ID with what the
   redirect carried; completion refuses a `state` of a sign-in of any other
   server, before anything is sent to a token endpoint.
2. **A client document for each server.** Sibillo's Client ID Metadata
   Document for a server is at `/v1/mcp-client/{server_id}`, and lists only
   that server's redirect address. A client Sibillo registers dynamically
   for a server registers only that server's redirect address. The shared
   document and the shared redirect address are gone. A client whose ID is
   one of Sibillo's documents takes the document of the server's ID now,
   whatever was stored when it was found.
3. **Given clients name their server's address.** The admin's view of an
   `oauth` server shows its redirect address, to register with the service
   when a tenant admin gives a client by hand. A client given or registered
   before this decision has the old address registered, and fails its
   sign-ins until a tenant admin registers the new one, or saves the server
   again so that Sibillo registers anew.
4. **The issuer is still checked** when the authorization server returns
   it, or said it would.

This amends ADR-0100 points 3, 4 and 5.

## Consequences

- An authorization server that holds Sibillo's client registered for S, or
  given for S, can only send S's sign-ins back to S's address; a code it
  issues reaches only S's token endpoint.
- **Residual risk.** An authorization server that reads Client ID Metadata
  Documents fetches whichever document the request names. A malicious
  server can name its own document, which Sibillo serves, and so still
  obtain a code of an honest authorization server that neither sends `iss`
  nor binds its codes to a client the user chose. It needs a malicious
  server added by a tenant admin (AGT-019), one click of a user, and such an
  authorization server; T-38 records it.
- Servers configured before this decision need their redirect address
  registered again, once.

## Alternatives considered

- **Requiring `iss`:** complete against the mix-up, but refuses honest
  authorization servers that do not send it.
- **Keeping one redirect address and checking `resource`:** the code says
  nothing of the resource it was issued for.
- **Refusing Client ID Metadata Documents without `iss`:** closes the
  residual risk, at the cost of Home Assistant and other servers whose
  authorization server reads documents but sends no `iss`; a later ADR can
  choose it once the MCP authorization specification requires `iss`.
