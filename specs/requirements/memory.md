# MEM — Memory

What the assistant remembers across conversations, and the user's control
over it. Background: ADR-0013, ADR-0095.

## MEM-001: Memory is visible

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e

A user MUST be able to list and read every memory item the assistant holds
about them. What the user sees MUST be all that the assistant is given of
their memory: there MUST be no summary, embedding or other form of it that
the user cannot see (ADR-0095).

## MEM-002: Memory is editable

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e

A user MUST be able to add memory items and edit any of their memory items,
and the assistant MUST use the edited version from the next run on
(ADR-0095).

## MEM-003: Memory deletion is real

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

Deleting a memory item MUST remove it and every derived copy (embeddings,
search indexes, caches) so that it can no longer influence the assistant.
A user MUST be able to delete all their memory items at once. Runs MUST NOT
keep copies of memory items in their durable inputs or in stored messages
(ADR-0095).

## MEM-004: Memory is private

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** security

Memory items MUST be private to their user. A memory item MUST exist in a
shared space only when it is explicitly created there.

## MEM-005: Memory provenance

- **Status:** implemented
- **Priority:** SHOULD
- **Phase:** 1
- **Verification:** integration

Each memory item SHOULD record when and from which conversation it was
created, whether the user or the assistant wrote it last, and whether it is
untrusted (MEM-008), and show this to the user (ADR-0095).

## MEM-006: Memory can be disabled

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

A user MUST be able to turn memory off; while it is off, no memory items
are created or used for that user. Memory MUST be on until the user turns it
off, and existing items MUST stay visible, editable and deletable while it
is off (ADR-0095).

## MEM-007: The assistant keeps memory through tools

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

While memory is on, every run of a conversation that is not temporary MUST
be given all the user's memory items, and the assistant MUST be able to add,
change and delete them only through mediated tools, `remember`,
`update_memory` and `forget`, whose calls show in the conversation. A memory
item MUST hold at most 500 characters, and a user's memory at most 10,000;
a tool call or a request over a limit MUST fail and say so, without
truncating (ADR-0095).

## MEM-008: Memory written from untrusted content

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration, security

A memory item that the assistant writes or changes in a run that has
untrusted content when it calls the tool (AGT-003) MUST be untrusted; a
memory item the user writes or saves MUST be trusted. Untrusted memory items
MUST be given to the model labeled as untrusted content, and a run given any
untrusted memory item MUST count as having untrusted content from its start
(AGT-004, ADR-0095). In a run with untrusted content, changing or deleting
an item the user wrote MUST ask for approval (ADR-0127).

Rationale: threat T-35.
