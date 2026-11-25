# ADR-0143: A run's events wake the API by notification

- **Status:** Accepted
- **Date:** 2026-11-25
- **Deciders:** @tapionx
- **Related:** API-004, AGT-009, ADR-0141, ADR-0142

## Context

The API read a run's events with the durable execution engine's default,
polling once a second, so that a client received them in batches a second
apart (ADR-0141). Reading every 20 milliseconds (ADR-0141), then every 50
(ADR-0142), fixed the batches, but each open reader then queried the database
twenty times a second, and the readers of a stream that never closes, such as
that of a run whose worker was killed, kept doing so.

The engine can wake a reader by notification instead (`use_listen_notify`),
which its own migrations already support: no polling, and an event reaches
the client as soon as the worker writes it.

## Decision

The API's client of the durable execution engine uses notification
(`use_listen_notify=True`), and reads a run's events without a polling
interval of its own. ADR-0142's fifty milliseconds are replaced by this.

## Consequences

- A client sees an event within milliseconds, and an idle stream costs the
  database nothing.
- The API holds one more connection to the database, for the listener.
- A test that cancels a run after a session in which the worker was killed
  and restarted still sees the cancelled run end late (test_rewinding): the
  cause is not the readers' polling, and is open; the tests that kill the
  worker run in a part of their own until it is understood.
