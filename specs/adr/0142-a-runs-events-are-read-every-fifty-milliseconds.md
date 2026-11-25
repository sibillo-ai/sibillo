# ADR-0142: A run's events are read every fifty milliseconds

- **Status:** Superseded by ADR-0143
- **Date:** 2026-11-25
- **Deciders:** @tapionx
- **Related:** API-004, AGT-009, ADR-0141

## Context

ADR-0141 (point 1) has the API read a run's events every 20 milliseconds,
where the engine's default is a second. At 20 milliseconds, the test of a
rewind after a cancelled run (ADR-0132) failed in the real processes: the
cancelled run's workflow did not end within 30 seconds, so its row kept no
`finished_at` and the rewind answered `run.in_progress`. At 50 and at 100
milliseconds it ended in seconds, as with the default. Why the faster reading
keeps a cancelled workflow from ending is not known.

## Decision

The API reads a run's events every 50 milliseconds (`STREAM_POLL_SECONDS`):
a client sees an event within a twentieth of a second of the worker writing
it, and a run's reading is no heavier than the engine tolerates. ADR-0141's
twenty milliseconds are replaced by this value; the rest of that ADR stands.

## Consequences

- The cause of the stalled cancellation at 20 milliseconds is a question to
  look into with the engine's maintainers before the interval goes lower.
