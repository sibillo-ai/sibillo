# Roadmap

Sibillo is built in phases. Each phase has a goal and exit criteria;
the requirements of a phase are those with the matching `Phase` field in
[`specs/requirements/`](specs/requirements/). Dates are deliberately absent:
this is a personal, best-effort project.

The phases were renumbered twice. When connected devices became phase 2
(ADR-0063), the release moved from phase 2 to 3 and opening up from 3 to 4.
When tasks became phase 2 (ADR-0106), connected devices moved to phase 3, the
release to phase 4 and opening up to phase 5. ADRs keep the numbers of the
day they were written.

## Phase 0 — Walking skeleton

**Status:** complete. Every phase 0 requirement is `implemented`, the security
tests pass, and the end-to-end test installs Sibillo by following the
README. Known limits are recorded in the specs, such as the workspace disk
limit, which comes with SBX-016 in phase 1.

**Goal:** the thinnest path through the whole architecture, with the
security foundations in place:
sign in → open a conversation → send a message → the agent runs a command in
the user's isolated sandbox → the answer streams back.

Includes: tenancy and row-level security (TEN), local accounts (AUTH), the
sandbox and its network isolation (SBX), mediated tools (AGT-001), the model
gateway with one local and one remote provider (MOD), the public API with
conversations, message versions, rewinding, stopping runs and streaming (API,
CNV-001 to CNV-004, CNV-015; message versions were replaced in phase 1 by
editing that rewinds, ADR-0068), the cost ledger (MOD-006), privacy defaults for
logs (OBS), Docker Compose deployment (OPS), and the repository governance
checks (REPO). There is no user interface in phase 0: the API is exercised by
end-to-end tests (ADR-0024).

**Exit criteria:**

- every phase 0 requirement is `implemented`, with passing tests;
- the cross-user, cross-tenant and sandbox network security tests pass;
- a fresh Linux host goes from `git clone` to a working conversation by
  following the README.

## Phase 1 — Daily use

**Goal:** an assistant the maintainer's family uses every day, on the web and
on the phone (installable web app).

Includes: the web client as an installable web app (UX) with externalized
strings (I18N-001), notifications, voice turns (UX-005, API-006), live context
and cost (UX-008, MOD-007), the conversation list with folders, forks, search,
conversation settings, custom instructions and temporary conversations
(CNV), artifacts (ART),
automatic compaction, skills and questions to the user (AGT), web search and
page reading, persistent workspaces in ephemeral sandboxes (ADR-0076), a
sandbox image with a selection of common tools for documents, media and
data, so that they need no installing (ADR-0022), transparent memory (MEM), tool
permissions, provenance and approvals with the lethal trifecta mitigation
(AGT), the data egress policy (MOD-003), backup and restore (OPS-006), and the
first eval suite (EVL). It also lays the foundations of connected devices:
approval of every call to a device or an MCP server (AGT-018), remote MCP
servers added by tenant admins (AGT-019), passkeys as a second factor
(AUTH-010), and models labeled as local or remote (MOD-010).

Suggested order: the web client's foundation (sign-in, conversations, streamed
answers, versions, model settings); then trust (approvals, the egress policy,
local and remote models, passkeys, backup, the first evals); then everyday
conversations; memory and files; remote MCP servers and the other agent
capabilities; notifications and voice last.

**Exit criteria:** used daily by at least one household for a month without
data loss; eval suite in place, including injection scenarios.

## Phase 2 — Tasks and triggers

**Goal:** the assistant works while nobody writes: a press review ready on
waking, a report every week, a word when something happens.

Includes: tasks with their instructions, settings and triggers, each firing a
new conversation listed under its task (TSK-001, TSK-002, TSK-010);
schedules (TSK-003); task grants that let a run work unattended without ever
completing the lethal trifecta (TSK-004, TSK-005); tasks proposed by the
assistant in a conversation (TSK-006); webhook triggers (TSK-007); events of
remote MCP servers through the MCP Events extension, reviewed by a tenant
admin like tools (TSK-008); limits on firing (TSK-009); and tasks in the app
(UX-031) (ADR-0106). Then running a task now, the assistant changing and
reading tasks, searching and reading the user's earlier conversations with
provenance that follows what was read, a stream of the user's changes that
the app follows, and a lasting sign when notifications are off (TSK-011 to
TSK-013, AGT-032, AGT-033, API-008, UX-032, UX-033, ADR-0107, ADR-0108). Mail, messaging and other services come in as remote MCP
servers, never as code of the control plane.

**Exit criteria:** a household member wakes up to a press review made by a
task every day for a month, and a task fired by a webhook or an MCP event
runs as expected; every grant check has security tests that try to break it.

## Phase 3 — Connected devices

**First:** the interface in every language of the preferred language's list,
English and Italian reviewed by a person and the others translated by a
model, with right-to-left layout and the plurals, dates and numbers of each
language (I18N-002, I18N-004 to I18N-006, ADR-0135). It moved here from
phase 4, ahead of the devices, so that households beyond the first use
Sibillo in their own language.

**Then:** delegation, so that the assistant hands self-contained pieces of
work to delegated runs with a fresh context, several at once, and receives
their reports, with provenance that follows the brief and the report
(AGT-035 to AGT-038, ADR-0136). It was not planned; the first long pieces of
work showed that one context fills up, and that independent parts wait for
each other.

**Goal:** the assistant helps with the household's own machines: diagnosing a
server, installing updates, checking logs and firewall rules, editing files,
from any device where the user is signed in.

Includes: the device service for Linux, paired to one user and connected
outbound (DEV-001, DEV-002), its tools for commands and files (DEV-003), the
tools of several devices in one run (DEV-004), calls that wait for offline
devices (DEV-005), device status (DEV-006), least privilege by default
(DEV-007), the web app as a device (DEV-008), and events of a device that
fire tasks, such as a weekly check of a server's security updates (DEV-010)
(ADR-0063, ADR-0106). macOS and Windows may follow (DEV-009).

**Exit criteria:** the maintainer administers their own servers through
Sibillo for a month, with every device call approved, in a conversation or
by a fixed grant of a task, and none surprising.

## Phase 4 — A real assistant, and a first release

**Goal:** the features that make it an assistant rather than a chat, and the
release engineering to let others run it.

Includes: multi-step research producing reports, browser automation in the
sandbox, connectors over open protocols (calendar, mail,
files, home automation through mediated tools), OpenID Connect (AUTH-003),
budgets (MOD-004), debug mode (OBS-004), signed multi-architecture images,
upgrade guarantees, release gating by evals.

**Exit criteria:** first public release `0.1.0`; installation and upgrade
documentation verified on a clean machine; public announcement.

## Phase 5 — Opening up

**Goal:** make the project sustainable beyond its first household.

Candidates: tenant administration for operators hosting several households,
Kata Containers and Kubernetes providers, a native mobile app with push
notifications, reviews of the model-made translations by their communities,
a second maintainer and the governance transition described in
[GOVERNANCE.md](GOVERNANCE.md).

## Later

Ideas kept for after these phases, not planned yet:

- personal remote MCP servers that a user adds for themselves (ADR-0064,
  ADR-0099);
- a credential of the household for remote MCP servers reached through one
  shared account, and revoking a server's
  tokens when a user removes them (ADR-0099, ADR-0100);
- sessions of external coding agents shown as Sibillo conversations;
- sharing data between users: copies of conversations and artifacts sent to
  another user, shared spaces and their data egress policy (CNV-010,
  MOD-016), and a file library that lets a user's conversations use the same
  files (CNV-012). Set aside because the privacy risks outweigh the value for
  now; not confirmed.

