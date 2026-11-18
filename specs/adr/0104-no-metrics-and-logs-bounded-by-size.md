# ADR-0104: No metrics, and logs bounded by size

- **Status:** Proposed
- **Date:** 2026-11-18
- **Deciders:** @tapionx
- **Related:** ADR-0014, ADR-0054, ADR-0058, OBS-001, OBS-002, OBS-003, OBS-004, OBS-005, OPS-001, T-12

## Context

ADR-0014 planned metrics without content, instrumentation with
OpenTelemetry, and logs and traces deleted after a retention period chosen by
the instance admin. None of it exists: Sibillo collects no metrics and has no
traces, and its services write their logs to standard output, where Docker
keeps them.

Sibillo runs one household, and its instance admin installs it with
`docker compose up` and nothing else on the host (ADR-0054). Nobody reads
dashboards of request counts or durations there: metrics would be code,
dependencies and a scrape endpoint for no reader. OpenTelemetry would add a
collector or an exporter to configure, and a new way for data to leave.

Logs carry no content: message text, tool arguments and outputs, memory items
and credentials are never logged, and a security test checks it (OBS-003,
ADR-0058). Deleting them by age therefore protects nothing that matters, while
it would take them away from `docker compose logs`, the simplest place to read
them: Docker rotates logs by size only, so a retention period needs the logs
kept somewhere other than Docker. What remains is the disk: Docker's default
logging driver never deletes a line, and a service that logs for months fills
the host's disk.

## Decision

We will:

1. **Collect no metrics** (OBS-002). No component counts or times its work
   for a metrics endpoint or a metrics service, and nothing is instrumented
   with OpenTelemetry. Design tests reject packages and imports for metrics,
   OpenTelemetry instrumentation or its SDK. `opentelemetry-api`, which
   dependencies bring in, does nothing without an SDK and stays allowed, as
   ADR-0058 says.
2. **Keep logs in Docker, bounded by size** (OBS-005). Every service of the
   deployment either keeps no logs, as the search service (OBS-001), or uses
   Docker's `json-file` driver with `max-size: 10m` and `max-file: "3"`: at
   most 30 MB per service, the oldest lines dropped first. It is set in
   `deploy/compose.yaml`, once for all services, so nothing changes on the
   host, and `docker compose logs` keeps working. A design test checks every
   service of the compose file.
3. **Have no traces.** Without OpenTelemetry there is nothing to trace with.
   The debug mode of OBS-004 decides where its unredacted traces are kept, and
   for how long, when it is built.

This replaces points 2 and 5 of ADR-0014 and its use of OpenTelemetry; its
points 1, 3 and 4 stand.

## Consequences

- Fewer dependencies and no metrics endpoint to protect.
- Diagnosing a slow instance relies on logs and on the cost ledger, not on
  metrics; an instance admin who wants metrics reads Docker's own
  (`docker stats`).
- Logs stay readable with `docker compose logs` and can no longer fill the
  disk; on a busy instance they may cover only a few days, on a quiet one
  months. Since they carry no content, how long they last is not a privacy
  matter.
- A log line that would carry content is still caught by the test of OBS-003,
  not by deletion.

## Alternatives considered

- **Logs kept by Sibillo in daily files, deleted after a retention period:**
  matches the old OBS-005, but takes the logs away from `docker compose logs`
  and needs a wrapper around every process and Postgres's own log files.
- **Logs sent to the host's journald:** needs a change to the host, and only
  the host decides the retention.
- **Metrics without content, kept locally:** harmless, but nobody in a
  household would read them.
