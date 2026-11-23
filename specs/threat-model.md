# Threat model

This document describes what Sibillo protects, from whom, and how. Every
mitigation points to the requirements that implement it. It is reviewed
whenever a requirement in the security-relevant areas changes.

## Scope and assumptions

- One instance runs on a Linux server under the control of the instance
  admin, in containers, with Docker Engine.
- **The instance admin is trusted** (ADR-0011). They can read all data on
  the server; protecting users from the admin is out of scope.
- The host kernel is kept up to date by the instance admin; the isolation
  runtime (gVisor) comes with the sandbox engine and is updated with Sibillo
  (ADR-0114).
- Sandbox egress is enforced in the host kernel, outside the sandboxes, by a
  dedicated `nftables` table in the sandbox engine's network namespace,
  maintained by the network guard (ADR-0021, ADR-0114). The host may be a
  cloud VM without hardware virtualization (OPS-009).
- Runs are checkpointed by the durable execution engine in its own schema,
  outside row-level security (ADR-0034); access to it is confined by TEN-009.
- Models — local or remote — are **not trusted to behave**: any model can be
  manipulated by the content it reads (prompt injection).
- Remote model providers receive whatever the data egress policy allows them
  to receive. What they do with it is governed by their terms, not by us.

## Assets

| ID | Asset |
|---|---|
| A1 | Users' private data: conversations, memory items, files, connector data (mail, calendar) |
| A2 | Shared space data of a tenant |
| A3 | Secrets: connector tokens, model provider keys, session keys, database credentials |
| A4 | The household network and its devices (router, NAS, cameras, home automation) |
| A5 | The host and the other services running on it |
| A6 | Compute, storage and paid model budgets |
| A7 | Integrity of the assistant's actions (what it sends, deletes, buys, switches on) |

## Adversaries

| ID | Adversary | Capabilities |
|---|---|---|
| X1 | Author of untrusted content | Controls a web page, an email, a document or a package the agent reads or installs. The most common adversary. |
| X2 | Curious or malicious user | Has a legitimate account in a tenant; tries to read other users' or tenants' data, or to escape their sandbox. |
| X3 | Compromised sandbox | Arbitrary code running in a conversation's sandbox (via X1 or X2), with internet access, until the answer it runs in ends. |
| X4 | Network attacker | Reaches the instance's exposed endpoint from the internet or the LAN. |
| X5 | Supply-chain attacker | Compromises a dependency, a container image or a CI workflow of the project. |

Out of scope: the instance admin (trusted), physical access to the server,
and unknown vulnerabilities in the host kernel or in the isolation runtime
beyond keeping them configurable and updatable.

## Trust boundaries

```
 internet / LAN ──(B1)──► reverse proxy / API
                              │
                         control plane ──(B4)──► remote model providers
                              │      └──(B5)──► connectors (mail, calendar, home automation)
                            (B2)
                              │
                        sandbox driver
                              │
                            (B3)
                              │
                 sandbox A │ sandbox B │ …  ──(B6)──► internet only, when allowed
```

- **B1** — clients to API: authentication, TLS termination, rate limits.
- **B2** — control plane to sandbox driver: the control plane never touches
  the container runtime.
- **B3** — sandbox to host and to other sandboxes: isolation runtime.
- **B4** — control plane to remote models: data egress policy.
- **B5** — control plane to connectors: mediated tools, permissions, approvals.
- **B6** — sandbox to network: egress policy (internet yes, local networks no).

## Threats and mitigations

| ID | Threat | Adversary | Mitigations |
|---|---|---|---|
| T-01 | A user reads or modifies another user's private data through the API | X2 | TEN-003, TEN-004, TEN-005, TEN-006, TEN-007 |
| T-02 | A user of one tenant reaches data of another tenant | X2 | TEN-002, TEN-003, TEN-006, TEN-008 |
| T-03 | Code in a sandbox escapes to the host | X3 | SBX-002, SBX-003, SBX-011, SBX-012, SBX-017, OPS-004 |
| T-04 | Code in a sandbox scans or attacks the LAN, the host's services or cloud metadata endpoints | X1, X3 | SBX-005, SBX-007, SBX-013, SBX-015, OPS-003 |
| T-05 | Code in one sandbox reaches another user's or another conversation's sandbox | X3 | SBX-001, SBX-006 |
| T-06 | Secrets are stolen from inside a sandbox | X3 | SBX-008, MOD-002 |
| T-07 | Compromise of the control plane yields control of the container runtime (root on the host) | X4, X5 | SBX-009 |
| T-08 | **Lethal trifecta:** injected instructions make the agent send private data to an attacker (e.g. "forward the last invoices to …") | X1 | AGT-001, AGT-003, AGT-004, AGT-005, AGT-034, SBX-024, EVL-003 |
| T-09 | Injected instructions trigger irreversible or physical actions (delete files, buy, open the gate) | X1 | AGT-005, AGT-006, AGT-007, AGT-002 |
| T-10 | A user's actions on their behalf are not visible, so abuse goes unnoticed | X1, X2 | AGT-008 |
| T-11 | Private data is sent to a remote model against the household's wishes | X1, X2 | MOD-003, MOD-005, MOD-010 |
| T-12 | Personal data leaks through logs, traces or telemetry | X4, X5 | OBS-001, OBS-002, OBS-003, OBS-004, OBS-005 |
| T-13 | A user cannot see or remove what the assistant retained about them | — | MEM-001, MEM-002, MEM-003, MEM-004 |
| T-14 | Unauthenticated access or account takeover through the exposed endpoint | X4 | AUTH-001, AUTH-002, AUTH-004, AUTH-005, AUTH-006, AUTH-007, AUTH-010, OPS-003 |
| T-15 | Resource exhaustion: a sandbox or a user consumes all CPU, memory, disk or model budget | X2, X3 | SBX-011, SBX-016, MOD-004 |
| T-16 | Malicious pull request or compromised CI action injects code or steals secrets | X5 | REPO-001, REPO-002, REPO-005, REPO-007, REPO-008, REPO-012 |
| T-17 | Tampered release images | X5 | REPO-012; OPS-007, still a draft: there is no release workflow yet, and images are built from source |
| T-18 | The host egress rules disappear (firewall reload, reboot, manual change) while sandboxes run, leaving them unfiltered | — | SBX-015, OPS-002 |
| T-19 | Run data stored by the durable execution engine, outside row-level security, is read across users or tenants, or survives deletion | X2 | TEN-009 |
| T-20 | A client forges or replays approval decisions to run tools the user did not approve | X2, X4 | AGT-012, AUTH-004 |
| T-21 | A framework capability fetches URLs, runs commands or reaches MCP servers from the control plane, bypassing the sandbox (SSRF to the LAN or host) | X1 | AGT-013, AGT-020, AGT-021, SBX-009 |
| T-22 | Active content in an artifact or a workspace file (scripts in a web page or SVG), possibly derived from untrusted content, runs with the user's session and calls the API or reads other data | X1 | ART-003, UX-002, UX-020 |
| T-23 | Notifications leak conversation content to the push services of browser vendors | — | UX-004 |
| T-39 | A user saves a notification subscription whose endpoint is an address of the instance or of the household network, so that the server sends requests there | X2 | UX-004, OBS-006 |
| T-24 | Content the user rewound past, or of a temporary conversation, reaches the model, memory or another conversation | X1 | CNV-002, CNV-004, CNV-011, MEM-007 |
| T-25 | An imported skill carries injected instructions or malicious scripts | X1 | AGT-003, AGT-004, AGT-017, AGT-025, SBX-022 |
| T-35 | Injected instructions are stored as memory items and reach later conversations as if the user had written them | X1 | AGT-003, AGT-004, MEM-001, MEM-008 |
| T-36 | Injected instructions are saved as a skill, or planted in a skill's files, and reach later conversations | X1 | AGT-003, AGT-004, AGT-025, AGT-026, SBX-022 |
| T-37 | A user's credential for a remote MCP server is used in another user's runs, or read by a tenant admin, so that one person acts on a service as another | X2 | AGT-030, TEN-007 |
| T-38 | A sign-in to a remote MCP server is subverted: an attacker's authorization is bound to a victim's account, a code is intercepted or replayed, a token is obtained for another server or sent to one, or the server's OAuth metadata leads the control plane to the household's network | X1, X2, X4 | AGT-031, MOD-009 |
| T-40 | Another app, or a web page that posts a form to the app's share address, puts text of its choosing in a new chat and has it sent as the user's own message | X1 | UX-006 |
| T-41 | A tenant admin signs in as a member with the password the admin chose, and reads or changes the member's private data | X2 | AUTH-008, AUTH-011, AUTH-012, TEN-007 |
| T-42 | Injected instructions in a page or an event read by a task's run, while nobody watches, use the task's grants to send data out or to act | X1 | AGT-003, AGT-004, TSK-004, TSK-005 |
| T-43 | Forged, replayed or flooded webhook requests or MCP event deliveries start conversations, plant content in them, or spend the household's model budget | X1, X4 | TSK-007, TSK-008, TSK-009 |
| T-44 | Injected instructions make the assistant propose a task, so that they run again later, unattended, with standing grants | X1 | TSK-005, TSK-006 |
| T-45 | Injected instructions read in one conversation reach another, unseen, when the assistant searches or reads the user's earlier conversations | X1 | AGT-003, AGT-004, AGT-032, AGT-033 |
| T-46 | Injected instructions make the assistant ask for internet access, again and again or at a moment the user expects it, so that what the conversation holds can then be sent out | X1 | AGT-034, SBX-024, UX-022, UX-041 |
| T-47 | Code in a sandbox reaches the sandbox engine's container runtime or the network guard over the network, and takes over the engine, which is privileged | X3 | SBX-005, SBX-015, SBX-025 |
| T-34 | A file operation on a workspace reaches outside it, through a crafted path or a link the agent planted, and reads or overwrites a file of the sandbox image, the host or another workspace | X1, X2 | SBX-014, TEN-008 |
| T-27 | A tenant admin who is not the instance admin configures a connection that leads the control plane to the household's network or the host, through a private address, DNS rebinding or a redirect | X2 | MOD-009 |
| T-28 | Injected instructions, such as a crafted log line, make the agent run commands or change files on a user's connected device | X1 | AGT-003, AGT-018, DEV-007 |
| T-29 | A remote MCP server, malicious or compromised, injects instructions through its tool descriptions or results, or changes its tools after they were reviewed | X1, X5 | AGT-003, AGT-018, AGT-019, AGT-028 |
| T-30 | A stolen device credential lets an attacker pose as the device, receive its tool calls and return forged results | X4 | DEV-001, DEV-002 |
| T-31 | A tenant admin uses connection tests to probe the household's network, or to read what internal services answer, through the details of failed steps | X2 | MOD-009, MOD-013 |
| T-32 | A dependency or an asset of the web app contacts a third party at run time, telling it who uses the instance and when, or making the instance depend on it | X5 | OBS-001, OBS-006 |
| T-33 | Injected instructions plant files or programs in a sandbox that steer or attack later runs, and are carried into backups | X1 | SBX-001, SBX-018, SBX-019, OPS-006, AGT-003, AGT-022 |

## The lethal trifecta in Sibillo

The assistant necessarily combines all three elements: it reads private data,
it reads untrusted content, and some tools communicate externally. The
sandbox does not help here — the risk lives in the tools. The mitigation is
to break the trifecta **within each run**:

1. Every tool declares its capability classes (AGT-005).
2. Content entering a run is labeled with its provenance (AGT-003).
3. The web tools and the sandbox's network need internet access, which the
   user gives for a turn or a conversation, never beyond it; without it a
   sandbox has no network, so commands cannot send anything out (AGT-034,
   SBX-024, ADR-0113).
4. Once untrusted content is part of a run, the other tools in the
   `external_communication` class require explicit user approval (AGT-004).
   Untrusted content counts in every later turn of the conversation
   (ADR-0090).
5. Approvals fail closed (AGT-007) and every tool call is auditable
   (AGT-008).
6. A task, which runs while nobody watches, carries grants instead of
   asking; its grants together never reach private data, untrusted content
   and an open way out at once, and a fixed grant carries nothing the model
   chose (TSK-004, TSK-005, ADR-0106).
7. Evals include injection scenarios that must not exfiltrate (EVL-003).

Prompts are never relied upon as a security boundary.

## Residual risks

- **What a household can learn of names.** Usernames are unique in the
  instance, so a tenant admin creating a user learns whether a name is taken
  in another household; members see the names and roles of their own
  household's users; an attacker who fails on purpose can keep a known
  username from signing in for 15 minutes at a time (ADR-0047, ADR-0131).
- **One key for every secret.** Connection keys, credentials, client
  secrets and the notification key all come from one key, without a
  version; a leak of it exposes all of them, and rotating it needs every
  secret encrypted again (ADR-0128).
- **What runs on after untrusted content arrives.** A command started
  before a run held untrusted content keeps running, and may run files
  written under injection, such as a server that reloads its code; a
  change of permissions or switches applies from the next run (ADR-0127).
- **A link the assistant wrote.** Injected content can make an answer link
  to an address that carries private data in its path or query. Clients
  show the link's host before it is clicked, but not the rest of the
  address, and following a link never asks (UX-002, ADR-0126).
- **An OAuth mix-up through Sibillo's client documents.** A malicious
  remote MCP server of the household can name its own client document of
  Sibillo at an honest authorization server that reads them and does not
  send `iss`, and obtain a code of that server for its token endpoint. It
  needs a tenant admin to add the malicious server and a user to sign in to
  it; redirect addresses and documents of each server stop every other form
  of the mix-up (AGT-031, ADR-0122).
- **Exfiltration from a compromised sandbox.** A sandbox whose conversation
  has internet access can send out the data it contains. This is bounded to
  the conversations whose user gave them internet access, to that
  conversation's workspace and the answer it runs in, which never contain
  secrets (SBX-001, SBX-008, SBX-024, ADR-0078, ADR-0113).
- **Approval fatigue.** Users may approve requests without reading them.
  Approval prompts must show what will be sent and where, and are kept rare:
  a conversation asks for internet access at most once (ADR-0090, ADR-0113).
- **Internet access in a conversation.** A user who gives a conversation
  internet access accepts that injected instructions could send out what it
  holds and its workspace, until they withdraw it. It is often given before
  any untrusted content exists, and stays as that content arrives; its
  request says so, and does not show the later calls it covers (AGT-034,
  ADR-0113).
- **A web page leaving its frame.** A page the assistant made runs with an
  opaque origin and no network access, but it can still navigate its own
  frame to another address, carrying data it holds, and it relies on the
  browser's sandbox and policy enforcement rather than on a separate domain
  (ADR-0086). Browsers that ignore `webrtc 'block'`, Firefox and Safari
  today, let it open a peer connection too. What a page holds is what the
  assistant wrote into it, and a run with untrusted content can choose it:
  writing a file never asks (ADR-0090, ADR-0125).
- **What a task with open web grants holds.** Injected content in a page
  that such a task reads can send out what its run holds: the task's
  instructions, the user's instructions and what it found on the web. The
  task has no other private data by construction (TSK-005); its user writes
  its instructions knowing that (ADR-0106).
- **A fixed grant repeated.** Injected content can make a task's run repeat
  a call that a fixed grant covers, within the task's limits, but cannot
  change it (TSK-004, TSK-009).
- **A tenant admin ahead of a new member.** The admin who chose an
  initial password can sign in with it before the member does and change it
  (T-41). The member is then locked out, which they notice; the admin cannot
  do it silently (ADR-0105).
- **Model-level manipulation without tools.** An injected page can still make
  the assistant give a wrong answer. Provenance labels make this visible but
  cannot prevent it.
- **Isolation runtime vulnerabilities.** gVisor reduces but does not
  eliminate kernel attack surface. A dedicated guest kernel per sandbox
  (microVMs) would isolate more strongly, but requires hardware virtualization,
  which cloud VMs often lack; this trade-off is accepted (ADR-0023). Egress
  enforcement does not depend on gVisor's integrity (ADR-0021).
- **A privileged sandbox engine.** The container that runs the sandboxes is
  privileged, which is root on the host in effect: an escape from gVisor, or
  a compromised sandbox driver, reaches the host as it did when sandboxes
  were containers of the host's Docker. Only the driver can ask the engine
  anything, and no sandbox can reach it (SBX-009, SBX-025, ADR-0114).
