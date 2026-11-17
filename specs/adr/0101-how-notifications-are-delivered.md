# ADR-0101: How notifications are delivered

- **Status:** Proposed
- **Date:** 2026-11-17
- **Deciders:** @tapionx
- **Related:** ADR-0039, ADR-0049, ADR-0052, ADR-0072, ADR-0083, ADR-0090, ADR-0094, UX-004, AGT-007, AGT-015, AUTH-004, T-23, T-39

## Context

ADR-0039 chose Web Push with content-free payloads, sent only when no client
of the user is following the run. It left open what makes that work in
Sibillo:

- Runs execute in the worker (ADR-0052), and clients follow them through the
  API's event stream. The worker cannot see which streams are open, and
  nothing records them.
- A question to the user ends a run with an interrupt, as an approval request
  does (AGT-015, ADR-0083), and the user must learn about both.
- Web Push needs a VAPID key pair (RFC 8292) and a contact, the `sub` claim,
  and works only for a page served from a secure origin.
- A subscription is a URL the browser chooses and the client sends; the
  server then sends requests to it. Accepted as is, it would let a user make
  the server call any address, including the instance's own services.

## Decision

1. **Kinds of notification.** At the end of a run, the worker sends one
   notification of the first kind that applies:
   - `approval_pending`: the run ended with an approval request (AGT-007);
   - `question_pending`: the run ended with a question to the user (AGT-015);
   - `run_failed`: the run failed;
   - `run_finished`: the run completed.

   A run the user stopped sends none. The payload is a JSON object with
   exactly `kind`, `conversation_id` and `run_id`.
2. **Following a run.** Each open event stream of a run, the one that starts
   it or one that reads it later, is a row of `run_followers`. The API adds
   the row when the stream opens, before the run is queued for the stream
   that starts it, refreshes its `seen_at` at least every 10 seconds, and
   deletes it when the stream closes, also when the client goes away. The
   run is followed while it has a row seen in the last 30 seconds, so that
   the rows of an API that stopped do not count for long. The worker decides
   whether to notify before it writes the run's final event, so that a client
   that reads the end of the run has not closed its stream yet.
3. **Subscriptions belong to a device session.** A device session has at most
   one notification subscription. Turning notifications on in a client saves
   the browser's subscription for the current session, and turning them off
   deletes it. A subscription is used only while its session is valid (not
   revoked, not expired, its user not disabled); the API deletes it when it
   revokes the session, and the worker deletes subscriptions of sessions that
   are no longer valid when it meets them. When a push service answers that a
   subscription is gone (`404` or `410`), the worker deletes it.
4. **Only push services, over HTTPS.** The API accepts a subscription only
   when its endpoint is an `https` URL without credentials or a port other
   than 443, on one of these hosts: `fcm.googleapis.com`,
   `updates.push.services.mozilla.com`, `web.push.apple.com`, or a host under
   `notify.windows.com`. Anything else is refused with
   `notification.endpoint_refused`. The worker checks the endpoint again
   before each send. Changing the list is a `spec/` change (ADR-0072).
5. **The VAPID key is derived from the instance's secret key.** The worker
   and the API derive the P-256 private key from `SIBILLO_SECRET_KEY` with
   HKDF-SHA-256 and a label of its own, so that operators configure nothing
   and backups already hold it. The `sub` claim is `SIBILLO_PUBLIC_ORIGIN`.
   When that origin is empty, notifications are unavailable: browsers allow
   them only on a secure origin, as passkeys need.
6. **Sending.** The worker sends from the run's end, after the run's status
   is stored, with the payload encrypted as RFC 8291 requires, a time to live
   of 24 hours (the life of an approval request, AGT-007), urgency `high` for
   `approval_pending` and `question_pending` and `normal` otherwise, and a
   timeout of 10 seconds per subscription. Sending is best effort: it is tried
   once per subscription, and a failure never changes the run.
7. **In the client.** The service worker shows a fixed text for each kind in
   the user's language, with the conversation as the notification's tag, so
   that a newer notification replaces an older one of the same conversation;
   tapping it opens the conversation, in an open window of the app when there
   is one. Notifications are off on every device until the user turns them on
   there, which asks the browser's permission and says that the push service
   learns when the instance notifies the device (ADR-0039).

## Consequences

- No new setting and no new secret: an instance with a public origin can
  notify as soon as it is upgraded. Changing `SIBILLO_SECRET_KEY` changes the
  VAPID key, and every subscription must be made again; this is already true
  of stored API keys.
- The API writes a row while a client follows a run, every 10 seconds per
  open stream.
- A user who follows a run on one device gets no notification on the others.
  When the API stops without closing its streams, runs it was streaming count
  as followed for up to 30 more seconds.
- The web client's service worker gains its own code for push and
  notification clicks, next to the cached app files (ADR-0067).
- A browser whose push service is not in the list cannot subscribe until the
  list changes.

## Alternatives considered

- **Track followers in memory in the API:** the worker sends the
  notifications and cannot see the API's memory; a row in the database is
  what both share.
- **One timestamp on the run, refreshed while it is followed:** a client that
  goes away would count as following for up to the timeout, and a run that
  ends soon after the user closes the app, the case notifications are for,
  would send nothing. A closing stream cannot clear it either, while another
  stream of the same run is open.
- **Always send, and let the service worker hide notifications while the
  conversation is visible:** simpler on the server, but the push service
  would learn about every run, and the user's other devices would ring while
  they watch the answer on one.
- **A VAPID key in its own variable, generated by `init`:** one more secret to
  keep and back up, for no gain over deriving it from the one that exists.
- **Any `https` endpoint, with the instance's addresses refused:** checking
  addresses is easy to get wrong (redirects, DNS rebinding, IPv6 forms); a
  list of hosts is not, and every browser in use has its push service in it.
