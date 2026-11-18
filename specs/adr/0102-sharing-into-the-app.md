# ADR-0102: Sharing into the app

- **Status:** Proposed
- **Date:** 2026-11-18
- **Deciders:** @tapionx
- **Related:** ADR-0067, ADR-0079, ADR-0090, UX-006, UX-014, CNV-017, AGT-003, T-40

## Context

On a phone, the way to hand something to another app is the system's share
sheet: a page in the browser, a photo in the gallery, a PDF in the files app
(journey J5). Today a user who wants to ask about one must save it, open
Sibillo, start a chat and attach it by hand.

An installed web app joins the share sheet through the Web Share Target
API: its manifest names an address and the fields it accepts, and the system
opens that address with what was shared. Files can be shared only as a
`multipart/form-data` POST. Chromium on Android and ChromeOS supports it;
Safari on iOS does not, nor do desktop browsers elsewhere.

The app is a static single-page app served by the API (ADR-0067). It
attaches files by uploading them into the workspace of a conversation, which
a new chat creates with its first attachment (ADR-0079). The user may not be
signed in when something is shared, and the service worker that receives a
share has no session of its own to upload with.

What arrives this way comes from another app, or from any web page that
opens the same address with a form: it is untrusted, and it must not become
a message the user did not read.

## Decision

1. **The share target.** The manifest declares `share_target` with action
   `/share`, method `POST`, encoding `multipart/form-data`, the fields
   `title`, `text` and `url`, and files of any type in the field `files`.
2. **The service worker receives the share.** It answers a navigation that
   posts to `/share` itself: it reads the form, keeps the title, the text,
   the link and the files on the device, in the app's IndexedDB, with the time
   they arrived, and answers with a redirect to `/?shared=1`. Only the latest
   share is kept: a new one replaces it. It handles only navigations, so a
   script cannot leave a share behind without opening the app. Nothing is sent
   to the server at this point.
3. **The app offers a new chat with it.** When the app opens `/?shared=1`
   with a user signed in, it takes the kept share, deleting it from the
   device, and opens a new chat. The message box holds the text: the title,
   the text and the link, each on its own paragraph, leaving out empty ones
   and any already contained in another. The files are attached as if the
   user had picked them (CNV-017), which creates the conversation and uploads
   them into its workspace. Above the message box, the app says that the
   content was shared from another app and should be checked before sending.
   Nothing is sent until the user sends it; the user can edit the text, remove
   attachments, or leave the chat.
4. **Signed out.** The share waits on the device while the user signs in, and
   is offered once they have. A share older than one hour is discarded
   unread, so that one left on a shared device does not reach whoever signs
   in later.
5. **Nothing arrived.** When the app opens `/?shared=1` and finds no share,
   because it was too large to keep, expired, or the service worker was not
   running, the new chat opens with an error notice that says nothing arrived
   and that the user can share it again or attach the files in the chat
   (UX-014).
6. **Without the service worker.** The API answers a `POST /share` that
   reaches it with a redirect to `/?shared=1`, without reading what was sent,
   so that the app opens and says that nothing arrived.
7. **Provenance.** The text becomes the user's message only when the user
   sends it, after reading it in the box. The files are attachments, which
   are untrusted content as every attachment is (AGT-003, ADR-0090).

## Consequences

- A user on Android shares a page, a photo or a file to Sibillo in two taps,
  and asks about it in the chat that opens.
- On iOS and on desktop browsers other than ChromeOS, the app is not in the
  share sheet; users attach files and paste links as before. The
  requirement is a SHOULD for this reason.
- A shared file stays on the device, in the browser's storage, until the app
  reads it or a later share replaces it; at most an hour while nobody is
  signed in.
- A shared file larger than the upload limit (ADR-0079) is kept on the
  device, attached, and refused by the upload with the usual error.
- A web page can open the app with text of its choosing in the message box.
  The user sees it, is told where it came from, and decides whether to send
  it (T-40).

## Alternatives considered

- **Sharing with a GET share target:** simpler, with no service worker
  involved, but it carries no files, which are most of what people share.
- **Uploading in the service worker:** the share would reach the server
  before the user decides anything, and a signed-out device has no session to
  upload with.
- **Sending the shared text at once:** a page opening `/share` could then
  send a message as the user, with the provenance of the user's own words.
- **Choosing an existing conversation for the share:** useful, but it needs
  a picker in the share flow; a new chat covers the journey, and the files
  can be moved to another conversation by downloading and attaching them.
- **Keeping several shares:** a queue nobody sees; the latest share is the
  one the user expects to find.
