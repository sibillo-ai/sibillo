# ADR-0116: An untrusted skill makes every run it reaches untrusted

- **Status:** Accepted
- **Date:** 2026-11-23
- **Deciders:** @tapionx
- **Related:** ADR-0090, ADR-0095, ADR-0096, ADR-0113, AGT-003, AGT-004, AGT-025, AGT-034, MEM-008, T-25, T-36

## Context

ADR-0096 point 7 offers untrusted skills to every run by name and
description, marked as from an untrusted source, and makes a run untrusted
only when it loads one. Descriptions were judged short enough not to matter,
and the alternative, a run untrusted from its start, was set aside because a
user with one imported skill would be asked to approve the first search of
every conversation.

Both reasons have gone:

- **A description is enough.** A description holds up to 1,024 characters,
  written by whoever wrote the skill, and it reaches the model's context in
  every run where the skill is on, whether or not the skill is loaded. That
  is room for injected instructions. The mark that says it comes from an
  untrusted source is a word in the prompt, and the threat model never
  relies on prompts as a security boundary. A skill the assistant saved
  after reading a web page (T-36) reaches every later conversation the same
  way.
- **The cost is gone.** Since ADR-0113, the web tools and the sandbox's
  network follow internet access, asked once in a conversation whether or
  not the run has untrusted content. Untrusted content now asks only before
  the other tools of the `external_communication` class, such as those of
  remote MCP servers (AGT-004), and it is said in the request for internet
  access. A run untrusted from its start no longer asks before its first
  search.

Untrusted memory items already make a run untrusted from its start
(MEM-008, ADR-0095).

## Decision

1. **A run offered an untrusted skill has untrusted content from its
   start** (AGT-003, AGT-004): a run whose skills, those on for its user and
   not off in its conversation, include an untrusted one counts as having
   untrusted content before its first step, as a run given an untrusted
   memory item does. A request for internet access in that run says so, and
   every other tool of the `external_communication` class asks, unless an
   allowance or a task grant covers it.
2. **Loading still marks.** Loading an untrusted skill still marks its
   result, so that the history of the conversation keeps holding untrusted
   content after the skill is marked trusted or turned off; a trusted skill
   offered or loaded does neither.
3. **The rest of ADR-0096 point 7 holds:** provenance, how a skill becomes
   trusted, the mark in the catalog, and scripts only in the sandbox.

This amends ADR-0096 point 7 and the alternative it rejected.

## Consequences

- A description of an untrusted skill can no longer steer a run toward
  sending data out without the user seeing that the run holds content from
  elsewhere.
- A user with an untrusted skill on sees every request for internet access
  say that the conversation holds content from elsewhere, and approves each
  call of a remote MCP server that communicates externally, until they read
  the skill's files and mark it trusted, or turn it off. The Skills page
  says so where it offers to mark a skill trusted.
- A conversation that turns an untrusted skill off is trusted again from its
  next run, unless its history holds untrusted content.
- Task grants are checked when a task is saved (TSK-005), and a skill can be
  imported later: an open grant still lets a task run with an untrusted
  skill call a tool that communicates externally, as it does with untrusted
  memory items. That is a residual risk of open grants, not of skills.

## Alternatives considered

- **Offering untrusted skills by name only, with a neutral description the
  server writes,** until the user marks them trusted: the description is
  how the model knows when to use a skill, so an untrusted skill would
  rarely be used, and its name, up to 64 characters, still reaches every
  run.
- **Keeping descriptions out of untrusted runs' instructions and letting the
  model list skills with a tool:** a call per run for every user with
  skills, and the description still arrives before anything is loaded.
- **Leaving it as it is:** the only protection is a word in the prompt.
