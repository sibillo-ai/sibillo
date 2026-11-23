# ADR-0124: The approval of `save_skill` shows the skill it saves

- **Status:** Accepted
- **Date:** 2026-11-23
- **Deciders:** @tapionx
- **Related:** ADR-0090, ADR-0096, ADR-0116, AGT-007, AGT-012, AGT-025, AGT-026, T-36

## Context

ADR-0096 point 5 says that the approval of `save_skill` shows the user the
skill's name and description before it reaches later conversations. The
request shows only the folder's path: the folder is read after the
approval. A process of the sandbox can change the folder between the two,
and the user cannot see that the save replaces one of their skills.

Replacing a skill also writes its provenance anew, so an untrusted skill
replaced from a run without untrusted content becomes trusted, although
AGT-025 says that only the user marks a skill trusted.

## Decision

1. **The folder is read when the approval is asked.** Before raising the
   request, the control plane reads and checks the folder as the save
   would, and the request shows the skill's name and description, its
   files, and whether it replaces one of the user's skills. A folder that
   is not a valid skill asks nothing: the call fails with the reason, as an
   unapproved save would.
2. **The skill saved is the skill approved.** The request keeps a digest of
   the folder's files, paths, contents and whether each is executable. The
   approved call reads the folder again and saves nothing when the digest
   differs; the model is told that the folder changed after the approval.
3. **A replaced skill keeps its distrust.** Replacing an untrusted skill
   leaves it untrusted, whatever the run that replaces it; a trusted skill
   replaced from a run with untrusted content becomes untrusted, as before.
   Only the user marks a skill trusted (AGT-025).

This amends ADR-0096 points 5 and 7.

## Consequences

- The user approves a skill they have seen, and nothing else is saved.
- An approval of `save_skill` reads the sandbox twice: once to ask, once to
  save.

## Alternatives considered

- **Copying the folder into the control plane when asking, and saving the
  copy:** nothing to compare, but a copy of up to 10 MiB held in the
  approval request for as long as the user takes to answer.
