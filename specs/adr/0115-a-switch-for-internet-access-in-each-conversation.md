# ADR-0115: A switch for internet access in each conversation

- **Status:** Accepted
- **Date:** 2026-11-23
- **Deciders:** @tapionx
- **Related:** ADR-0090, ADR-0111, ADR-0113, AGT-006, AGT-012, AGT-034, SBX-024, UX-039, UX-042

## Context

ADR-0113 made internet access one permission of a conversation, created
only by answering a request of the assistant. Using it showed what that
leaves out:

- **Nothing says whether a conversation has it.** The allowance is listed in
  the chat's settings, behind a dialog; an allowance for the turn is shown
  nowhere. A user cannot tell, before sending, whether the assistant will
  ask, nor see that a turn has the internet.
- **The user cannot give it first.** A user who knows the work needs the
  web, such as "look up today's train strikes", must send the message, wait
  for the request and answer it. Giving it up front avoids a request in
  hands-free mode, where answering one takes the user's eyes and hands.
- **The user cannot change their mind during a turn.** Withdrawing takes a
  dialog; giving it while the assistant works is not possible at all.

ADR-0113 rejected "a switch the user turns on before asking" as the standing
allowance that ADR-0090 rejected. That rejection was about an allowance
that outlasts a conversation, or that a setting gives to new ones: the
injected instructions of one conversation then reach the user's data in
another, without the user deciding anything about it. A switch of one
conversation, turned on by its user, is a decision of that user about that
conversation, as an answer to a request is.

## Decision

1. **A switch, always in view.** A conversation's top bar (UX-039) holds a
   switch for internet access, on every size of screen; the new-chat screen
   holds one too, whose position the conversation gets when it is created.
   The switch is on while the conversation has internet access, for the
   conversation or for the turn that is going on.

2. **What it shows.** Answering a request with "Allow in this chat" turns it
   on, and it stays on. Answering "Allow for this turn" turns it on until the
   turn ends: once the turn's last run has ended, it is off again.

3. **What turning it on does.** It gives the conversation internet access,
   as "Allow in this chat" does: an allowance of the conversation, shown
   with it, withdrawable, never copied into a fork, and never given to new
   conversations by any setting. While a request for internet access waits,
   turning the switch on answers it with "Allow in this chat", so that the
   waiting calls run.

4. **What turning it off does.** It withdraws internet access, for the
   conversation and for the turn: the sandbox loses its network at once
   (SBX-024), and the later calls of the turn that is going on need internet
   access again, which they ask for.

5. **During a turn.** A run reads the conversation's internet access again
   before each call that needs it, and the sandbox is given network before
   the next command once the switch is on. A change is therefore felt by the
   calls that follow it, without waiting for the next turn. The
   instructions the run started with are not changed; a model told that the
   conversation has none may still ask, and is answered at once.

6. **Permissions.** A user whose `external_communication` class is denied has
   no switch, and the API refuses to turn it on (ADR-0113 point 5). The
   new-chat screen's switch is sent with the request that creates the
   conversation.

This amends ADR-0113 point 4 and the alternative it rejected: internet
access is created by answering a request, or by its user turning on the
switch of that conversation.

## Consequences

- The user sees at a glance whether the assistant can reach the internet,
  and gives it or takes it away in one touch.
- More conversations will have internet access before any request, and
  therefore before untrusted content arrives, which ADR-0113 already
  accepted for "Allow in this chat"; the request no longer comes in front
  of the user to say what is at stake. The switch's label and tooltip say
  it instead.
- A run reads the allowance again before each call that needs it: one query
  more for each such call.
- Contracts to change: the conversation's allowances say whether the turn
  that is going on has internet access; a conversation may be created with
  internet access; and the allowance of the conversation may be turned on
  by its user, which also clears the turn's.

## Alternatives considered

- **Keep the allowance in the chat's settings only:** what ADR-0113 did;
  the state stays hidden, and the user can only withdraw it.
- **A default for new conversations:** the standing allowance that ADR-0090
  and ADR-0113 rejected; the switch of the new-chat screen gives it to one
  conversation, chosen each time.
- **A switch that gives access for the turn only:** a user who turns it on
  expects it to stay on; requests remain for the turn.
- **Disable the switch while a request waits:** two controls for one
  question would disagree; turning it on is an answer the user gave.
