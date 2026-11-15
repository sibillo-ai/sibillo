# ADR-0095: Memory items, kept by the assistant through tools

- **Status:** Proposed
- **Date:** 2026-11-15
- **Deciders:** @tapionx
- **Related:** ADR-0012, ADR-0013, ADR-0031, ADR-0068, ADR-0077, ADR-0081, ADR-0082, ADR-0087, ADR-0090, ADR-0091, AGT-002, AGT-003, AGT-004, AGT-005, CNV-011, CNV-013, CNV-014, MEM-001, MEM-002, MEM-003, MEM-004, MEM-005, MEM-006, MEM-007, MEM-008, OPS-006, UX-027

## Context

ADR-0013 made memory visible, editable, really deletable, private and
optional, but left open what a memory item is, how the assistant writes and
reads it, and how it fits the rest of the agent: provenance and the trifecta
rule (ADR-0090), the instructions of a run (ADR-0081), tool switches
(ADR-0087), temporary conversations (ADR-0082) and backups (ADR-0077).

Three forces shape it:

- **What the user sees must be what the assistant gets.** Embeddings, a
  search index or a summary written by a model would each be a second copy,
  harder to show and to delete (MEM-003).
- **Memory carries content across conversations.** Text the assistant
  writes in a run that read a web page may come from that page: injected
  instructions stored in memory would reach every later conversation, as
  trusted instructions, unless memory keeps its provenance (T-35).
- **Small local models have small context windows.** Memory goes into
  every run, so it must stay short.

## Decision

1. **A memory item is a short text.** Each user has a list of memory items,
   each at most 500 characters, at most 10,000 characters in all. There are
   no embeddings, indexes, caches or summaries of them: the rows the user
   sees are the only copy, and they are what the assistant is given.
2. **The assistant is given every item.** When a run starts, the worker
   reads the user's items and puts them in the run's instructions after the
   working instructions and the voice instructions, before the additional
   instructions, each with its ID. The items are read for each run, never
   copied into a workflow's input, and stored model requests keep no
   instructions, so that an item changed or deleted applies from the next
   run and leaves no copy in a conversation (MEM-002, MEM-003). The memory
   section tells the assistant that the items are what it remembers about
   the user from earlier conversations.
3. **The assistant keeps memory through three tools** (MEM-007):
   `remember`, which adds an item; `update_memory`, which replaces the text
   of an item by its ID; and `forget`, which deletes an item by its ID. Their
   calls and results show in the conversation like any tool call. The
   working instructions of memory, given while any of the three is on, tell
   the assistant to remember lasting facts and preferences the user would
   want carried into other conversations, not details of one task; to
   remember, change or forget an item when the user asks; never to remember
   passwords, keys or other secrets; and to keep each item to one fact.
4. **Their declaration** (AGT-005): no capability classes, allowed by
   default. They change only the user's own memory, which the user sees,
   corrects and deletes; what they write is guarded by provenance
   (point 5), not by approvals. Tool permissions reach them as any tool
   (AGT-002), and clients list them in a group of their own, Memory, with a
   switch per tool, as ADR-0087 does for the others (CNV-013).
5. **Provenance** (MEM-005, MEM-008). Each item records its origin: `user`
   when the user wrote it, or last saved it, in the settings; `assistant`
   when a memory tool did, with the conversation and the time. An item the
   assistant writes or updates in a run that has untrusted content when it
   calls the tool (AGT-003) is **untrusted**; otherwise it is trusted. Saving an item in the
   settings, changed or not, makes it the user's, and trusted: it is how a
   user confirms one. Untrusted items are given to the model marked as
   information from untrusted sources, not instructions, and a run given any
   untrusted item has untrusted content from its start, so the trifecta rule
   applies to it (AGT-004). Clients show which items are untrusted.
6. **Memory is on unless the user turns it off** (MEM-006). It is a setting
   of each user, on by default. While it is off, runs are given no items and
   no memory tools; the items stay, and the user still sees, edits and
   deletes them in the settings. A temporary conversation is always as if
   memory were off (CNV-011, ADR-0082).
7. **Deletion is physical** (MEM-003). Deleting an item deletes its row;
   the user can also delete every item at once. Nothing else in the
   database holds it (point 1 and point 2). Three places are outside
   memory and say so in the documentation: the conversation where a memory
   tool wrote the item keeps that call, as it keeps the rest of what was
   said, until the user deletes or rewinds it; backup archives keep it until
   they are rotated (OPS-006); and a remote model's provider handles what it
   was sent under its own terms, which the data egress policy governs
   (MOD-003).
8. **Items outlive their conversation.** Deleting, rewinding or forking a
   conversation does not change memory (ADR-0068): the user manages items
   on their own. An item keeps the ID of the conversation it came from as an
   identifier, without a reference, and the API gives the conversation's
   title while it exists, and says it was deleted otherwise.
9. **Limits are told, not enforced by truncation.** `remember` and
   `update_memory` fail when an item would be over 500 characters, or memory
   over 10,000, saying so, so that the assistant can merge or forget items,
   or tell the user. The API refuses the same with `422`.
10. **Memory is private** (MEM-004). `memory_items` is a private table, under
    the same row-level security policy as the others. Memory of a shared
    space comes with shared spaces (TEN-007).
11. **API.** `GET /me/memory` gives the setting, the items with their
    provenance, and how much of the limit is used; `PUT /me/memory` turns it
    on or off; `POST /me/memory/items` adds an item; `PATCH` and `DELETE` on
    `/me/memory/items/{id}` change and delete one; `DELETE /me/memory/items`
    deletes all.
12. **Clients** (UX-027) have a Memory page in the settings: the switch, the
    items newest first with where each came from, untrusted ones marked, and
    adding, editing, deleting one and deleting all, the last after asking.
    In a conversation, a call to a memory tool shows what was remembered,
    changed or forgotten, and leads to the Memory page.

## Consequences

- What the assistant remembers is plain text the user can read in one page,
  and deleting it is deleting a row.
- Memory costs context in every run, up to about 2,500 tokens; the limit
  keeps it usable with small local models.
- Without retrieval, memory does not scale to thousands of facts. That is a
  choice for now: a later ADR may add search over past conversations, as a
  tool whose results are the conversations themselves, not a second copy.
- Untrusted items make runs untrusted from the start, so a user whose memory
  holds one may be asked to approve a search they would not otherwise have
  been asked about, until they confirm the item.
- Stored model requests losing their instructions changes nothing that
  reads them today: each run is given the instructions that apply when it
  starts (ADR-0081).
- `ToolName`, the tool switches and the tool declarations grow by three
  tools.

## Alternatives considered

- **Extracting memory after each conversation, in the background:** less
  for the assistant to decide, but it writes without the user seeing it
  happen, costs a model call per conversation, and still needs provenance.
- **Embeddings and retrieval:** scales further, but adds derived copies to
  delete and makes what the assistant was given harder to show.
- **One free text the assistant rewrites:** simple, but every change risks
  losing other facts, and provenance cannot be kept per fact.
- **Approving every memory write:** safe, but prompts on ordinary turns;
  provenance with the trifecta rule keeps the same guarantee quietly.
- **Treating every item the assistant writes as untrusted:** would make
  almost every run untrusted from its start, and the trifecta rule would ask
  on the first search of every conversation.
