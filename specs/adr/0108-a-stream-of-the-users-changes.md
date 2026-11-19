# ADR-0108: A stream of the user's changes

- **Status:** Proposed
- **Date:** 2026-11-19
- **Deciders:** @tapionx
- **Related:** API-008, UX-032, UX-004, ADR-0032, ADR-0034, ADR-0101, ADR-0106

## Context

Until tasks, every conversation started in the client that showed it, so
the app knew when to refresh its list. A task starts a conversation in the
worker (ADR-0106): the app shows it only when it next reloads its list, and
nothing says that the task is running. Polling would show it late, or cost a
request every few seconds from every open client.

The API already streams a run's events with Server-Sent Events (ADR-0032).
What the app needs now flows one way too, from the server to the client.

## Decision

1. **One stream per client.** `GET /me/events` is a Server-Sent Events stream
   of what changes for the user, as long as the client keeps it open. Each
   event says what changed and its identifiers, never content:
   `conversation_created`, `run_started` and `run_finished` with the
   conversation's and the run's IDs, and `task_fired` with the task's ID.
   A client refreshes what the event names. Heartbeats keep the connection
   open through proxies.
2. **Postgres carries the events.** The worker and the API publish each
   change with `pg_notify` on the channel `sibillo_changes`, in the
   transaction that makes it, with the tenant's and the user's IDs and the
   event. Each API process listens on one connection and forwards an event
   only to the streams of that user. Nothing is kept: a client that
   reconnects reloads its lists, and events missed meanwhile need no replay.
3. **No WebSocket.** The stream is one-way, as SSE is; it passes the same
   proxies and authentication as the run streams.

## Consequences

- A conversation a task starts appears at once in every open client, marked
  as running until its first run ends (UX-032).
- Each open client holds one more connection; each API process holds one
  database connection for listening.
- `NOTIFY` payloads are visible to any session of `sibillo_app` that listens
  on the channel; they carry only identifiers, and only the API listens.

## Alternatives considered

- **Polling:** no new mechanism, but late by its interval, and a request
  from every client all the time.
- **WebSocket:** two-way, which nothing needs, and a second kind of
  connection for proxies and authentication.
- **Reading DBOS's streams:** they are per workflow, not per user, and hold
  run content without row-level security (TEN-009).
