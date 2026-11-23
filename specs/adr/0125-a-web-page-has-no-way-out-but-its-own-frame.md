# ADR-0125: A web page has no way out but its own frame

- **Status:** Accepted
- **Date:** 2026-11-23
- **Deciders:** @tapionx
- **Related:** ADR-0086, ART-003, AGT-004, UX-020, T-08, T-22

## Context

ADR-0086 runs a web page the assistant made in a sandboxed frame, in an
opaque origin, under a policy without network. A security audit found ways
out that the policy does not close:

- **WebRTC** is not governed by `default-src`: a page can open a peer
  connection to a STUN server of the attacker and send data in it.
- **DNS prefetching** of a `<link rel="dns-prefetch">` sends a name to the
  resolver, which the attacker's name server sees.
- **The page as a document of its own.** The file endpoint serves a page to
  any request with `page=true`. A link in an answer to that address opens
  it at the top level, where it is no longer framed and can navigate the tab
  anywhere with what it holds.
- **Forms and base addresses** are not named by the policy.

The threat model says that the lethal trifecta mitigation bounds what
injected content can make the assistant write into a page. It does not:
writing a file never asks (ADR-0090).

## Decision

1. **The page's policy names every way out it can.** Beside `default-src
   'none'`: `form-action 'none'`, `base-uri 'none'`, `frame-src 'none'`,
   `webrtc 'block'`, and the header `X-DNS-Prefetch-Control: off`.
2. **A page runs only in a frame.** The file endpoint serves `page=true`
   only to a request whose `Sec-Fetch-Dest` is `iframe`; any other is
   refused with `file.not_previewable`, so a link cannot open it at the top
   level. The app's own policy says `frame-src 'self'`.
3. **A PDF's policy drops `plugin-types`,** which browsers removed. A PDF
   stays unsandboxed, since the browser's viewer does not open in a
   sandboxed document; it runs nothing of the app.
4. **The residual risk is stated as it is.** A page can still navigate its
   own frame, carrying what it holds, and browsers that do not implement
   `webrtc 'block'` let it open a peer connection. What a page holds is what
   the assistant wrote into it, which a run with untrusted content can
   choose: writing files never asks.

This amends ADR-0086 point 3.

## Consequences

- A page opened from a link shows the refusal instead of running.
- Firefox and Safari, which ignore `webrtc`, leave WebRTC open; the threat
  model says so.

## Alternatives considered

- **Removing WebRTC from the page with a script the server prepends:** a
  page can make a frame of its own with a fresh window.
- **Asking before `offer_download` of an HTML file in a run with untrusted
  content:** the file is in the workspace and the Files panel opens it
  without any offer; it would ask without closing anything.
- **A separate domain for pages:** the strongest isolation, but every
  instance would need a second name and certificate.
