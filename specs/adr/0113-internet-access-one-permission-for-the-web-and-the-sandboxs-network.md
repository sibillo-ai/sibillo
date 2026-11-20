# ADR-0113: Internet access, one permission for the web and the sandbox's network

- **Status:** Proposed
- **Date:** 2026-11-21
- **Deciders:** @tapionx
- **Related:** ADR-0012, ADR-0021, ADR-0033, ADR-0078, ADR-0087, ADR-0088, ADR-0090, ADR-0106, AGT-002, AGT-003, AGT-004, AGT-005, AGT-006, AGT-007, AGT-012, AGT-020, AGT-021, AGT-034, SBX-004, SBX-005, SBX-007, SBX-015, SBX-018, SBX-024, TSK-004, TSK-005, UX-005, UX-022, UX-023, UX-041

## Context

ADR-0090 made approvals few: one approval covers the four web and command
tools, for a turn or a conversation, and it is asked only once a run has
untrusted content. Daily use showed where this still falls short:

- **Several prompts for one step.** A model that searches the web calls
  `web_search` two or three times at once. Each call is an approval request
  of its own, and the client shows them one after another, also after the
  first was answered for the whole conversation.
- **A question about a call, when the answer is about a capability.** The
  request shows one query or one address, but the answers that matter, for
  the turn or for the conversation, allow every later search, page and
  command. After the first answer nobody reads a call again.
- **A rule that is hard to explain.** The first search of a conversation
  asks nothing; the page read right after it asks, because the search
  results made the run untrusted. A user cannot tell when a prompt will come.
- **Hands-free mode stops without a word.** An approval request ends the
  run. In hands-free mode nothing says so and nothing on the screen answers
  it, so the conversation stands still until the user leaves the mode
  (UX-005).
- **The sandbox always reaches the internet** (SBX-004). Every command can
  therefore send data out, which is why `run_command` and `start_command`
  communicate externally, and why the only defense is a prompt that comes
  after untrusted content is already in the run. The threat model records
  what a compromised sandbox can send out as a residual risk.

## Decision

1. **Internet access is one permission of a conversation.** Without it, the
   web tools `web_search` and `read_page` do not run, and the conversation's
   sandbox has no network at all: no connection to any address, and no name
   resolution. With it, the web tools run, and the sandbox reaches public
   addresses as it did before, never local ones (SBX-005 to SBX-007). The
   user is asked "may the assistant access the internet?", not "may it
   search for this?" (AGT-034).

2. **Commands need no approval.** A command in a sandbox without network
   cannot send anything out, so `run_command` and `start_command` leave the
   `external_communication` class: their only way out is the sandbox's
   network, which internet access governs. This amends the table of
   ADR-0090 point 1:

   | Tools | Classes | Default |
   |---|---|---|
   | `web_search`, `read_page` | `ingests_untrusted`, `external_communication` | allowed, and they need internet access |
   | `run_command`, `start_command` | `reads_private_data`, `ingests_untrusted` | allowed |
   | `request_internet_access` | none | allowed |

   The other rows stand. The trifecta rule of AGT-004 no longer names the
   four web and command tools: internet access takes its place for them, and
   the rule stays for every other tool that communicates externally.

3. **Asking.** A call to `web_search` or `read_page` in a conversation
   without internet access asks for it. For commands the server cannot know
   whether one needs the network, so the assistant has a tool,
   `request_internet_access`, without arguments. The request is made
   whether or not the run has untrusted content. All the calls of one run
   that need internet access make **one** approval request, with the reason
   `internet_access`. Built by the server from the stored calls (AGT-012), it
   says what internet access lets the assistant do, that what the
   conversation holds and its files could then be sent out, whether the run
   already has untrusted content, and which web calls wait for it, with
   their queries and addresses. The tool has no arguments so that nothing
   the model writes is part of the request: the model gives its reasons in
   its answer, where they are read as the model's.

   The answers offered are **Deny**, **Allow for this turn** and **Allow in
   this conversation**. "Allow once" is not offered: a network that is on
   for one command is on for whatever that command starts. When the user
   allows it, the waiting web calls run and `request_internet_access`
   answers that the network is on. When the user denies it, every waiting
   call is denied and the model is told; any later call that needs internet
   access in the same turn is denied at once, without asking, so that
   injected instructions cannot ask until the user gives in. A request that
   expires is denied (AGT-007).

4. **It is an allowance.** Internet access is created only by answering a
   stored approval request, never by a settings change; it is listed with
   the conversation, its user can withdraw it, and a fork does not copy it.
   Withdrawing it takes the network from a running sandbox at once. There is
   no standing internet access beyond one conversation, and no setting that
   gives it to new conversations: the reasons of ADR-0090 stand. It replaces
   the allowance of the web and command tools of ADR-0090 points 3 and 4; a
   conversation that holds that allowance holds internet access.

5. **Tool permissions.** A tenant admin who sets the
   `external_communication` class to `deny` for a user also denies them
   internet access: it is never asked and never given, and their sandboxes
   never have network. No tool permission gives internet access, since that
   would be a standing allowance. `request_internet_access` has a switch like
   every tool (ADR-0087), in the Web group.

6. **Enforced outside the sandbox.** A sandbox starts without network, and
   gets it only when the control plane tells the sandbox driver that its
   conversation has internet access; the driver takes it away when the
   allowance is withdrawn or ends. Like the local ranges of SBX-005, this is
   enforced outside the sandbox's kernel and holds for code with full
   control of the sandbox's network configuration. It includes DNS: without
   internet access not even the instance's resolver is reachable, or names
   would carry data out. It fails closed: a sandbox whose state the driver
   cannot verify has no network, and it is verified before any code runs
   (SBX-015, SBX-024). A sandbox that waits for the user's answer keeps its
   scratch folder and its background commands (ADR-0090 point 8), so the
   network is switched on a running sandbox, not by starting a new one.

   **A bridge for each sandbox, and a set of the bridges that are online.**
   Each sandbox attaches to a sandbox bridge of its own, created by the
   driver with a name it chooses, under a fixed prefix, and a subnet of four
   addresses from a range of the instance. The egress table matches every
   bridge with the prefix: the rules of ADR-0021 stand for all of them, and
   one rule more drops everything from a bridge that is not in a set of the
   table, the bridges whose conversation has internet access. Giving
   internet access adds the bridge's name to the set, withdrawing it removes
   it. Which bridge a packet enters from is decided by the host, so nothing
   a sandbox does to its own network configuration changes it. The driver
   removes a sandbox's bridge with the sandbox.

   A spike settled this, on 2026-11-21, on Ubuntu 26.04 with kernel 7.0, an
   AMD Ryzen 9 5950X without `/dev/kvm`, Docker 29.1.0, gVisor
   `release-20261116.0` and nftables 1.1.6, with a table and bridges of its
   own beside the deployment's:

   | Design | Result |
   |---|---|
   | One shared bridge, and a set of the source addresses that are online | **Failed.** Giving and withdrawing worked on a running gVisor sandbox, but a container with `NET_ADMIN` and raw sockets on the same bridge, emulating a compromised sandbox kernel, took the address of an online sandbox and reached the internet, with UDP and with a complete HTTP request |
   | Two bridges, one without a way out, and the running sandbox moved between them with Docker | **Failed.** Docker connected the gVisor sandbox to the second network, but the sandbox never saw the new interface; once disconnected from the first it had no network at all. A runc container, as a control, got the interface |
   | A bridge for each sandbox, and a set of the bridges that are online | **Passed.** A sandbox out of the set reached nothing, by address or by name; in the set it reached the internet at once, without a restart, and its resolver alone on port 53; out of the set again, the packets it kept sending stopped at once. It never reached another sandbox or the host. The container with `NET_ADMIN`, on a bridge out of the set, was dropped as itself, with an online sandbox's address, and with its address and MAC, while that sandbox kept working. A bridge took 0.07 s to create; with 42 bridges a sandbox still started in 0.37 s |

   Replacing the sandbox with a new one when internet access is given was
   not tried: it loses the scratch folder and the background commands,
   against ADR-0090 point 8, and the third design does not need it.

   The network guard owns the table, so it changes the set: the driver
   tells it, over a Unix socket in a volume that only the two share, which
   bridges are online, always as the whole list. A guard that reinstalls the
   table starts with an empty set, so every sandbox is without network until
   the driver says again; a driver that cannot reach the guard treats the
   egress table as missing (SBX-015). This channel was not part of the
   spike. This amends ADR-0021 points 1 and 3.

7. **Tasks.** A task grant of internet access is a third kind of grant,
   beside fixed and open grants: it gives internet access to the runs of the
   task's first turn. Without it, a call that needs internet access in those
   runs is denied at once with the reason `not_granted`. In the check of
   TSK-005 it counts as a source of untrusted content and as external
   communication. Open grants of `web_search` and `read_page` are no longer
   needed, and a task that has one has a grant of internet access instead.
   Commands need no grant, and run without network unless the task has the
   grant. This amends ADR-0106 points 4 and 5.

8. **The assistant knows.** The instructions say that the sandbox has no
   network and that the web tools need internet access; that the assistant
   asks for it once, when the work needs it, rather than trying commands
   that will fail; and that the tools of the sandbox image need no network
   (SBX-021).

9. **Approval requests in hands-free mode.** When a run ends with an
   approval request in hands-free mode, the client plays a sound of its own,
   says the request aloud, and shows it in the lower half of the screen in
   place of the large button, with a large button for each answer the
   request offers, Deny first, none preselected (UX-041). What is said aloud
   is a fixed sentence of the client, translated like its other strings and
   chosen by the request's reason: for internet access, that the assistant
   asks to access the internet; for any other request, that a request waits
   on the screen, with the tool's label. Nothing the model wrote is spoken as
   part of a request. A request is answered only by its buttons: not by
   voice, since the microphone hears more than the user, and not by the
   media buttons of a headset or a car, which only say the request again.
   The microphone stays closed while a request is pending. Once it is
   answered the turn goes on as any other, and its answer is read aloud.
   This amends ADR-0088.

## Consequences

- A conversation asks for the internet at most once, in words that say what
  is at stake, and several searches at once ask once.
- Without internet access the lethal trifecta cannot complete through the
  web tools or the sandbox: the mitigation no longer rests on a prompt that
  comes after untrusted content. What a compromised sandbox can send out is
  bounded to conversations whose user gave them internet access.
- The request no longer shows every call. It shows the web calls that wait
  for it; later calls are covered by the allowance, as they were after
  "allow in this conversation". The user gives internet access more often
  before any untrusted content exists, and it stays as that content
  arrives: this is what the request says, and it is recorded as a residual
  risk.
- Commands that need the network, such as installing a package, fail until
  the assistant asks. The tools of the sandbox image cover ordinary work
  without network; evals must show that models ask rather than retry.
- A first search now asks, where it did not before. One prompt for each
  conversation that uses the web is the cost of a rule a user can predict.
- SBX-004 changes: a sandbox reaches the internet only while its
  conversation has internet access. The network guard and the sandbox
  driver gain work that is security-critical, with security tests from
  inside a sandbox and from a container with network administration
  privileges, as for SBX-005.
- Contracts to change once this is accepted: in the public API, the reason
  `internet_access` and its request, one interrupt for the calls that wait
  on it, the allowance of internet access in place of that of the web and
  command tools, the tool `request_internet_access`, and the task grant of
  internet access; in the database, the columns that hold the allowance for
  the conversation and for the turn, and the grant; in the sandbox driver's
  API, how a sandbox's network is given and taken; in the configuration,
  the range the sandbox bridges take their subnets from, which bounds how
  many sandboxes run at once. Stored allowances and task grants move over
  as points 4 and 7 say.
- Sandboxes no longer share a bridge, so one cannot pose as another on it,
  and SBX-006 no longer rests on a bridge option. The driver creates and
  removes a bridge with every sandbox, and must remove the ones a crash
  left behind when it starts.
- Questions to the user in hands-free mode (AGT-015) are not decided here.

## Alternatives considered

- **Two permissions, "online access" and "code execution":** the first
  idea. While the sandbox reaches the internet, running code includes going
  online, so the two would name a separation that does not exist; and
  commands without network need no permission at all.
- **Keep ADR-0090 and only merge the requests of one run:** removes the
  repeated prompts, but keeps the question about a call, the rule nobody can
  predict and a sandbox that is always online.
- **One shared bridge with a set of addresses, or moving a sandbox between
  two bridges:** both failed in the spike of point 6.
- **Leave the network on and ask before commands:** what ADR-0090 does; the
  defense is a prompt alone.
- **Let `read_page` read without asking the addresses that search results
  or the user gave:** would make the web silent, but a hostile page can
  still publish one link for each value it wants to learn, and commands
  would need a permission of their own anyway. It can be added later.
- **A switch the user turns on before asking, or a default for new
  conversations:** convenient for hands-free mode, but an allowance made
  without a request is the standing allowance ADR-0090 rejected.
- **Answering by voice in hands-free mode:** no touch needed, but the
  microphone hears passengers, the radio and the assistant's own voice.
- **An argument of `request_internet_access` that says why:** useful to the
  user, but it would put text an injected page can dictate inside a request
  the user trusts.
