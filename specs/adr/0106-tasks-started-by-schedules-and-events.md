# ADR-0106: Tasks started by schedules and events

- **Status:** Proposed
- **Date:** 2026-11-19
- **Deciders:** @tapionx
- **Related:** TSK-001 to TSK-010, UX-031, DEV-010, AGT-002, AGT-003, AGT-004, AGT-006, AGT-018, AGT-019, AGT-028, AGT-030, UX-004, ADR-0034, ADR-0063, ADR-0064, ADR-0090, ADR-0099

## Context

Every conversation starts today because the user writes. Much of what an
assistant is for happens while nobody writes: a press review ready on
waking, a weekly check of the security updates of one's servers, a word on
the mail that just arrived. The glossary has had a "scheduled task" since
phase 0, and the worker was built to run them (ADR-0026, ADR-0034), but no
requirement said what one is.

Three forces shape it:

- **Nobody is there to approve.** A run that stops at its first approval
  request delivers nothing by the morning, and an approval left for 24 hours
  is denied (AGT-007). A task must carry, from the start, the permissions it
  needs. Yet those permissions are what injected content would abuse: the
  task reads web pages, mail and logs that an attacker may write (T-08), and
  nobody watches it run.
- **Many sources of events.** Mail, messaging apps, home automation,
  devices: writing an integration of each into Sibillo grows the control
  plane with code that handles credentials and untrusted input, one service
  at a time.
- **A standard just appeared.** MCP, which Sibillo already uses for tools
  (ADR-0020, ADR-0064, ADR-0099), gained an Events extension,
  `io.modelcontextprotocol/events` (SEP-3415, merged on 2026-11-19): a server
  lists the types of event it emits, with a JSON Schema of the arguments of a
  subscription and of the event's data, and delivers events by polling, by a
  stream or by webhooks signed as Standard Webhooks. Each event has an ID for
  deduplication and a cursor to resume from. The extension calls event data
  untrusted, like tool results, and leaves to the client whether an event
  starts a turn of the model.

## Decision

1. **A task.** A user's task has instructions, conversation settings (model,
   reasoning, enabled tools, use of memory), a time zone, one or more
   triggers and its task grants. It is private to its user like every other
   piece of their data (TEN-007). A user creates, changes, pauses and deletes
   their tasks in the settings (TSK-001, UX-031), or the assistant proposes
   one in a conversation (point 8). A task fires whether or not its user is
   signed in, under the user's data egress policy and tool permissions as
   they stand at the firing, and stops firing when the account is disabled
   (TSK-010).

2. **Each firing is a new conversation.** When a trigger fires, the worker
   starts a new conversation of the task's user, linked to the task, whose
   first message is the task's instructions, followed by the event, if any,
   as untrusted content. The conversation is listed with the others, marked
   with the task's name, and the task lists every conversation it started,
   with its outcome (TSK-002). The run notifies its user like any other
   (UX-004). From then on it is an ordinary conversation: the user can read
   it, continue it, fork it or delete it. A fresh conversation for each
   firing keeps the context small and every firing apart; a task that wants
   the previous result says so in its instructions, and memory, when the
   task uses it, carries what should last.

3. **Triggers.** Three kinds, one mechanism behind them: a firing, with or
   without an event, starts a conversation (point 2).
   - A **schedule**: a cron expression evaluated in the task's time zone,
     firing at most once every 15 minutes. The worker owns schedules as
     durable workflows (ADR-0034), so a firing is never lost or doubled: one
     firing, one conversation. Firings missed while the instance was down
     are not replayed one by one: the worker fires once, for the latest one
     (TSK-003).
   - A **webhook trigger**: a secret address of the instance, for senders
     that can only make an HTTP request, such as a home automation rule or a
     mail forwarding service. The address holds a random token of at least
     256 bits, stored only as a hash and shown once; the body, at most
     64 KiB, is the event (TSK-007).
   - An **event of a remote MCP server**: the server's event types are
     reviewed by a tenant admin as its tools are (point 6), and the user
     subscribes to an accepted type with the arguments it declares, with
     their own server credential when the server needs one (TSK-008).
     Devices will emit events over the same extension, on the MCP connection
     they open (DEV-010, ADR-0063).

4. **Task grants.** A task carries grants, approved by its user when the task
   is saved: the calls its runs may make without asking. A grant is one of:
   - a **fixed grant**: one tool with all of its arguments fixed, such as
     `run_command` on a device with the command `apt list --upgradable`. A
     call matches it only when its arguments equal the grant's. The model
     chooses nothing in such a call, so injected content cannot use it to
     carry data out: at most it can make the task repeat it;
   - an **open grant**: one tool, with any arguments, such as `web_search`.

   Grants cover the runs of the task's first turn only: the run the firing
   starts and the runs that resume it. Once the user writes in the
   conversation, its runs follow the ordinary rules. A call that no grant
   covers, and that would need an approval, **is not asked**: it is denied at
   once with the reason `not_granted`, the model is told so, and the run goes
   on. The conversation shows the calls denied this way, so the user who
   opens it can ask the assistant to go on, with the ordinary approvals
   (TSK-004).

   A grant never covers a tool in the `irreversible` or `physical` classes
   (AGT-006), a tool that a tool permission sets to `ask` or `deny` for the
   user (AGT-002), a tool that is not offered (a switched-off group, a server
   tool no longer accepted, AGT-028), or the task tool of point 8. Grants
   are checked when the task is saved and again at every call.

   This amends ADR-0090 point 4, "there is no standing allowance beyond one
   conversation", and ADR-0063 point 5 and AGT-018, which ask every call to a
   device or an MCP server: a fixed grant is the user's approval, given in
   advance for one exact call. Open grants never cover a tool of a device or
   of a remote MCP server.

5. **Grants never complete the lethal trifecta.** When a task is saved, and
   again at every firing, the server checks three things together:
   - **private data**: a grant, fixed or open, of a tool in the
     `reads_private_data` class; memory, when the task uses it and memory is
     on for the user; an event trigger, a webhook trigger or a trigger on an
     event, since an event may carry the user's mail or messages;
   - **untrusted content**: a grant, fixed or open, of a tool in the
     `ingests_untrusted` class; an event trigger;
   - **external communication**: an open grant of a tool in the
     `external_communication` class. A fixed grant does not count: its
     arguments carry nothing the model chose.

   A task MUST NOT have all three. A task that would is not saved, with the
   reason; a task that no longer passes at a firing, because a tool
   permission or its settings changed, fires without grants, and the
   conversation says why (TSK-005).

   The two examples pass. A press review has open grants of `web_search`
   and `read_page` (untrusted content and external communication), no
   memory and no private data. A weekly check of updates has a fixed grant of
   a device command (private data and untrusted content) and nothing that
   sends data out. A task fired by a mail may summarize it, but may not
   search the web or reply without asking. Tools of remote MCP servers are
   in all three classes (ADR-0099), so they could not pass with an open
   grant anyway; fixed grants of them can.

   Within a run, the trifecta rule of AGT-004 still holds: an open grant
   lifts it only for the calls it covers, and only because the task has no
   private data that those calls could carry.

6. **Event types are reviewed like tools.** A remote MCP server that offers
   the Events extension lists its event types with `events/list`. A tenant
   admin accepts or withdraws each one, as for tools (AGT-028), seeing its
   name, description and schemas; a type that changes after it was accepted
   is offered no longer until it is accepted again. Users subscribe only to
   accepted types of servers they may use (AGT-029).

   The worker supports two of the extension's delivery modes:
   - **polling** (`events/poll`), which needs no address of the instance
     that the server can reach, honouring the server's `nextPollMs` with a
     floor of one minute;
   - **webhooks** (`events/subscribe`), when the instance has a public
     origin: the worker gives each subscription its own secret, renews the
     subscription before its `refreshBefore`, and the API accepts a delivery
     only with a valid Standard Webhooks signature, a timestamp less than
     five minutes old, and a `webhook-id` not seen before.

   Streams (`events/stream`) wait until they are needed: they hold a
   connection per subscription. Events are deduplicated by their `eventId`.
   Their data is untrusted content (AGT-003), bounded as tool results are
   (AGT-014). Subscribing and polling reach only the server's own address,
   checked as for its tools (AGT-019); no new declared destination is added.

7. **Limits.** A task starts at most 10 conversations an hour. Firings over
   the limit, and events that arrive while the task is paused, are not run:
   the task counts them and shows the latest. One firing of a task runs at a
   time; firings that arrive meanwhile wait, up to the limit (TSK-009). A
   flood of events, forged or real, costs at most that.

8. **Proposed in a conversation.** The assistant has a tool that proposes a
   task, with its instructions, settings, triggers and grants. It is always
   asked, for every call, and its approval request shows the whole task,
   grants included, as the task's page would; approving it saves the task
   (TSK-006). It cannot be granted to a task, so a task never creates tasks.
   The approval is the user's, but its content may come from injected
   instructions in a run with untrusted content; the approval request says
   so when it does.

9. **Connectors live outside Sibillo.** A mail account, a messaging app or a
   calendar becomes a source of events and tools by being a remote MCP
   server, run by the household or by a third party, never by code of the
   control plane. Sibillo keeps one interface for tools and one for events,
   both MCP; the webhook trigger is the only integration of its own, for
   senders that speak no MCP.

## Consequences

- The assistant works while nobody watches: a press review, a weekly report,
  a reaction to a mail. This is the first time a run acts on standing
  permissions, so the grants' rules (points 4 and 5) carry the weight that
  approvals carry elsewhere. Their checks are security requirements, with
  tests that try to break them.
- An open grant of web tools lets injected content in a page send out what
  the run holds: the task's instructions, the user's instructions and what
  the task found on the web. A task with open web grants has no private data
  by construction; its instructions are written by the user knowing that.
  This is recorded as a residual risk.
- Some useful tasks need the user: a task fired by a mail cannot search the
  web unattended, and a task cannot install updates (`irreversible`
  commands are never granted). They run as far as their grants go, and the
  user continues them with the ordinary approvals.
- Tasks are a new phase, before connected devices, so that a press review
  works with the web tools of phase 1. The check of a server's updates waits
  for devices, and device events come with them (DEV-010). The roadmap's
  phases are renumbered: connected devices become phase 3, the first release
  phase 4 and opening up phase 5.
- The worker gains schedules and event subscriptions; the API gains two
  unauthenticated endpoints, for webhook triggers and for MCP event
  deliveries, both rate-limited, bounded and answering the same for an
  unknown address as for a refused one.
- The Events extension is days old. The worker implements the client side
  of polling and webhooks itself if the MCP Python SDK does not have them
  yet, and follows the SDK when it does (REPO-010).
- Sibillo needs MCP servers for mail and messaging, written by others or
  run beside it as separate containers. None of them is part of the control
  plane. For WhatsApp, only the Business Cloud API is offered by its owner;
  bridges to a personal account break its terms and risk the number.

## Alternatives considered

- **Every firing in the same conversation:** a running history ("compared
  with yesterday"), but a context that grows without end, compaction on
  every firing, and one firing's untrusted content counting in all the
  next (AGT-003).
- **Stop and ask, as now:** keeps the security model unchanged, but defeats
  the purpose: the press review would wait for the user who wakes up, and an
  approval request left overnight is denied.
- **Grants by tool only:** simpler, but a granted `run_command` on a device
  runs anything injected content asks for. Grants by command prefix were
  dropped too: `apt list; curl …` starts with `apt list`.
- **Integrations in the control plane** (IMAP, a messaging bridge): quicker
  for the first one, but each brings credentials and untrusted parsing into
  the control plane, and the tenth is as much work as the first.
- **Webhooks only, no MCP events:** works with anything that can send a
  request, but leaves every service to be glued by hand, with no schema, no
  review of what an event carries and no resumption after a gap.
- **CloudEvents as the envelope:** a wide standard for event data, but it
  leaves out subscriptions, schemas and signatures, which the MCP extension
  defines and Sibillo would have to invent.
