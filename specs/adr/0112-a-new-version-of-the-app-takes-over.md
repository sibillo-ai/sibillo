# ADR-0112: A new version of the app takes over

- **Status:** Proposed
- **Date:** 2026-11-20
- **Deciders:** @tapionx
- **Related:** UX-040, UX-001, UX-004, UX-006, ADR-0067, ADR-0101, ADR-0102

## Context

The web client is an installable app with a service worker that keeps the
app's own files on the device (UX-001, ADR-0067). The page is served from
that copy, so the app opens without the network and opens fast.

The browser looks for a new service worker only when a page of the app is
loaded. An installed app on a phone is rarely loaded again: it is brought
back from the background, where it may stay for days. After a new version
is deployed the phone keeps showing the old one, and even when the browser
does find the new worker, which takes over at once, the page already open
keeps running the old code until it is loaded again. The maintainer saw the
old screens on their phone after every deployment of the last few days.

The server already sends the page and the service worker with `no-cache`
and only files with a content hash in their names as immutable. One file
without a hash, the script that registers the worker, was sent as immutable
too, and so were the icons.

## Decision

1. **The app looks for a new version.** Besides the browser's own check, the
   app asks for one whenever it comes back into view, when it goes out of
   view, and every hour while it stays open. The browser fetches the service
   worker past its HTTP cache for this check.
2. **The new worker takes over at once**, as it already does: it skips
   waiting and takes control of the open pages, and it drops the files of
   the old version.
3. **The page follows it.** When a new worker takes control of a page that
   already had one, the page loads itself again, so that its code is the new
   version's, as soon as that loses nothing: while the app is out of view
   and no field holds text the user typed. Until then it shows a notice that
   a new version is ready, which stays until the user loads it with the
   notice's button or closes it, and the page loads itself the next time
   the app goes out of view with nothing typed. The first worker of a page,
   on its first visit, changes nothing.
4. **Only hashed files are kept for long.** The server sends as immutable
   only the files under `/assets/`, whose names carry a hash of their
   content; every other file of the app, the page, the service worker, the
   script that registers it, the manifest and the icons, is sent with
   `no-cache`.

## Consequences

- A deployment reaches an installed app the next time it is opened, or
  within an hour while it stays open, without clearing anything.
- A reload while the user is not looking costs nothing that was typed; a
  run in progress goes on on the server and the conversation shows it again
  when it loads.
- What a user typed in a field and the app does not keep, such as a draft in
  the message box, still decides when the page reloads: never under it.
- A proxy in front of the instance, such as a CDN, may keep files longer
  than the server says; the check of point 1 does not depend on it, but an
  operator who caches the page itself must not.

## Alternatives considered

- **Reloading at once, wherever the user is:** simplest, and it would throw
  away a message being written.
- **Only a notice, and the user reloads:** the old version would stay for as
  long as the notice is ignored, which on a phone is most of the time.
- **No service worker cache for the page:** the app would no longer open
  without the network, and the share target and the notifications need the
  worker anyway (ADR-0101, ADR-0102).
- **A version endpoint the app polls:** a second way to say what the service
  worker update already says.
