# ADR-0128: Outbound requests are bounded, and checked by what they reach

- **Status:** Accepted
- **Date:** 2026-11-23
- **Deciders:** @tapionx
- **Related:** ADR-0061, ADR-0064, ADR-0066, ADR-0069, ADR-0072, ADR-0099, ADR-0100, ADR-0117, AGT-019, AGT-028, AGT-030, AGT-031, API-006, MOD-002, MOD-009, MOD-010, MOD-013, OBS-003, T-11, T-15, T-21, T-27, T-29, T-31, T-38

## Context

The control plane makes requests to addresses that tenant admins choose:
model connections, speech, remote MCP servers and their authorization
servers. A security audit of those requests found:

- **No bound on what comes back.** Responses are read whole, with a timeout
  per read but none overall, so an endpoint can make the API or the worker
  hold as much memory, for as long, as it likes. Every tool a server lists is
  stored, beyond the limits.
- **The instance admin's exemption reaches too far.** An address the
  instance admin sets may be private (ADR-0064 point 4), but OAuth discovery
  then follows every address the server names, for metadata, the issuer,
  registration and tokens, to the household's network.
- **Moving an MCP server keeps its client secret,** and sends it to the
  authorization server of the new address, as ADR-0117 found for connection
  keys.
- **Limits that do not limit.** Creating and updating a connection run its
  test without the rate limit, and every listing of models starts a new
  refresh of a stale connection.
- **Tests say too much.** A connection test shows a tenant admin the
  addresses a name resolves to, and 500 characters of a private server's
  answer.
- **Speech errors pass the provider's text** to the user and the logs, and
  an upload's file extension reaches a `Content-Type` unchecked.
- **Some non-global ranges pass as public:** `::/96`, `fec0::/10`,
  `192.88.99.0/24`, depending on the Python release.
- **A tenant admin can label a remote connection `local`,** which the data
  egress policy trusts (MOD-003, ADR-0066).
- **Smaller gaps:** the checking transports leave plain `http` to their
  callers; addresses may carry a user and password, kept in clear; a cost
  a provider reports is not checked; an authorization server's `expires_in`
  and `error` are unbounded; a user's pending sign-ins are not capped; a run
  that started before a server changed deletes the user's fresh credential;
  the MCP library follows redirects within the server's origin, though the
  specs say no request follows one; tool descriptions may hide invisible or
  bidirectional characters from the review; some provider errors are logged
  with their content; ADR-0072's table does not list authorization servers.

## Decision

1. **Every response is bounded.** The clients of connections, speech, MCP
   servers and their authorization servers cap the bytes of a response and
   its total time, in their transport: 64 MiB and 30 minutes for a model's
   answer, 16 MiB and 2 minutes for anything else. A response over either
   fails as the connection would. Of a listing with more tools than a server
   may offer, at most that many are kept, marked `too_many_tools`.
2. **The exemption covers the address the instance admin typed.** Requests
   to the origin of that address may reach any address. A request an OAuth
   flow makes to any other origin, discovered from the server, goes through
   the checking transport, whoever set the server.
3. **Moving an MCP server needs its client secret again.** A new address of
   an `oauth` server with a client secret given by a tenant admin must come
   with the secret again, or with a new client, and is refused otherwise,
   before any request.
4. **Limits limit.** Creating and updating a connection count toward the
   tenant's limit of tests. One refresh of a connection's models runs at a
   time.
5. **Tests show details to the instance admin only.** A tenant admin who is
   not the instance admin sees the steps and the reason of a test, without
   resolved addresses or excerpts of the answer.
6. **Speech errors are Sibillo's.** A failed speech request is logged with
   its HTTP status only, and answers a fixed reason. An upload's extension
   must be 1 to 5 lowercase letters or digits, or `webm` is assumed.
7. **Non-global ranges are named.** Besides `is_global`, `::/96`,
   `fec0::/10` and `192.88.99.0/24` are refused, and a test of literal
   addresses keeps the judgement fixed across Python releases.
8. **Only the instance admin's addresses may be `local`.** A connection to
   an address a tenant admin who is not the instance admin set is `remote`;
   asking for `local` is refused.
9. **Smaller gaps close.**
   - The checking transports refuse plain `http` themselves.
   - Addresses with a user or password are refused.
   - A reported cost must be finite and not negative, or it is unknown.
   - An authorization server's `expires_in` is taken up to a year, and its
     `error` up to 200 characters.
   - A user has at most 10 pending sign-ins; a new one deletes the oldest.
   - A credential is deleted as unusable only when its generation is still
     the server's, as the database says.
   - The specs say what the code does: the MCP library follows redirects
     within the server's origin only.
   - A tool whose name, title or description holds invisible or
     bidirectional control characters is listed with the problem
     `hidden_characters`, and cannot be accepted.
   - Errors of providers are logged without their content.
   - ADR-0072's table lists the authorization servers of remote MCP
     servers.
10. **One key, recorded as a risk.** Every secret is encrypted with one key,
    without a version, which also derives the notification key; rotating it
    needs every secret re-encrypted. The threat model says so; a later ADR
    can add key versions.

This amends ADR-0064 point 4, ADR-0066, ADR-0072 point 1 and ADR-0100
point 6.

## Consequences

- An endpoint a tenant admin added can no longer exhaust the API's memory
  or hold a request open for ever.
- An instance admin's public server cannot lead Sibillo into the household's
  network.
- Very long model answers over 64 MiB fail; none is near that today.

## Alternatives considered

- **A cap in each caller:** many places to keep in step; the transport is
  where every request passes.
- **Refusing every OAuth address off the server's origin:** breaks services
  whose authorization server is elsewhere, as GitHub's is.
