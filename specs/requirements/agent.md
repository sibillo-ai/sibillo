# AGT — Agent and tools

How the agent acts, and the controls around it. Background: ADR-0012,
ADR-0033, ADR-0090, threat model T-08 to T-10.

## AGT-001: All actions through mediated tools

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** design

The agent MUST act only by invoking mediated tools executed by the control
plane. There MUST NOT be any other way for the model to act on the outside
world.

## AGT-002: Per-user tool permissions

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

A tenant admin MUST be able to set each tool, or each tool capability class,
to allowed, asked or denied for each user of the tenant; without a setting, a
tool follows its approval default (AGT-006). A setting for a tool MUST win
over the settings of its classes, and among its classes the strictest MUST
win. A denied tool MUST NOT be offered to the model for that user, a call to
it MUST be refused, and the user MUST NOT be able to switch it on
(CNV-013). An asked tool MUST require approval for every call. An allowed
tool MUST NOT require approval by default, but MUST still follow AGT-004,
AGT-006 for the `irreversible` and `physical` classes, and AGT-018
(ADR-0090).

## AGT-003: Content provenance

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** unit

Every piece of content entering a run MUST be labeled as trusted (written by
the user or the system) or untrusted (web content, received messages,
external files, sandbox output, connector data from third parties). The
results of tools in the `ingests_untrusted` class, attachments and files
of the file library given to a run, untrusted memory items (MEM-008), and
the loaded bodies of untrusted skills (AGT-025), MUST be untrusted; the user's messages,
their answers to questions (AGT-015) and the instructions MUST be trusted. A
run MUST count as having untrusted content when the conversation's active
path, up to and including that run, holds any, also after compaction and in
a fork (ADR-0090).

## AGT-004: Breaking the lethal trifecta

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration, eval

In a run with untrusted content (AGT-003), every invocation of a tool in the
`external_communication` class MUST require explicit user approval, unless
the user allowed it earlier for that turn or that conversation. One approval
MUST cover the web and command tools `web_search`, `read_page`,
`run_command` and `start_command` together, and MAY cover them for the rest
of the turn or for the conversation, as the user chooses; other tools are
approved one by one (ADR-0090).

## AGT-005: Capability classes

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** design

Every tool MUST declare its capability classes among `reads_private_data`,
`ingests_untrusted`, `external_communication`, `irreversible` and `physical`,
possibly none, and its approval default, allowed or asked. A design test
MUST fail when a registered tool has no declaration, and MUST check the
declarations of the tools listed in ADR-0090.

## AGT-006: Approval for consequential actions

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

Tools in the `irreversible` or `physical` classes MUST require explicit user
approval for every invocation, and an approval MUST cover only that
invocation. Tools in the `external_communication` class MUST be asked by
default, unless ADR-0090 or a later ADR records why one is allowed by
default. For a tool asked by default or by a tool permission (AGT-002), the
user MAY allow it once or in that conversation. Allowances in a
conversation MUST be created only by answering an approval request
(AGT-012), MUST be shown with the conversation, MUST be withdrawable by its
user, and MUST NOT be copied into a fork (ADR-0090).

## AGT-007: Approvals fail closed

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

An approval request that is not answered within 24 hours, or that cannot be
delivered, MUST be treated as denied: a scheduled job MUST resume the
conversation with its pending approvals denied and its pending questions
declined. A denied call MUST NOT run, and the model MUST be told the user
denied it. The approval request MUST show the tool, its arguments in full,
what the call does, the data involved and its destination, and why it needs
approval (ADR-0090).

## AGT-008: Audit events visible to the user

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

Every tool invocation, including calls that were denied, expired or refused,
MUST produce an audit event (tool, time, run, conversation, approval outcome
and its scope) that the user it acted for can view. Audit events MUST NOT
hold the call's arguments or results, MUST outlive the conversation, and
MUST be deleted with their user. Tools in the `external_communication`,
`irreversible` or `physical` classes MUST record an idempotency key for each
call before it runs, so that a call that may have run twice after a crash
(ADR-0034) is visible as such (ADR-0090).

## AGT-009: Durable runs

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

A run MUST execute independently of the client connection that started it,
and every event of the run MUST be persisted in order, so that a client can
disconnect and later receive everything that happened (ADR-0034).

## AGT-010: Runs are never silently lost

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

If the process executing a run stops before the run completes, the run MUST
be either resumed, retried or marked as failed with an event visible to the
user.

## AGT-011: Command execution tool

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

The agent MUST have mediated workspace tools that run commands and read,
write and edit files in the sandbox of the conversation it acts in,
returning command output and exit codes (ADR-0035, ADR-0078). The tools MUST
NOT be able to target any other conversation's sandbox.

## AGT-012: Approvals verified against stored requests

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** security

Approval decisions MUST be applied only to approval requests the server
stored for that conversation and that are still pending. Decisions referring
to unknown, already resolved or expired requests MUST be rejected, and the
tool, arguments and destination shown to the user MUST come from the stored
request (ADR-0033). A decision MUST NOT allow more than the request offered:
a scope the request did not offer MUST be rejected, and an allowance MUST
NOT be created in any other way (ADR-0090).

## AGT-013: No host-side execution through framework capabilities

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** design

Framework capabilities that execute commands, fetch URLs, search the web
locally or connect to MCP servers MUST NOT run in the control plane. They MUST
run in the user's sandbox or use provider-native tools (ADR-0030, ADR-0035).
There are two exceptions. Remote MCP servers over HTTP added by a tenant admin
(AGT-019): the control plane calls them as a client, through the address
rules of ADR-0064, and never starts MCP programs. Web search (AGT-020): the
worker sends queries to the instance's search service, and nothing else
(ADR-0075).

## AGT-014: Bounded tool output

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

A tool result larger than a configured limit MUST NOT be sent to the model in
full. The model MUST receive a bounded excerpt and a way to read the rest,
which is kept in the sandbox's scratch folder until the sandbox stops
(ADR-0043, ADR-0076).

Rationale: command output and web pages can fill the context window in one
call.

## AGT-015: Questions to the user

- **Status:** implemented
- **Priority:** SHOULD
- **Phase:** 1
- **Verification:** integration

The agent SHOULD be able to ask the user structured questions during a run,
each with choices, one or several of which the user picks; the user MAY
answer in their own words instead, or decline. A question MUST end the run
with an interrupt, like an approval, and the answer MUST start a new run that
continues it (ADR-0033, ADR-0043, ADR-0083). The server MUST build what the
model receives from its own stored question and the user's choice, and MUST
refuse answers to questions that are not pending. While a question is
pending, the conversation MUST NOT take a new message. Answers are user
input, not tool output: they carry the user's provenance (AGT-003).

Rationale: journey J7.

## AGT-016: Automatic compaction

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration, eval

When the history of a run would exceed 80% of the context window of the
conversation's model, the system MUST compact the history sent to the model:
the conversation's model summarizes the oldest turns, and the most recent
ones stay as they are. The context window comes from the provider or, for a
connection to the household's own server, from the connection, which a
tenant admin can set. Compaction MUST NOT change the stored conversation,
which the user can still read, rewind and fork in full (ADR-0041, ADR-0073).

Rationale: journeys J7 and J12.

## AGT-017: Skills

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration, security

A user MUST be able to create and edit skills in the open Agent Skills
format, a folder with a `SKILL.md` file and optional bundled files; to upload
one as a `.zip` or `.skill` archive; to import one from a URL of a GitHub
repository or a folder of one, or of an archive, choosing among the skills
the source holds; to download one as an archive; and to turn each on or off
and delete it. Skills MUST be private to their owner, MUST be validated by
the Agent Skills rules, and MUST stay within the limits of ADR-0096. The
download of an import MUST run in a sandbox, never in the control plane, and
archives MUST be refused when an entry would fall outside the skill's folder
or when they exceed the limits.

Every run MUST be given the skills that are on for its user and not turned
off in its conversation, with only their names and descriptions in the
context until the model loads one; a conversation MUST be able to turn off
skills that are on, and a skill turned on or added later MUST be on in the
user's conversations. Skills MUST be read for each run, and runs MUST NOT
keep copies of skills in their durable inputs (ADR-0044, ADR-0096).

Rationale: journey J13.

## AGT-018: Every call to a device or an MCP server is approved

- **Status:** accepted
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration, security

Every invocation of a tool of a connected device (DEV-003) or of a remote MCP
server (AGT-019) MUST require the user's explicit approval, whatever its
capability classes, in addition to AGT-006. The run MUST wait for the answer.
The approval MUST cover only that invocation, and MUST NOT be lifted by
any tool permission or allowance. Tools of the sandbox and Sibillo's own tools follow
AGT-006 alone (ADR-0063, ADR-0064, ADR-0099).

## AGT-019: Remote MCP servers of a household

- **Status:** accepted
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration, security

A tenant admin MUST be able to add remote MCP servers, reached over
Streamable HTTP, to their tenant, and to list, change, switch off and remove
them; their tools MUST be available to the users of that tenant (AGT-029) and
to no other tenant. A server MUST need either no credential or a credential
of each user (AGT-030); no credential MAY be shared between users. Only a
tenant admin who is also the instance admin MAY use a
private or local address; other tenant admins MUST use public `https`
addresses, checked at connection time, without following redirects
(ADR-0061). The control plane MUST only call a server's tools, never start a
program, and MUST NOT give the model the server's instructions, resources or
prompts. A server's tools MUST be offered under names prefixed with the
server's prefix, which no tool of Sibillo or of another server can take.
Their results MUST be untrusted content (AGT-003) (ADR-0064, ADR-0099,
ADR-0100).

## AGT-020: Web search

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration, security

The agent MUST be able to search the web with a `web_search` tool, for every
model that can call tools. The tool MUST send only the query, to the
instance's search service, and return at most ten results, each with its
title, address and excerpt, as untrusted content (AGT-003) bounded like other
tool output (AGT-014). It MUST NOT fetch any address itself, and MUST NOT use
a model provider's web search (ADR-0074). When the search service fails, the
tool MUST tell the model so, and the run MUST go on. Queries MUST NOT be
logged (OBS-001) (ADR-0075).

## AGT-021: Reading web pages

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

The agent MUST be able to read a web page with a `read_page` tool, which
fetches one `http` or `https` address from the conversation's sandbox, under its
egress rules, and returns the page's title, final address and main text as
Markdown, as untrusted content (AGT-003) bounded like other tool output
(AGT-014). Other addresses MUST be refused. When the page cannot be read,
the tool MUST tell the model why, and the run MUST go on (ADR-0075).

## AGT-022: What the workspace keeps

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration, eval

The agent's instructions MUST explain that work happens in the scratch
folder, which is discarded, and that `/workspace` keeps only what the user
will want again: scripts, results and notes, each piece of work in its own
folder with a `README.md` saying what it is and how to make it again, and
not bulk data that can be fetched again. Evals MUST check that the agent
keeps the right files (ADR-0076).

## AGT-023: Offering a file to download

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration, e2e

The agent MUST be able to offer one file of the conversation's workspace for
download with an `offer_download` tool. Clients MUST show the offer in the
answer, with the file's name and size and a button that downloads it, and
MUST NOT download it without the user's action. The offer names the file in
the workspace: it downloads the file's current content, or says that it is
gone (ADR-0079).

## AGT-024: Built-in skills

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration, design

The instance MUST come with built-in skills, trusted and the same for every
user, which each user MAY turn off for themselves. Together they MUST
describe how to use every tool the sandbox image installs (SBX-021), and one
of them MUST describe how to write a skill and save it (AGT-026). A user's
skill MUST NOT take the name of a built-in skill (ADR-0096).

Rationale: the toolbox is used often; how to use it belongs in skills,
read when needed, and must not drift from the image.

## AGT-025: Skills from untrusted sources

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration, security

Each skill MUST record its origin: written in the editor, uploaded, imported
with its URL, or saved by the assistant with its conversation. Uploaded and
imported skills MUST be untrusted, and so MUST a skill saved by the
assistant in a run that has untrusted content when it calls the tool
(AGT-003). Editing a skill MUST NOT change whether it is trusted; only the
user, explicitly, MUST be able to mark an untrusted skill trusted. The
catalog MUST mark untrusted skills as from an untrusted source, and loading
one MUST make the run have untrusted content from then on (AGT-004). The
scripts of every skill MUST run only in the sandbox (ADR-0096).

Rationale: threats T-25 and T-36.

## AGT-026: The assistant saves skills

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

The assistant MUST be able to save a folder of its sandbox as one of the
user's skills only through a mediated tool, `save_skill`, which creates the
skill or replaces the user's skill of the same name, never a built-in skill,
and which asks for approval by default. It MUST NOT be offered in temporary
conversations (CNV-011, ADR-0096).

Rationale: the assistant turns work it did into a skill the user can reuse.

## AGT-027: A run's limit of model requests

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

A run MUST make at most the number of model requests the instance admin
configures, 200 by default. A run that reaches it MUST fail with the code
`run.step_limit`, never `internal.error`, and keep in the conversation what
it did until then; clients MUST say that the assistant stopped after many
steps and that the user can ask it to continue (UX-014). The agent's
working instructions MUST tell it to keep work in progress that takes many
steps in a folder of `/workspace`, so that a run that stops does not lose
it (ADR-0097).

Rationale: the first long task a user tried stopped at a default limit
nobody had chosen, as an internal error, and lost its work.

## AGT-028: Tools of an MCP server are reviewed

- **Status:** accepted
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration, security

A tool of a remote MCP server MUST be offered to the model only after a
tenant admin accepted it, having been shown its name, title, description,
input schema and annotations as the server listed them, and only while the
server lists its title, description and input schema exactly as accepted. A
tool that changed, or a new one, MUST NOT be offered until a tenant admin
accepts it again, and an approved call to a tool that is no longer offered
as accepted MUST NOT run. An acceptance MUST be refused when the server's
listing changed after the admin saw it, and a new address MUST clear a
server's acceptances. Accepted descriptions MUST NOT by themselves make a run
have untrusted content (ADR-0099).

Rationale: tool descriptions reach the model in every run, and the server
can change them at any time (T-29).

## AGT-029: Remote MCP servers for each user

- **Status:** accepted
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

A tenant admin MUST be able to deny a remote MCP server to a user; a denied
server MUST NOT be offered to that user, a call to its tools MUST be refused,
and the user MUST NOT be able to switch it on. A capability class set to
`deny` for a user MUST take away the tools of every server, as it does for
other tools of that class (AGT-002). A user MUST be able to switch each
server on or off for a conversation and in their defaults, as for tools
(CNV-013); a server added later MUST be on (ADR-0099).

Rationale: a household may want a server for some of its members only.

## AGT-030: Each user's own credential for an MCP server

- **Status:** accepted
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration, security

For a remote MCP server that needs a credential, each user MUST give their
own: a token they enter, or one obtained by signing in to the service
(AGT-031). A credential MUST be used only for its user's runs and requests,
sent only to its server's address, stored encrypted, and never returned by
the API or shown to tenant admins, other users, sandboxes, clients or logs
(MOD-002). A token MUST be tried when given and refused when the server
refuses it. A user MUST be able to remove their credential. A user without a
credential, or whose credential the server refuses or that cannot be
renewed, MUST NOT be offered the server's tools, and the run's instructions
MUST say that their account is not connected. A new address, authentication
or OAuth client of a server MUST make every credential given for it before
unusable (ADR-0099).

Rationale: most services know each person; a shared credential would let
one user act on a service as another (T-37).

## AGT-031: Signing in to an MCP server with OAuth

- **Status:** accepted
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration, security

A user MUST be able to obtain their credential for a remote MCP server by
signing in to the service in their browser, with OAuth 2.1's authorization
code flow and PKCE (`S256`), as the MCP authorization specification
describes. The control plane MUST find the server's authorization server
from its metadata, and use a client given by a tenant admin or registered
dynamically. Each sign-in MUST be bound to the user who started it, used
once, and expire after 10 minutes; its `state` MUST be checked, and the
issuer when the authorization server returns it. Tokens MUST be asked for
the server alone (`resource`), and renewed once at a time per credential. The
requests the control plane makes for OAuth MUST follow the server's address
rules (AGT-019) (ADR-0100).

Rationale: many hosted servers accept no other credential, and people who
are not technical cannot create tokens (T-38).
