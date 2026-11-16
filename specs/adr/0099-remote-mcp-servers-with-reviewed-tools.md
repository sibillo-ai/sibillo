# ADR-0099: Remote MCP servers with reviewed tools and personal credentials

- **Status:** Proposed
- **Date:** 2026-11-16
- **Deciders:** @tapionx
- **Related:** ADR-0033, ADR-0051, ADR-0061, ADR-0064, ADR-0069, ADR-0081, ADR-0087, ADR-0090, ADR-0096, ADR-0100, AGT-002, AGT-003, AGT-004, AGT-005, AGT-006, AGT-007, AGT-008, AGT-013, AGT-014, AGT-018, AGT-019, AGT-028, AGT-029, AGT-030, CNV-013, MOD-002, MOD-009, TEN-007, UX-029, T-21, T-29, T-37

## Context

ADR-0064 lets a tenant admin add remote MCP servers to their household and
says that every call to one is approved. It leaves open how their tools
reach a run, and five of its consequences collide with decisions taken since,
or with the servers people want to use:

- **Credentials.** ADR-0064 gives a server one credential, entered by the
  tenant admin, so that every user acts on the service as one account. Most
  services worth connecting know each person: GitHub, Notion, Linear, a
  calendar, even Home Assistant, whose tokens each belong to one of its users
  and whose logbook names who turned a light on. One shared credential would
  let Alice read Bob's private repositories and act in his name, against
  TEN-007.
- **Descriptions and the trifecta rule.** ADR-0064 calls a server's tool
  descriptions untrusted content, and rightly: a server can carry injected
  instructions in them as well as in its results (T-29). But a run with
  untrusted content asks before every web or command tool (ADR-0090 point 3),
  and a server's descriptions are in every run its tools are offered to. Read
  literally, a household that connects Home Assistant would be asked before
  every search and command in every conversation.
- **Tools that change.** A server decides its tools, and can change their
  descriptions at any time, after anyone looked at them.
- **Switches.** ADR-0087 gives the user one switch per tool, by a name of the
  API's `ToolName`. A server's tools are not known to the contract, and
  come and go.
- **People.** A household may want a server for the adults only: Home
  Assistant with the door lock, but not for the children.

Pydantic AI 2.64 brings an MCP client, `MCPToolset`, over Streamable HTTP,
which takes an HTTP client of ours, a prefix for its tools' names, and a
filter of the tools it offers. The old HTTP+SSE transport is deprecated by
the protocol.

## Decision

1. **Streamable HTTP, tools only.** Sibillo is an MCP client of servers
   reached over Streamable HTTP, through `MCPToolset`. It uses their tools and
   nothing else: no resources, prompts, sampling, elicitation, roots or task
   execution, and the server's `instructions` never reach the model. A tool
   that requires task execution cannot be used.
2. **A server of a household** has a name, shown to people; a **prefix**,
   from 1 to 20 lowercase letters, digits and single underscores, starting
   with a letter, unique in the household and fixed once the server is
   added; an address; and an **authentication**, chosen by the tenant admin:
   `none`, for a server that needs no credential; `token`, for one where each
   user gives a token of their own; or `oauth`, for one where each user signs
   in to the service (ADR-0100). A household has at most 20 servers. A tenant
   admin can switch a server off for everyone. This amends ADR-0064 point 3:
   there is no credential of the household.
3. **Credentials are each user's own** (AGT-030). A user who wants the tools
   of a `token` or `oauth` server gives their own credential: a token they
   paste, such as a Home Assistant long-lived access token or a GitHub
   personal access token, or one Sibillo obtains when they sign in
   (ADR-0100). It is sent only to that server's address, as a bearer token in
   `Authorization`, and only in that user's runs and requests. It is stored
   in a private row of that user, encrypted with AES-256-GCM under
   `SIBILLO_SECRET_KEY` with the row's ID as associated data, as an API key
   of a connection is (MOD-002, ADR-0051); it is never returned by the API,
   and neither tenant admins nor other users can read it. A token is tried
   when given, by listing the server's tools, and refused with
   `mcp_server.unauthorized` when the server refuses it; nothing of that
   listing is kept. A user can remove their credential at any time.

   A user who has no credential, or whose credential the server refuses or
   Sibillo cannot renew, is not offered the server's tools, and the run's
   instructions say that the user has not connected their account to that
   server, so that the model can tell them where to do it. A new address,
   authentication or OAuth client of a server starts a new **generation** of
   it: every credential of an older generation is ignored, and deleted the
   next time its owner's requests or runs meet it, since the server may now
   be another one.
4. **Where a server may be** is ADR-0064 point 4, with the rules of
   connections (ADR-0069): an address set by a user who is the instance admin
   may be private and `http`; any other must be `https`, and is checked at
   connection time through the transport of ADR-0061, without redirects. A
   new address set by a user who is not the instance admin is public again.
   Failures say which step failed, without what an internal service
   answered. Connecting to a server, or to its authorization server, outside
   a run (to add, change or refresh a server, to try a token, or to sign
   in) is limited to 20 times a minute per tenant, as connection tests are
   (T-31).
5. **Tools are named `<prefix>__<tool>`** for the model, such as
   `home__HassTurnOn`. No tool of Sibillo has a double underscore, so a
   server's tools never take the name of one, nor of another server's. A
   name that does not fit `^[A-Za-z0-9_-]{1,64}$` once prefixed cannot be
   used.
6. **A tenant admin reviews a server's tools** (AGT-028). When a `none`
   server is added or its address changes, and when a tenant admin refreshes
   a server, Sibillo connects, lists its tools and keeps the list: each
   tool's name, `title`, `description`, `inputSchema` and `annotations`. A
   `token` or `oauth` server is listed with the credential of the admin who
   refreshes it, so its tools are first listed once that admin has given
   theirs; an admin without one is refused with
   `mcp_server.credential_missing`. The admin sees every tool, and accepts
   those the household may use, one by one: an acceptance keeps the tool's
   `title`, `description` and `inputSchema` as the admin saw them, by a
   digest of their canonical JSON, and is refused when the listing has
   changed since. A new address clears every acceptance, since it may be
   another server. A tool with a description of more than 4,000 characters
   or an input schema of more than 16 KiB cannot be accepted, nor can more
   than 100 tools of one server.

   At the start of each run, the worker connects to each server the run may
   use (point 8), with the user's credential, lists its tools, and offers
   only the accepted ones whose listing is still, field for field, what the
   admin accepted. A server may list other tools to other users, by what
   their accounts allow; each user is offered only the accepted tools their
   own listing has unchanged. A tool that changed, or a new one, is not
   offered until its admin accepts it again; a refresh shows the admin which
   tools changed, and how. A resumed run lists again, and an approved call to
   a tool that is no longer offered as accepted does not run: the model is
   told the tool changed.
7. **Reviewed descriptions do not make a run untrusted.** This refines
   ADR-0064 point 6. A description a tenant admin accepted, which cannot
   change without them, is no more an injection risk than the descriptions of
   untrusted skills that ADR-0096 point 7 lets into every run: the worker's
   instructions name each server and its prefix, and say that its tools come
   from a service outside Sibillo. Every tool of a server is declared with
   the classes `reads_private_data`, `ingests_untrusted` and
   `external_communication` (AGT-005): its results are untrusted content
   (AGT-003), so the trifecta rule applies from the first result on. MCP's
   tool annotations, such as `readOnlyHint`, are hints from the server: the
   admin sees them, and they grant nothing.
8. **Who uses a server.** Every user of the household may, unless a tenant
   admin denies them the server: tool permissions gain a third kind of
   subject, a server, whose only setting is `deny` (AGT-029). A denied server
   is never offered to that user, its tools are listed to them as off and
   locked, as a denied tool is (ADR-0090 point 5), and they cannot give it a
   credential. A capability class set to `deny` takes away every server's
   tools, as it takes away every other tool of that class; `ask` and `allow`
   change nothing, since every call is asked anyway (AGT-018).
9. **One switch per server.** A user switches a whole server on or off, in a
   conversation and in their defaults, beside the switches of ADR-0087; the
   tool settings show each server as a group of its own, with its accepted
   tools listed under it, and whether the user's account is connected. The
   conversation and the user's settings store the IDs of the servers that
   are off, so that a server added later is on; the ID of a server that no
   longer exists is ignored. A new conversation copies the user's defaults,
   and a fork copies its conversation's, as for tools.
10. **Every call is approved** (AGT-018, ADR-0090 point 4): with the reason
    `device`, and only Deny and Allow once; no tool permission and no
    allowance lifts it. The approval request shows the tool's title, or its
    name, and its server's name; the arguments in full; and as the
    destination the server's name and host. The call runs from the worker,
    with the run's HTTP client for that server and the user's credential;
    its audit event names the prefixed tool and records the attempt before
    the call (AGT-008), as for every tool with external effects.
11. **Calls and failures.** A server that cannot be reached when a run
    starts, or that does not list its tools within 10 seconds, is left out
    of that run: its tools are not offered, and the instructions say the
    server could not be reached, so that the model can tell the user. A call
    that fails, times out after `SIBILLO_MCP_CALL_SECONDS`, or that the
    server answers with an error, is a failed tool call the model sees.
    Results reach the model through the output limits (AGT-014): text, and
    images, as other tools' results do.
12. **API.** Tenant admins manage servers at `/tenant/mcp-servers`: add one,
    which for `none` connects and lists its tools first and is refused with
    `mcp_server.unreachable` when it cannot, and for `oauth` finds and
    registers with its authorization server first (ADR-0100); list, read,
    change and remove them; refresh one; and replace the accepted tools of
    one, with the digests they saw. `GET /mcp-servers`, beside `GET /tools`,
    lists to each user the household's servers that are on, with their
    accepted tools, whether the user is denied them, and the state of the
    user's credential; it never shows a credential or a full address. Each
    user gives and removes their credential at
    `/mcp-servers/{server_id}/credential`, and signs in at
    `/mcp-servers/{server_id}/sign-in` (ADR-0100). Tool permissions gain
    `servers`; user settings, conversations and their requests gain
    `disabled_servers`.
13. **Tests serve their own MCP server** on the loopback address, added by
    a user who is the instance admin, as the test model is (ADR-0069), whose
    tools the tests script and change, and which checks the tokens it is
    sent and acts as its own authorization server (ADR-0100).

## Consequences

- A household connects Home Assistant, GitHub, an error tracker or a
  calendar server, and the assistant uses the tools their makers publish,
  asking before every call.
- Every person acts on a service as themselves: the service's own
  permissions and logs apply to them, and Sibillo's audit names them too. A
  child without an account on the service has none of its tools, whatever
  Sibillo's settings say.
- Each person connects their own account once per server, and a token
  pasted by hand is theirs to create with the least rights it needs; the app
  says so. Servers that only sign people in with OAuth need ADR-0100.
- Conversations stay quiet: offering a server's tools asks nothing, and a
  run is asked about the web and commands only once a server's result, or
  other untrusted content, is in it.
- A server that changes its tools loses them until its admin looks again. A
  server that changes often makes work for its admin; that is the price of
  knowing what the model is told.
- The tenant admin carries a judgement no other setting asks of them:
  whether a tool's description is fit for the household's runs. The review
  page shows every field the model would read. To review a `token` or
  `oauth` server, the admin needs an account on its service.
- A service the household reaches through one shared account, such as a
  device with a single API key, has no place yet: each user would have to
  paste the same key.
- The data egress policy (MOD-003) is about models, and does not apply to
  servers: what a call sends, and where, is shown on its approval.
- `ToolName` stays the list of Sibillo's own tools; the tool switches gain
  servers, and the test of ADR-0087 point 5 compares Sibillo's tools only.
- The server's package gains `pydantic-ai-slim`'s `mcp` extra, which brings
  the MCP SDK and FastMCP.

## Alternatives considered

- **One credential of the household per server,** as ADR-0064 had it:
  simple, and enough for a device with one key, but every user would act on
  the service as whoever created the token, and see what that account sees.
  It can be added later as a fourth authentication, if a household needs it.
- **Users adding servers of their own:** each user could point the control
  plane at any address and bring descriptions nobody reviewed; kept for
  later, as ADR-0064 decided. Personal credentials give each person their
  own account without it.
- **Deleting other users' credentials when an address changes:** credentials
  are private rows that a tenant admin cannot touch; a generation reaches
  the same end without a privileged path.
- **Descriptions always untrusted:** offering a server's tools would make
  every run untrusted, and the web and commands would ask in every
  conversation while a server is on; the approval fatigue ADR-0090 was
  written to avoid.
- **Accepting a whole server at once, without pinning:** a server could
  change its descriptions the day after, and nobody would see it (a "rug
  pull").
- **One switch per tool:** more control, but a list that grows with every
  server and names that change with the server; the tenant admin already
  chooses which tools the household has.
- **Allowing a server per user with `allow`, `ask` and `deny`:** `ask` and
  `allow` would mean the same, since every call is asked.
- **Legacy HTTP+SSE as well:** deprecated by the protocol; servers that
  speak only it are few, and can sit behind a proxy that speaks Streamable
  HTTP.
- **Any authentication header:** a bearer token covers Home Assistant, the
  hosted servers and OAuth.
- **The server's `instructions` in the run, reviewed like descriptions:**
  more text for the admin to review, for little the descriptions do not
  already say.
