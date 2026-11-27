# ADR-0146: A run does not wait for its title

- **Status:** Accepted
- **Date:** 2026-11-28
- **Deciders:** @tapionx
- **Related:** CNV-006, API-008, UX-022, UX-032, UX-042, ADR-0073, ADR-0083, ADR-0108

## Context

ADR-0073 asks the conversation's model for a title alongside the first
answer, and says that the run finishes only after its title request did.
The title is a request to the same model, and it can take longer than the
answer: a reasoning model may think about it for many seconds. A first run
that ends to ask the user, for internet access or another approval
(UX-022, UX-042), then holds its request back until the title arrives: in
use, a model asked for internet access after 2.6 seconds, and the request
reached the user after 17.5, when the title request ended.

The title is a courtesy (ADR-0073): nothing the user waits for should
depend on it.

## Decision

This replaces the sentence of ADR-0073 point 2 that makes the run wait.

1. **The run ends without its title.** The title is still asked for when
   the first run of an untitled conversation starts, alongside the answer.
   A run that has its answer, or a request for the user, ends then, whether
   or not its title request did. The title request goes on after the run;
   it is stored unless the user named the conversation meanwhile, recorded
   in the cost ledger with the purpose `title`, and a failed request leaves
   the conversation untitled, as before.
2. **A title stored is a change of the user.** The worker announces it on
   the stream of the user's changes (ADR-0108) with an event named
   `conversation_titled` and the conversation's ID, in the transaction that
   stores it. Clients read the conversation again.
3. **The run's stream still names it when it can.** A title that arrives
   while the run goes on is also announced on the run's stream with the
   `CUSTOM` event `sibillo.title`, as ADR-0073 says; one that arrives later
   is announced on the stream of changes only.
4. **Not durable after the run.** The title request remains a step of the
   run's workflow. If the worker stops after the run ended and before the
   title arrived, the conversation stays untitled, as when the request
   fails; the next run does not ask again.

## Consequences

- A first run ends as soon as its answer or its question does: approval
  requests, questions and the end of the answer no longer wait for a
  helper request.
- Clients that show titles follow the stream of changes; a client without
  it sees the title the next time it reads the conversation.
- The stream of changes has one more kind of event, with identifiers only.

## Alternatives considered

- **Wait for the title, with a time limit:** shortens the wait but keeps
  one, and a slow title is then lost even though the model would have
  answered.
- **Ask for the title after the answer:** the conversation would stay
  untitled while it is answered, which ADR-0073 wanted to avoid.
- **A workflow of its own for the title:** durable, but one more workflow
  for each new conversation, for something whose loss costs nothing.
