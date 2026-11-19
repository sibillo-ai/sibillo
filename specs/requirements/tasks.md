# TSK — Tasks and triggers

Conversations that start without a message from the user: on a schedule,
from a webhook, or from an event of a remote MCP server, with the task
grants they need to work while nobody watches. Background: ADR-0106.

## TSK-001: Tasks

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 2
- **Verification:** integration

A user MUST be able to create, list, change, pause, resume and delete their
own tasks. A task MUST have instructions, conversation settings (model,
reasoning, enabled tools and whether it uses memory), a time zone, at least
one trigger and its task grants. A task MUST be private to its user: no other
user, tenant admin included, can see it, change it or fire it (TEN-007). A
paused task MUST NOT fire (ADR-0106).

## TSK-002: Every firing is a new conversation

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 2
- **Verification:** integration

When a trigger of a task fires, the worker MUST start a new conversation of
the task's user, linked to the task, whose first message holds the task's
instructions as trusted content and the event, if any, as untrusted content
(AGT-003). The conversation MUST be listed with the user's others, marked
with the task's name, and MUST otherwise be an ordinary conversation that the
user can continue, fork and delete. A task MUST list every conversation it
started that still exists, with when it started and how its run ended, newest
first (ADR-0106).

## TSK-003: Schedules

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 2
- **Verification:** integration

A schedule MUST be a cron expression evaluated in the task's time zone, and
MUST be refused when it would fire more often than once every 15 minutes.
Each firing MUST start exactly one conversation, also across a restart or a
crash of the worker. When the instance was down at one or more firing times,
the task MUST fire once when the worker returns, for the latest of them, and
not once per missed time (ADR-0106).

## TSK-004: Task grants

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 2
- **Verification:** integration, security

A task's user MUST be able to give it grants: fixed grants, of one tool with
all its arguments, which cover a call only when its arguments equal the
grant's; and open grants, of one tool with any arguments. Grants MUST cover
only the runs of the task's first turn, and MUST NOT cover a tool in the
`irreversible` or `physical` classes, a tool that a tool permission sets to
`ask` or `deny` for the user (AGT-002), a tool not offered to the run, or the
tool that proposes a task (TSK-006). In those runs, a call covered by a grant
MUST run without approval, but a call to a device or a remote MCP server
only when a fixed grant covers it (AGT-018); a call that is not covered and would need approval MUST be denied
at once, without asking, with the reason `not_granted`, and the model MUST be
told so. The conversation MUST show the calls denied this way. Grants MUST
be checked when the task is saved and at every call (ADR-0106).

## TSK-005: Task grants never complete the lethal trifecta

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 2
- **Verification:** security

A task MUST NOT be saved when it has all three of: a source of private data
(a grant of a tool in the `reads_private_data` class, use of memory while
memory is on for its user, or an event trigger, which is a webhook trigger or
a trigger on an event); a source of untrusted content (a grant of a tool in
the `ingests_untrusted` class, or an event trigger); and an open grant of a
tool in the `external_communication` class. Fixed grants MUST NOT count as
external communication. The check MUST be repeated at every firing, and a
task that fails it then MUST fire without grants, its conversation saying
why (ADR-0106).

## TSK-006: The assistant proposes a task

- **Status:** implemented
- **Priority:** SHOULD
- **Phase:** 2
- **Verification:** integration

The assistant SHOULD have a tool, `propose_task`, that proposes a task with
its instructions, settings, triggers and grants, given as the fields of a
request to create a task. Every call to it MUST require the user's
approval, whose request MUST show the whole task as its page shows it, and
say when the run holds untrusted content; only approving it MUST save the
task, after the checks of TSK-004 and TSK-005. It MUST NOT be granted to a
task (ADR-0106).

## TSK-007: Webhook triggers

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 2
- **Verification:** integration, security

A task's user MUST be able to give it a webhook trigger: an address of the
instance holding a random token of at least 256 bits, shown to the user once,
stored only as a hash, and replaceable, which makes the old address stop
working. A request to that address with a body of at most 64 KiB MUST fire
the task with the body as its event. A request to an unknown, replaced or
deleted address, or to a paused task's, MUST receive the same answer as one
that fired a task. Requests MUST be rate-limited per address and per source
address (ADR-0106).

## TSK-008: Events of remote MCP servers

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 2
- **Verification:** integration, security

The control plane MUST support the MCP Events extension
(`io.modelcontextprotocol/events`) for remote MCP servers (AGT-019): it MUST
list a server's event types, and a tenant admin MUST accept or withdraw each
one, which is offered only while the server lists it unchanged, as for tools
(AGT-028). A user MUST be able to give their task a trigger on an accepted
event type of a server they may use, with the subscription's arguments, using
their own server credential when the server needs one (AGT-030). The worker
MUST receive events by polling, at most once a minute, and SHOULD receive them
by webhooks when the instance has a public origin, accepting a delivery only
with a valid Standard Webhooks signature with the subscription's own secret,
a timestamp less than five minutes old and a delivery ID not seen before. An
event MUST fire the task at most once, by its event ID, and its data MUST be
bounded as tool results are (AGT-014) (ADR-0106).

## TSK-009: Limits on firing

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 2
- **Verification:** integration

A task MUST NOT start more than 10 conversations in an hour, and MUST run one
firing at a time, the others waiting their turn. Firings over the limit, and
events that arrive while the task is paused, MUST NOT run; the task MUST
count them and show when the latest was skipped (ADR-0106).

## TSK-010: Tasks need no one to be signed in

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 2
- **Verification:** integration

A task MUST fire and run while its user has no client open and no session,
and MUST stop firing when its user's account is disabled or deleted. Its runs
MUST follow the user's data egress policy (MOD-003) and tool permissions
(AGT-002) as they stand at the firing, and MUST be recorded in their cost
ledger (MOD-006) and audit events (AGT-008) like any other run (ADR-0106).

## TSK-011: Running a task now

- **Status:** accepted
- **Priority:** MUST
- **Phase:** 2
- **Verification:** integration

A task's user MUST be able to fire it at once, also while it is paused. Such
a firing MUST be recorded as `manual`, MUST count toward the limit of
TSK-009 and wait its turn as any other, and its runs MUST follow the task's
grants as TSK-004 and TSK-005 say (ADR-0107).

## TSK-012: The assistant changes a task

- **Status:** accepted
- **Priority:** SHOULD
- **Phase:** 2
- **Verification:** integration

The assistant SHOULD have a tool, `update_task`, that changes one of the
user's tasks with the fields of a request to change a task, pausing and
resuming included. Every call to it MUST require the user's approval, whose
request MUST show the change in full and say when the run holds untrusted
content; only approving it MUST apply the change, after the checks of
TSK-004 and TSK-005. It MUST NOT be granted to a task (ADR-0107).

## TSK-013: The assistant reads the user's tasks

- **Status:** accepted
- **Priority:** SHOULD
- **Phase:** 2
- **Verification:** integration

The assistant SHOULD have a tool, `list_tasks`, that lists the user's own
tasks with their instructions, triggers, next firing, grants and whether they
are paused, and their latest firings with when each started, how its first
run ended and its conversation's ID and title. It MUST NOT list another
user's tasks, and its result MUST be trusted content (ADR-0107).
