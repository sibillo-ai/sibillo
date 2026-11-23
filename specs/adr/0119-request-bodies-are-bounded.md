# ADR-0119: Request bodies are bounded, 1 MiB unless an operation takes files

- **Status:** Accepted
- **Date:** 2026-11-23
- **Deciders:** @tapionx
- **Related:** ADR-0050, ADR-0079, ADR-0096, API-006, API-009, SBX-019, TSK-007, T-14, T-15

## Context

Nothing bounds the size of a request body. FastAPI reads and parses a JSON
body before it checks the session that sent it, so anyone who reaches the
API can make it hold as much memory as they send, and some fields, such as
the WebAuthn objects of a sign-in, are free-form JSON of any size. Only a few
operations bound what they read: webhooks (64 KiB), MCP event deliveries
(256 KiB), recordings (25 MiB), skills and workspace uploads, each in its
own way, and after the body has started to arrive.

The largest JSON body an operation needs today is a skill's text file, up to
1,048,576 characters, which JSON escaping can make a few times larger. Every
other JSON body is a few kilobytes.

## Decision

1. **One limit for every body: 1 MiB.** A middleware in front of every
   route refuses a body over its limit with `413 request.too_large`. A
   declared `Content-Length` over the limit is refused before anything is
   read; a body without one, or longer than it said, is counted as it
   arrives and refused once it passes the limit. This happens before the
   route runs, so before any authentication.
2. **Larger limits, stated by the operations that take files:**

   | Operation | Limit |
   |---|---|
   | `POST /speech/transcriptions` | 26 MiB: a 25 MiB recording and its form |
   | `POST /me/skills` | 21 MiB: an archive of a skill and its form, as read now |
   | `PUT /me/skills/{id}/file` | 7 MiB: 1 MiB of text, escaped |
   | `PUT /conversations/{id}/workspace/file`, `POST /conversations/{id}/workspace/uploads` | the instance's upload limit (`SIBILLO_UPLOAD_MAX_MB`) |

   An operation's own, smaller limits still apply, with their own error
   codes.
3. **The driver's API is left as it is:** only the control plane reaches it,
   with its token (ADR-0062), and every body it receives comes from the
   control plane, within these limits.

## Consequences

- An unauthenticated client can make the API hold at most 1 MiB per
  request; larger bodies are reserved for routes whose callers are signed
  in, and are refused by length before they are read where they declare
  it.
- A client that sends a larger JSON body than any operation needs gets
  `413` instead of a validation error.
- A new operation that takes files must state its limit here, or it gets
  1 MiB.

## Alternatives considered

- **A limit in the reverse proxy:** not every deployment has one that we
  configure, and the proxy does not know which routes take files.
- **Uvicorn's own limits:** it bounds headers, not bodies.
- **Pydantic limits on every field:** needed anyway for meaning, but the
  body is read and parsed in full before they run.
