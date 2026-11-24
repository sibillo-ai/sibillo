# ADR-0140: A run's steps in compact lines

- **Status:** Accepted
- **Date:** 2026-11-24
- **Deciders:** @tapionx
- **Related:** UX-003, UX-013, UX-023, UX-043, CNV-013, API-003, AGT-008, AGT-014, AGT-039, ADR-0085, ADR-0087, ADR-0090, ADR-0096, ADR-0111, ADR-0138

## Context

ADR-0085 shows an answer's parts where they happened: consecutive tool calls
form one block of steps, each piece of reasoning a fold of its own. Daily use
with models that search, browse and reason for many steps showed what this
costs:

- **Scrolling before the answer.** Each block is a bordered card with its
  own margin, and each step a line of at least 40 pixels with padding. A run
  of reasoning, a search, reasoning, a search… is a column of cards to
  scroll past before the answer starts, while the run works and after.
- **The label gives way to the arguments.** A step's verb and its first
  argument share one line, and both are truncated: a long argument, such as
  a script the browser runs, leaves "Ha …" of the verb.
- **What ran is not said.** The label is a description for people ("Ha
  cercato sul web"); the tool's own name, which the settings, the audit log
  and the model know it by (ADR-0087), is nowhere, nor how long the call
  took.
- **The browser is told wrongly.** The browser tools (ADR-0138) match the
  words that make a step "searched the web", and loading the browser, a
  deferred capability like a skill, shows as "using a skill browser",
  though no skill has that name.
- **An approval's outcome is a badge** ("Allowed in this chat") that takes
  the room of the label.

## Decision

1. **One block of steps.** Consecutive tool calls and pieces of reasoning
   form one block, in their order, between the answer's texts. A block has
   no margin of its own beyond the gap between it and the text; its steps
   are lines of one row each, 32 pixels high (44 where the pointer is
   coarse, for touch), with a hairline between them and no padding around
   them. Reasoning is a step like a call: "Reasoning" and its first words.
2. **The label is never cut.** A step's line holds its state (spinner or
   check, said to screen readers, ADR-0085), its label in full, then a
   preview of its arguments in what room is left, cut with an ellipsis, then
   the chevron that opens it. Where the label alone fills the line, the
   preview is left out; where the label is wider than the line, it wraps.
3. **The preview is the argument that says most.** Each tool names the one
   argument that tells the call apart: the query of `web_search`, the
   address of `read_page` and `browser_goto`, the host of an address where
   the whole address is long, the path of the file tools, a command's
   description and first line, the value typed by `browser_fill`, the
   selector of the other browser actions. A tool without one, such as a
   remote MCP server's, shows its first argument that is a string; a script,
   such as that of `browser_evaluate`, is never shown in the line.
4. **An approval's outcome is an icon** at the end of the line, with its
   words as its accessible name and tooltip, in the colour of its outcome
   (UX-023); the opened step says it in words.
5. **Opened, a step says everything.** Its tool's own name, in monospace and
   untranslated, such as `web_search`; its arguments; its result; how long
   it took; and how it was decided, when it needed approval.
6. **How long a call took** is measured by the worker around the tool's
   execution, kept with its result in the stored messages, and given by the
   history, on each `tool` message, as `duration_ms` (API-003). A call made
   before this change has none, and shows none. While a run streams, clients
   time the call from its start to its result.
7. **Long runs fold.** When an answer has ended, a block of more than three
   steps shows as one line: how many steps, and what they were, such as
   "12 steps · Searched the web ×3 · Used the browser ×8 · Reasoning", which
   opens to the steps. While the run works, a block shows its last three
   steps, under a line that says how many came before and opens them.
8. **The browser is told as itself.** Its tools are labelled by what they
   did in the browser: "Opened a page", "Read the page", "Clicked", "Typed",
   and "Used the browser" for the others. Loading the browser is the step
   "Opened the browser", not a skill (UX-028). The sprite shows them as
   searching (UX-013).
9. **Unchanged:** memory and skills keep their cards (UX-027, UX-028),
   offered files their place at the end, and a step's details their limits.
   This replaces ADR-0085 points 1 and 4: a command's description is its
   label, and its first line its preview, on the same line.

## Consequences

- A run of many steps takes one line once it has ended, and three while it
  works; each step is about half as high as before.
- What ran, by its real name, and how long it took, are one click away.
- Previews depend on a list of tools' arguments that the client keeps; a
  new tool shows its first string argument until it is added.
- Old answers show no durations.
- The tests of the web client that find steps by their old layout change.

## Alternatives considered

- **Only less padding:** halves the height, but a run of thirty steps is
  still thirty lines before the answer.
- **The technical name in the line, beside the label:** the line is short on
  a phone, and the name is for the user who looks closer, who opens the
  step.
- **Durations from the timestamps of the stored messages:** a tool call has
  none of its own; the model response's timestamp is when the model began
  answering, not when the call started.
