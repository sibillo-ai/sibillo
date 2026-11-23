# API — Public API and conversations

The interface every client uses. Background: ADR-0016, ADR-0008.

## API-001: One public API for all clients

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** design

Every first-party client MUST use only the public HTTP API. The server MUST
NOT expose client-specific private endpoints.

## API-002: Committed OpenAPI contract

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

The public API MUST be described by an OpenAPI document committed in
`specs/contracts/`. CI MUST fail when the server serves an operation the
contract does not describe or lacks one it describes, or when a request the
server accepts or a response it sends during the test suite does not match
the contract (ADR-0056).

## API-003: Separate conversations

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** e2e

A user MUST be able to create, list, open, rename, archive and delete
conversations. Each conversation MUST have its own history; content MUST NOT
flow between conversations except through memory items (MEM-004).

## API-004: Streaming responses

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

Assistant responses, including tool activity, MUST be streamed to clients
with Server-Sent Events carrying AG-UI 1.0 events, each with a sequence
number. A client that reconnects MUST be able to resume receiving the events
after the last sequence number it received, while the run is in progress or
after it has finished (ADR-0032).

## API-005: Compatibility and deprecation

- **Status:** draft
- **Priority:** SHOULD
- **Phase:** 4
- **Verification:** review

Breaking changes to the public API SHOULD be introduced only with a new
version, migration notes and a deprecation period for the previous behavior.

## API-006: Voice input and output

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

The API MUST transcribe a recorded spoken turn into text (speech-to-text) and
synthesize text as audio (text-to-speech), for voice turns (UX-005). Speech
models MUST come from the household's connections, like its chat models: a
connection lists which of its models transcribe and which speak, with their
voices, and tenant admins choose the household's transcription model and
speech model with its voice (ADR-0088). Each connection states whether it runs
locally or remotely (MOD-010), and remote speech is subject to the data egress
policy (MOD-003). Requests to speech models MUST carry the connection's
credentials from the control plane only, and their cost, as the provider
reports it with the answer or, failing that, after the request, MUST be
recorded in the cost ledger with the purpose `speech` (MOD-006). A run MUST
carry whether its message was dictated or spoken in hands-free mode, and the
assistant's instructions for that run MUST say so (ADR-0088).
A failed speech request MUST say why, such as a speech model that took too
long to answer. Recordings MUST NOT be kept after transcription.

## API-007: Stable error codes

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** design

Every error response of the public API MUST carry a stable, machine-readable
error code documented in the API contract, so that clients can present errors
in the user's language.

## API-008: A stream of the user's changes

- **Status:** implemented
- **Priority:** SHOULD
- **Phase:** 2
- **Verification:** integration

The API SHOULD offer each signed-in client a Server-Sent Events stream of
what changes for its user: a conversation created, a run started or
finished, and a task fired, each with its identifiers and nothing of its
content. A change MUST reach the streams of its user within a second of its
transaction, and MUST NOT reach any other user's (ADR-0108).

## API-009: Bounded request bodies

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 2
- **Verification:** security

The API MUST refuse a request body larger than 1 MiB with `413` and
`request.too_large`, before it reads more of it than that, and before any
authentication, unless the operation states a larger limit for the files it
takes: a recording to transcribe, a skill's archive or one of its files, and
a file uploaded to a workspace, whose limit is the instance's upload limit.
A body without a declared length MUST be counted as it arrives (ADR-0119).

Rationale: threats T-14 and T-15; a body is read before the session that
sends it is checked.
