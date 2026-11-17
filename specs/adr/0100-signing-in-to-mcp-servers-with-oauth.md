# ADR-0100: Signing in to remote MCP servers with OAuth

- **Status:** Proposed
- **Date:** 2026-11-16
- **Deciders:** @tapionx
- **Related:** ADR-0025, ADR-0051, ADR-0061, ADR-0064, ADR-0067, ADR-0069, ADR-0094, ADR-0099, AGT-019, AGT-030, AGT-031, MOD-002, MOD-009, UX-029, T-31, T-37, T-38

## Context

ADR-0099 gives each user their own credential for a remote MCP server. Many
hosted servers, such as Notion's, Linear's and Atlassian's, accept no token
a person can paste: they sign people in with OAuth. Others accept both, and a
person who is not technical will not create a personal access token.

The MCP authorization specification (revision 2025-11-25) makes a server an
OAuth 2.1 resource server. A client that is refused with 401 finds the
server's protected resource metadata (RFC 9728), and from it an
authorization server, whose metadata (RFC 8414, or OpenID Connect discovery)
gives its endpoints. The client signs the person in with the authorization
code flow and PKCE, names the server as the `resource` the token is for
(RFC 8707), and is registered with the authorization server beforehand, by
a Client ID Metadata Document that the authorization server fetches, or by
dynamic client registration (RFC 7591).

Sibillo is a web application at `SIBILLO_PUBLIC_ORIGIN` (ADR-0094), often
reached only from the household's network or a private network, so an
authorization server may be unable to fetch anything from it. The browser
reaches both. The MCP SDK has an OAuth client, `OAuthClientProvider`, built
for an application that waits for the redirect in the same process; the
control plane gets the redirect in another request, maybe in another
process.

## Decision

1. **The authorization code flow with PKCE, for each user.** A user signs in
   to an `oauth` server in their browser, and Sibillo keeps the tokens as
   that user's credential for the server (ADR-0099 point 3). Sibillo is the
   OAuth client; its own sessions are not involved.
2. **Discovery when the server is set.** When a tenant admin adds an `oauth`
   server, or changes its address, authentication or client, Sibillo
   connects without a credential and expects 401. It reads the protected
   resource metadata at the address the answer's `WWW-Authenticate` names in
   `resource_metadata`, or else at the well-known addresses of RFC 9728 for
   the server's address, path first. Its `resource` must be the server's
   address, or a resource that contains it: the same scheme, host and port,
   no query, and a path that is the server's path or a prefix of it ending
   at a `/` boundary. Home Assistant names its origin for its server at
   `/api/mcp`. It takes the first authorization server the metadata lists, and
   reads its metadata at the well-known addresses of RFC 8414 and of OpenID
   Connect, in the order the MCP specification gives; its `issuer` must be
   that authorization server. The metadata must offer the `code` response
   type and the `S256` code challenge method. Sibillo keeps the resource, the
   issuer, the
   authorization and token endpoints, whether the issuer is returned with
   the code (RFC 9207), and the scope to ask for: the `scope` of the 401
   answer, or else the `scopes_supported` of the resource metadata, or else
   none. When anything is missing or does not match, the server is refused
   with `mcp_server.oauth_unsupported`, saying which step failed.
3. **One client per server,** chosen in the order of the MCP authorization
   specification. A tenant admin may give a client ID, and a client secret,
   registered with the service by hand, as GitHub requires. Otherwise, when
   the authorization server's metadata says
   `client_id_metadata_document_supported` and `SIBILLO_PUBLIC_ORIGIN` is
   `https`, the client ID is the address of Sibillo's own Client ID Metadata
   Document, `SIBILLO_PUBLIC_ORIGIN` followed by `/v1/mcp-client`, which the
   authorization server fetches, as Home Assistant does. The document, served
   without authentication, names the client "Sibillo" and gives its
   `client_id`, its redirect address, the grants `authorization_code` and
   `refresh_token`, and no client authentication (`none`); it holds nothing
   secret. Otherwise Sibillo registers dynamically, when the authorization
   server offers it, with the same metadata. None of the three is refused
   with `mcp_server.oauth_unsupported`. The client serves every user of the
   household. A client secret is encrypted like a token (ADR-0099 point 3),
   with the server's ID as associated data, and never returned; with one,
   Sibillo authenticates to the token endpoint with `client_secret_basic`,
   or with `client_secret_post` when only that is offered.
4. **The redirect lands in the web app.** The redirect address is
   `SIBILLO_PUBLIC_ORIGIN` followed by `/mcp-sign-in`, a page of the web
   app that sends what it received to the API with the user's session, and
   then shows the server's settings. Without `SIBILLO_PUBLIC_ORIGIN`,
   `oauth` servers cannot be added. Since the redirect passes only through
   the browser, Sibillo need not be reachable from the internet.
5. **A sign-in is bound to its user.** `POST
   /mcp-servers/{server_id}/sign-in` starts one: a `state` of 32 random
   bytes, of which only a hash is kept, and a PKCE code verifier, bound to
   the user, the server and its generation, valid for 10 minutes and used
   once. It answers the authorization address, with `response_type=code`,
   the client ID, the redirect address, the `state`, the `S256` code
   challenge, the resource kept at discovery as `resource`, and the scope. The
   client opens it in the browser. `POST /mcp-sign-in` completes it
   with what the redirect carried: the `state` must be a pending sign-in of
   the same user, which is deleted at once; an `error` ends it; when the
   authorization server returns its issuer, or said it would, `iss` must be
   that issuer. Sibillo then exchanges the code at the token endpoint, with
   the code verifier, the redirect address and the `resource`, and requires
   a bearer access token. It tries the token by listing the server's tools,
   as for a pasted token, and keeps the access token, its expiry, and the
   refresh token if any. Any failure is `mcp_server.sign_in_failed`, saying
   which step failed.
6. **Where OAuth requests go.** The requests Sibillo itself makes for
   OAuth, for metadata, registration and tokens, follow the server's address
   rules (ADR-0099 point 4): private and `http` only when the server's
   address was set by the instance admin, else public `https` checked at
   connection time, without redirects. The authorization address, which only
   the browser opens, must be `https`, or `http` under the same condition.
   Outside runs, these requests count toward the limit of ADR-0099 point 4.
7. **Tokens are renewed once, under a lock.** When an access token has
   expired or expires within 60 seconds, or a server answers 401, the worker
   or the API renews it with its refresh token, holding a lock on the
   credential's row, so that two runs of the user renew it once; a new
   refresh token replaces the old one. A call answered 401 is made again
   once with the renewed token, since the server did not perform it. When
   there is no refresh token, or renewing fails, the credential becomes
   expired: the server's tools are not offered to the user until they sign
   in again, and the run's instructions say so. A server that answers
   `insufficient_scope` is a failed call; signing in again asks for the
   scope once more.
8. **Signing out forgets.** Removing the credential deletes the tokens.
   Sibillo does not revoke them at the service.
9. **Tests sign in to their own server.** The test MCP server is also its
   authorization server: it serves the metadata, registers clients
   dynamically and knows a client registered by hand, issues, expires,
   renews and rotates tokens, and can be scripted to misbehave, as by
   returning another issuer, pointing its metadata at a private address, or
   offering no `S256` (ADR-0099 point 13).

## Consequences

- Household members connect GitHub, Notion or Linear with the sign-in page
  they know, and never handle a token.
- Sibillo carries an OAuth client of its own: discovery, registration, the
  flow, and renewal. The MCP SDK's models of the metadata and tokens are
  used; its client provider is not.
- A sign-in starts from a client that can open a browser and reach
  `SIBILLO_PUBLIC_ORIGIN`; a native client finishes it in the web app.
- Tokens stay valid at the service after a user removes them, until they
  expire or the user revokes them there; the app says so.
- A household's admin adds Home Assistant, or another service that reads
  Client ID Metadata Documents, with its address alone: the service fetches
  Sibillo's document, so it must reach `SIBILLO_PUBLIC_ORIGIN`, which a
  service on the household's network usually does. An instance opened only
  at `http://localhost` cannot use them, since a client ID must be `https`.
- A token asked for a resource that contains the server, such as Home
  Assistant's origin, is valid at every address under it, as the service
  chose. The resource never reaches past the server's own origin, and no
  further up its path than a `/` boundary.
- Servers that need a scope granted step by step cannot be signed in to
  yet. Servers of the earlier protocol
  revision, without protected resource metadata, can be used with `token`.

## Alternatives considered

- **The MCP SDK's `OAuthClientProvider`:** it keeps the flow's state in the
  process that waits for the redirect; Sibillo's redirect arrives as another
  request, and tokens live in the database, renewed by several workers.
- **A redirect to an API endpoint, authenticated by the session cookie:**
  works for the web app only, and turns a `GET` into a change of state;
  posting from the web app works for every client and keeps the API's rules.
- **Client ID Metadata Documents only:** the specification's preferred way,
  and Home Assistant's, but a hosted service must fetch the document from
  Sibillo, which a household instance often does not expose to the
  internet; registration and given clients remain beside it.
- **A `resource` identical to the server's address only (RFC 9728,
  section 3.3):** the strictest reading, but it refuses Home Assistant, whose
  metadata names its origin. A resource that contains the server on the same
  origin is no broader than the service itself declares, and the MCP Python
  SDK's client accepts it too (`check_resource_allowed`), asking for the
  resource its metadata names.
- **The server's address as `resource` in requests, whatever the metadata
  names:** an authorization server that checks resource indicators
  (RFC 8707) knows the resource of its metadata, not the server's address.
- **The origin itself as Home Assistant's client ID, given by hand:** works
  with its IndieAuth sign-in, but asks the admin to know it.
- **Signing in once for the household:** the shared credential ADR-0099
  rejects.
- **Revoking tokens when a user removes them (RFC 7009):** worth adding, but
  not every authorization server offers it, and forgetting the token already
  stops Sibillo from using it.
