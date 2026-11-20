# Glossary

The canonical vocabulary of Sibillo (its *ubiquitous language*). Code,
specs, docs and UI use exactly these terms. A new domain concept requires a
new entry here first (ADR-0005).

## Tenancy and identity

| Term | Definition |
|---|---|
| Instance | One installation of Sibillo, on one server. |
| Instance admin | The person who operates the instance (host, containers, configuration). Trusted (ADR-0011). |
| Tenant | An isolated group of users with its own data: typically a household, possibly a small organization. |
| Tenant admin | A user who manages a tenant's users, shared spaces and tool permissions. |
| Tool permission | A tenant admin's setting of one tool, or one capability class, for one user: allowed, asked or denied (AGT-002, ADR-0090). |
| User | A person with an account in exactly one tenant. |
| Device session | An authenticated session of one user on one device, identified by an opaque token and revocable by the user (ADR-0025). |
| Passkey | A WebAuthn credential kept by a user's device, often unlocked with a fingerprint or a face; a second factor on top of the password (ADR-0065). |
| Initial password | The password an administrator chose when creating an account; its user replaces it at their first sign-in (ADR-0105). |
| Source address | The network address a request comes from: the address of the connecting peer, or the client address reported by a trusted proxy (ADR-0050). |
| Trusted proxy | A reverse proxy, named by the instance admin in the configuration, whose report of the client address the server believes (ADR-0050). |
| Private data | Data owned by one user and visible only to that user. The default for all data. |
| Shared space | A container of data explicitly shared among some or all users of a tenant (e.g. household documents, family calendar, shopping list). The data model has them (TEN-001), but no feature uses them yet (ROADMAP, Later). |

## Conversations and agent

| Term | Definition |
|---|---|
| Conversation | An independent chat between a user and the assistant, with its own history. A user has many. |
| Attachment | A file the user adds to a message, uploaded into `/workspace/uploads/` of the conversation's workspace (CNV-017, ADR-0079). |
| Share | What another app hands to the installed web app through the system's share sheet: a title, a text, a link and files, kept on the device until the app offers them as a new chat (UX-006, ADR-0102). |
| Message | One entry in a conversation, from the user or the assistant. |
| Turn | A user message and the runs that answer it: the run the message starts, and the resume runs that continue it (ADR-0090). |
| Folder | A user's named group of conversations in the conversation list; carries no instructions or settings (CNV-007). |
| Fork | A new conversation started from a copy of another conversation up to a turn, which records where it came from (CNV-005, ADR-0073). |
| Pin | A mark that keeps a conversation or a folder at the top of the conversation list (CNV-008). |
| Rewind | Making an earlier turn the end of a conversation, so it continues from there; what followed is deleted (CNV-004, ADR-0068). |
| Base instructions | The assistant's main instructions, which a user may replace and restore; shown as "System prompt" (CNV-014). |
| Additional instructions | Instructions a user adds after the base instructions; shown as "Additional prompt" (CNV-014). |
| Working instructions | The part of the assistant's instructions that tells it how to use its workspace and the tools enabled for a run; not part of the base instructions, and kept whatever the user writes (CNV-014, ADR-0081). |
| Conversation settings | A conversation's model, reasoning and enabled tools, copied from the user's defaults when it starts, and its own instructions, if any (CNV-013, CNV-014). |
| User defaults | The settings and instructions a user chooses for their conversations: new conversations copy the settings, and conversations without instructions of their own use the instructions (CNV-013, CNV-014, ADR-0081). |
| Preferred language | The language a user wants the assistant to answer in, one of their user defaults, named by a BCP 47 language tag; it gives way to the language the user writes in, or asks for (I18N-003, ADR-0103). |
| Reasoning | What a model works out before it answers, set per conversation to off, on or deep, and shown folded above the answer (CNV-013). |
| Question | A question the assistant asks the user during a run, with choices; it ends the run with an interrupt, and the answer starts the next run (AGT-015, ADR-0083). |
| Task list | The steps the assistant plans for a long task and marks as it works, kept per conversation; shown as a checklist (UX-009, ADR-0083). |
| Skill | A reusable package of instructions and files in the open Agent Skills format, loaded by the model when relevant; kept by the control plane and given read-only to the sandbox at `/skills` (AGT-017, ADR-0096). |
| Built-in skill | A skill that comes with the instance, trusted and the same for every user, such as those that teach the sandbox toolbox (AGT-024). |
| Untrusted skill | A skill uploaded, imported, or saved by the assistant from untrusted content, until the user marks it trusted; loading it makes the run untrusted (AGT-025). |
| Context window | The most tokens a model reads at once: listed by the provider, or set on a connection to the household's own server (ADR-0073). |
| Compaction | Reducing the history sent to the model when it approaches the context window, without changing the stored conversation (ADR-0041). |
| Compaction checkpoint | The stored result of a compaction for one path, attached to the run at which it happened (ADR-0041). |
| Temporary conversation | A conversation that is not listed or searched, does not use memory, and is deleted when the user leaves it or a day after its last activity (CNV-011, ADR-0082). |
| Parent run | The run whose messages a run continues; the runs of a conversation form one chain (ADR-0037, ADR-0068). |
| Active path | The chain of runs, from the first to the active run: the history the user sees and that a new run continues (ADR-0037, ADR-0068). |
| Artifact | A file of the conversation's workspace that the assistant makes for the user and shows in the conversation, such as a document, code, a diagram or a web page, opened in the viewer (ADR-0086). Not to be confused with a repository artifact, a file of this repository. |
| Voice turn | A user turn spoken instead of typed, started and ended explicitly by the user, answered in full and read aloud (ADR-0040). |
| Hands-free mode | A way of holding voice turns without looking at the screen: one large button, the media buttons of a headset or a car, and sounds that say where the conversation stands (UX-005, ADR-0088). |
| Transcription model | A model of a connection that turns recorded speech into text (API-006, ADR-0088). |
| Speech model | A model of a connection that reads text aloud in one of its voices (API-006, ADR-0088). |
| Notification | A content-free message pushed to a user's device when a run finishes or fails, or an approval request or a question is pending (UX-004, ADR-0039, ADR-0101). |
| Notification subscription | The Web Push subscription of one device session, saved when the user turns notifications on in that client (UX-004, ADR-0101). |
| Agent | The component that turns a user request into model calls and tool calls. |
| Run | One execution of the agent in response to a message, including all its model and tool calls. |
| Run event | An AG-UI event produced during a run (text, tool call, result, interrupt, completion), stored durably with a sequence number and streamed to clients (ADR-0032, ADR-0034). |
| Worker | A server process that executes runs, and fires tasks, as durable workflows (ADR-0034, ADR-0106). |
| Durable execution engine | The library that checkpoints runs so they survive crashes and restarts: DBOS (ADR-0034). |
| Interrupt | The end of a run that needs the user's answer, such as an approval; the answer starts a new run (ADR-0033). |
| Tool | A capability the agent can invoke. All tools are mediated tools. |
| Tool group | A named set of tools that do one kind of work, such as the web, commands or files, which a user can switch on and off together (CNV-013, ADR-0087). |
| Mediated tool | A tool executed by the control plane, which checks permissions, approvals and records audit events. |
| Capability class | A declared property of a tool used for safety decisions: `reads_private_data`, `ingests_untrusted`, `external_communication`, `irreversible`, `physical`. |
| Approval default | Whether a tool is allowed or asked when no tool permission says otherwise, declared with its capability classes (AGT-005, ADR-0090). |
| Untrusted content | Any content not authored by the user or the system: web pages, received emails, external files, sandbox output; in particular the results of tools in the `ingests_untrusted` class and attachments (AGT-003, ADR-0090). |
| Lethal trifecta | The combination of access to private data, exposure to untrusted content and the ability to communicate externally, which enables data exfiltration through prompt injection. |
| Approval | An explicit confirmation by the user before a tool call is executed, asked for by an approval request that ends the run with an interrupt (ADR-0033). |
| Allowance | An approval that also covers later calls: internet access for the rest of a turn or in one conversation, or a tool in one conversation (AGT-006, AGT-034, ADR-0090, ADR-0113). |
| Internet access | A conversation's permission, given by its user, for the assistant to reach the internet: to search the web, to read pages, and to run commands that use the network in its sandbox. An allowance for a turn or a conversation, or a task grant (AGT-034, ADR-0113). |
| Audit event | A content-free record of a tool call and its approval outcome, visible to the user it acted for (AGT-008, ADR-0090). |
| Activity | The page of a user's settings that lists their audit events (UX-023). |
| Task | A user's standing instructions, with conversation settings, triggers and task grants, that start a new conversation each time a trigger fires, without a message from the user (TSK-001, ADR-0106). |
| Trigger | What fires a task: a schedule, a webhook trigger, or an event of a remote MCP server or a connected device (TSK-003, TSK-007, TSK-008, ADR-0106). |
| Schedule | A trigger that fires at a start and at the times of its iCalendar recurrence (RFC 5545), in the task's time zone; once, without recurrence (TSK-003, ADR-0109). |
| Webhook trigger | A trigger that fires when a request reaches its secret address of the instance, whose body is the event (TSK-007). |
| Event | Something that happened outside Sibillo, delivered by a remote MCP server or a connected device with the MCP Events extension, or by a request to a webhook trigger; its data is untrusted content (TSK-008, ADR-0106). |
| Accepted event type | A type of event of a remote MCP server that a tenant admin accepted as the server listed it; offered only while the server lists it unchanged (TSK-008, ADR-0106). |
| Firing | One time a trigger fires a task, which starts one conversation (TSK-002, TSK-009). |
| Change event | A content-free announcement, on the user's stream of changes, that a conversation was created, a run started or finished, or a task fired, with their identifiers (API-008, ADR-0108). |
| Task grant | A call a task's runs may make without approval, given by its user when the task is saved: a fixed grant, of one tool with all its arguments, an open grant, of one tool with any arguments; or a grant of internet access (TSK-004, TSK-005, ADR-0106, ADR-0113). Not to be confused with an allowance, which lasts one turn or one conversation. |
| Memory item | A short text the assistant retains about a user across conversations, given to every run while memory is on; written by the user or by the assistant's memory tools, and untrusted when the assistant wrote it from untrusted content. Visible, editable and deletable by the user (MEM-001 to MEM-008, ADR-0095). |
| Connector | An integration with an external system (calendar, mail, files, home automation), exposed to the agent as mediated tools. Not to be confused with a connection. |

## Devices and connectors

| Term | Definition |
|---|---|
| Connected device | A machine or phone of a user, paired to their account, that offers tools running on it to that user's runs (ADR-0063). Not to be confused with a device session, which is a sign-in. |
| Device service | The program that runs on a connected device, keeps its connection to the instance and runs its tools (ADR-0063). |
| Remote MCP server | A service reached over Streamable HTTP with the Model Context Protocol, added by a tenant admin, whose accepted tools the assistant can call, each call approved, with the user's server credential when it needs one (AGT-018, AGT-019, ADR-0064, ADR-0099). |
| Server prefix | The short name a remote MCP server's tools carry for the model, as in `<prefix>__<tool>`, chosen when the server is added and fixed (AGT-019, ADR-0099). |
| Accepted tool | A tool of a remote MCP server that a tenant admin accepted as the server listed it; offered only while the server lists its title, description and input schema unchanged (AGT-028, ADR-0099). |
| Server credential | A user's own token for a remote MCP server, entered by the user or obtained when they sign in to the service with OAuth; used only for that user, and seen by no one (AGT-030, AGT-031, ADR-0099, ADR-0100). |

## Clients

| Term | Definition |
|---|---|
| Design language | The look and behavior every screen of the clients shares: its design tokens, its shared components, its typefaces, its icons and the sprite, as the reference prototype shows them (UX-017, ADR-0111). |
| Design token | A named value of the design language: a color, a size of text, a spacing step, a radius, a control height, a width, a shadow or a duration. Clients use no other value (UX-037, ADR-0111). |
| Shared component | The one implementation of a control or a pattern of the design language, such as a button, a field, a dialog or a row, from which screens are assembled (UX-037, ADR-0111). |
| Top bar | The bar at the top of a page of the clients, on a phone of every page: where the user is, the way back, and the page's own actions, such as a conversation's model (UX-039, ADR-0111). |
| Sprite | The animated character of the clients: Sibillo, a mazzamurello, the house sprite of folklore, who greets the user and acts out what a run is doing (ADR-0111). |

## Execution

| Term | Definition |
|---|---|
| Control plane | The server components that hold state and secrets: API, agent, memory, model gateway. Never executes user code. |
| Execution plane | Where user code runs: the sandboxes. |
| Sandbox | A per-user isolated execution environment, without network until its conversation has internet access, and never with access to local networks (ADR-0113). |
| Workspace | The persistent folder of a conversation's sandbox, `/workspace`, which keeps what the user wants to keep; everything else in the sandbox is discarded when it stops (ADR-0076, ADR-0078). |
| Scratch folder | The folder where a sandbox's commands start, `/scratch`, discarded with the sandbox (ADR-0076). |
| Workspace disk | A sparse file holding the ext4 filesystem of one workspace, of the size of the workspace quota, attached to a loop device and mounted at `/workspace`; never mounted where user content runs (SBX-016, ADR-0098). |
| Disk helper | A short-lived privileged container of the sandbox driver that makes, grows, attaches and detaches workspace disks with fixed commands; never runs user content (ADR-0098). |
| Workspace panel | The client's view of a conversation's workspace, as a tree of files and folders to preview, download, upload, move and delete (UX-019, ADR-0079). |
| Sandbox driver | The only component allowed to manage containers; exposes a minimal API to the control plane. |
| Sandbox engine | The container that runs the sandboxes: a container runtime of its own with gVisor in it, privileged, reachable only by the sandbox driver over a Unix socket, so that nothing is installed on the host (SBX-025, ADR-0114). |
| Workspace backend | The control-plane component that presents a conversation's sandbox to Pydantic AI as a workspace, through the sandbox driver (ADR-0035, ADR-0078). |
| Sandbox bridge | The host network bridge of one sandbox, whose interface name has a fixed prefix; the egress table matches every sandbox bridge, and gives network only to those of conversations with internet access (ADR-0021, ADR-0113). |
| Network guard | A small infrastructure container that shares the sandbox engine's network namespace, with `NET_ADMIN`, and installs and maintains the egress table there (ADR-0021, ADR-0114). Never runs user code. |
| Egress table | The dedicated `nftables` table, in the sandbox engine's network namespace, that enforces the egress policy for traffic from the sandbox bridges (ADR-0021, ADR-0113). |
| Canary sandbox | A short-lived sandbox the sandbox driver starts to verify isolation before accepting requests. |
| Isolation runtime | The container runtime that enforces sandbox isolation: gVisor (ADR-0023). |
| Egress policy | The network rules that decide which destinations a sandbox may reach. |
| Declared destination | An external service the control plane may connect to, for one purpose, as listed in ADR-0072; the control plane connects to no other (OBS-006). |
| Search service | The instance's own metasearch engine, SearXNG, which the worker asks for web search results and which alone queries public search engines (ADR-0075). |
| Backup archive | One encrypted file holding an instance's database, secret key and workspaces, restorable with its backup key (ADR-0077). |

## Models

| Term | Definition |
|---|---|
| Model gateway | The component through which every model call passes; applies routing, budgets and the data egress policy. |
| Provider | A source of model inference: a local server or a remote service. |
| Connection | A household's access to one provider, managed by a tenant admin: OpenRouter, or a server with an OpenAI-compatible API, with its address and credentials. It offers all of the provider's models (ADR-0069). Not to be confused with a connector. |
| Connection test | A check of a connection, step by step, that says which step fails and why (MOD-013). |
| Default model | The model of one of its connections that a household's new conversations start with, chosen by a tenant admin (MOD-012). |
| Local model | A model served from inside the instance or the household's network. |
| Remote model | A model served by a third party over the internet. |
| Cost ledger | The record of every model request made for a user, with tokens and cost but no content (MOD-006, ADR-0042). |
| Data egress policy | The rule that decides whether a user's data may be sent to remote models: any model, or local models only. Set for the household and for each user by a tenant admin, and by each user for themself; the strictest applies (MOD-003, ADR-0091). |
| Served context window | The context window a model's server actually runs the model with, as an Ollama server reports it; it may be smaller than its connection's (MOD-019, ADR-0093). |

## Process

| Term | Definition |
|---|---|
| Requirement | A numbered, normative statement in `specs/requirements/`. |
| Persona | One of the kinds of user described in the product description (`specs/product.md`), used to justify user-experience requirements. |
| Journey | A task a persona accomplishes with Sibillo, described in the product description. |
| ADR | Architecture decision record in `specs/adr/`. |
| Contract | An interface that outlives the code: public API, database schema, on-disk formats. |
| Pending test | A test whose requirements are all `accepted` and not yet `implemented`; its failures are reported as expected (ADR-0045). |
| Invariant | A property that must always hold, typically a security property, verified by tests. |
| Eval | A repeatable scenario that measures agent behavior against one or more models. |
| Planted secret | A random value an adversarial eval puts in the user's workspace and that untrusted content tells the agent to send away; the scenario fails if it leaks (EVL-003, ADR-0092). |
| Scripted agent | The model the tests serve, scripted to act as an agent that passes or fails an eval scenario, so that the suite checks its own checks (EVL-006, ADR-0092). |
