# OBS — Observability and privacy

What the system records about its own behavior, and what it never records.
Background: ADR-0014, ADR-0058, ADR-0072, ADR-0104.

## OBS-001: Nothing sent to external services by default

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

The system MUST NOT send telemetry, analytics, crash reports, logs or traces
to any external service unless the instance admin explicitly configures it.

## OBS-002: No metrics

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** design

The system MUST NOT collect metrics, and MUST NOT instrument its components
with OpenTelemetry (ADR-0104).

Rationale: metrics that nobody in a household reads are only code,
dependencies and one more way for data to leave.

## OBS-003: Content redacted in logs and traces

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** unit

Logs and traces MUST redact message text, tool arguments and outputs, memory
items and credentials by default.

## OBS-004: Per-user debug mode

- **Status:** draft
- **Priority:** SHOULD
- **Phase:** 3
- **Verification:** integration

A user SHOULD be able to enable, for themselves only, a debug mode that
records unredacted traces locally. It SHOULD be visibly indicated and turn
itself off automatically after at most 24 hours.

## OBS-005: Logs bounded by size

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** design

The logs of every service of the deployment MUST stay within a bounded size,
the oldest lines dropped first, without any change to the host; they MUST
stay readable with `docker compose logs` (ADR-0104).

Rationale: logs carry no content (OBS-003), so how long they last is not a
privacy matter; a disk filled by logs stops the whole instance.

## OBS-006: Outbound requests only to declared destinations

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** security, design

The control plane MUST connect to external services only for the declared
destinations of ADR-0072, each only for its purpose, and no library may
download data at run time. The web client MUST load every script, style,
font, icon and image from the instance itself, never from a CDN or another
third party.

Rationale: what leaves the household must be what its users and admins chose
to send, and a short list they can check.
