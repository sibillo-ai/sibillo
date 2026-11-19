# ADR-0107: Tasks in use, and the assistant reading the user's conversations

- **Status:** Proposed
- **Date:** 2026-11-19
- **Deciders:** @tapionx
- **Related:** TSK-011 to TSK-013, AGT-003, AGT-032, AGT-033, UX-031, UX-033, CNV-009, CNV-011, ADR-0068, ADR-0090, ADR-0095, ADR-0096, ADR-0106

## Context

The first use of tasks (ADR-0106) showed what is missing once a task
exists. A user who wants to try a task waits for its schedule. The assistant
that proposed a task cannot change it, and when asked "how did it go?" it
cannot tell: it sees only the conversation it is in, while each firing
starts a conversation of its own. More generally, the user's earlier
conversations are out of the assistant's reach, although the user can
search them in the app (CNV-009).

Reading another conversation brings its content into the run. That content
is the user's own private data, and some of it may be untrusted content:
pages, command output, attachments or an event that fired a task (AGT-003).
Injected instructions must not pass from one conversation to another
unseen, as they must not through memory items (ADR-0095) or skills
(ADR-0096).

## Decision

1. **Running a task now.** A user fires a task at once from the app,
   paused or not (`POST /tasks/{id}/fire`). The firing is of kind `manual`,
   counts toward the limit of 10 an hour, waits its turn as any other, and
   follows the task's grants (TSK-011).

2. **The assistant changes a task.** `update_task` takes a task's ID and the
   fields of a change, as `PATCH /tasks/{id}` takes them, pausing and
   resuming included. As `propose_task`, every call is asked, once, with the
   whole change in its approval request and whether the run holds untrusted
   content; only the approval applies it, after the checks of TSK-004 and
   TSK-005. It cannot be granted to a task (TSK-012).

3. **The assistant reads the user's tasks.** `list_tasks` lists the user's
   tasks: name, instructions, triggers, next firing, whether it is paused,
   its grants, and its latest firings with when they started, how their
   first run ended, and their conversation's ID and title. Everything it
   returns was written by the user or by Sibillo, so its result is trusted
   (TSK-013).

4. **Searching and reading the user's conversations.** `search_conversations`
   finds the user's conversations by words of their titles and messages, as
   the app's search does (CNV-009), with a short excerpt of each match.
   `read_conversation` reads one conversation's messages on its active path,
   bounded as tool results are (AGT-014): what the user and the assistant
   wrote, and the tools called, without their results. Neither reaches a
   temporary conversation (CNV-011), what a rewind removed (ADR-0068), or
   another user's data (TEN-007). Both are in a new tool group, so that the
   user can switch them off (AGT-032, AGT-033).

5. **Provenance follows what was read.** Reading a conversation, or finding
   it, is in the `reads_private_data` class, and not in
   `ingests_untrusted`. Its result is untrusted content only when the
   conversation it shows holds untrusted content on its active path, as a
   run counts it (AGT-003); the result says so, as loading an untrusted
   skill does. A press review, which read the web, makes the run that reads
   it untrusted; a task that read nothing from elsewhere does not.

## Consequences

- The user tries a task without waiting, and the assistant answers "how did
  it go?" by listing the task and reading its last conversation.
- Earlier conversations become context the assistant can use, which makes
  injected instructions able to travel between conversations. Provenance
  keeps them visible: a run that read untrusted content asks before it
  sends anything out (AGT-004).
- A task's own runs can be granted these tools like any other; the check of
  TSK-005 counts them as sources of private data, so a task with open web
  grants cannot read the user's conversations.
- The search is the app's, by words; a semantic search over past
  conversations is left for later.

## Alternatives considered

- **Making every read untrusted:** simpler, but it would make every
  conversation that recalls an earlier one ask before each search, for
  content the user wrote.
- **Giving the model the task's conversations in its instructions:** no
  tool to call, but every run would carry private data it does not need.
- **Only `list_tasks`, with the last answer inside:** enough for "how did it
  go?", but one more way of reading conversations, with provenance of its
  own, instead of one general way.
