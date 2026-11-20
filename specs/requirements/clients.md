# UX — Client experience

What every first-party client must offer, on the web and on the phone.
Clients use only the public API (API-001). Background: ADR-0016, ADR-0039,
ADR-0040, ADR-0042, ADR-0067, ADR-0070, ADR-0111, and the personas and journeys of the
[product description](../product.md).

## UX-001: Installable web app

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e

The web client MUST work in current mobile and desktop browsers and MUST be
installable on the home screen of Android and iOS devices as a web app.

## UX-002: Rich message rendering

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e

Clients MUST render Markdown in messages, including tables, code blocks with
syntax highlighting and a copy action, and mathematical notation. Rendering
MUST NOT execute scripts or load remote resources contained in messages.

## UX-003: Simple by default, detailed on request

- **Status:** implemented
- **Priority:** SHOULD
- **Phase:** 1
- **Verification:** review

Clients SHOULD show tool activity, reasoning and sandbox output as compact
summaries that the user can expand to see full details. Tool activity MUST
appear where it happened among the answer's text, also while the answer
streams, and MUST show whether each call is still running or done. A command
the agent runs in the sandbox MUST say in a few words what it is for, which
clients show above the command (ADR-0085). When an answer ends and the
conversation's history takes the place of the streamed answer, nothing of
the answer MUST disappear, even for a moment. Approval prompts MUST
nevertheless always show the tool, its arguments and destination in full
(ADR-0033).

Rationale: personas P2 and P4 need clarity; persona P1 needs the details.

## UX-004: Notifications

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration, security, e2e

The installable web app MUST be able to receive notifications, with the user's
consent, when a run finishes while the user is away and when an approval or an
answer to a question is pending. Notification payloads MUST NOT contain
message text, titles, tool arguments or other conversation content; they MUST
carry only the kind of event and identifiers needed to open the right
conversation (ADR-0039).

Notifications MUST be off on every device until the user turns them on there,
and the user MUST be able to turn them off again. The server MUST NOT send a
notification for a run that a client of the user is following, or that the
user stopped, and MUST NOT use the subscription of a device session that is
revoked or expired. It MUST accept subscriptions only on the push services
ADR-0101 lists. Opening a notification MUST open its conversation (ADR-0101).

Rationale: journey J8; pending approvals expire (AGT-007), so users must learn
about them in time.

## UX-005: Voice turns

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e, eval

When the household has a transcription model (API-006), a user MUST be able
to speak a turn instead of typing it, and when it has a speech model, to have
any answer read aloud. The user ends a turn explicitly, and starts it
explicitly except in hands-free mode; pauses MUST NOT end it, and the
assistant MUST NOT speak while the user's turn is open. Answers to spoken turns MUST NOT be shortened or simplified because
they will be spoken (ADR-0040). Clients MUST offer:

- **dictation:** a spoken turn becomes the text of the message box, which
  the user reviews and sends. While the user speaks, the message box MUST
  show that the voice is being captured, with an animation that follows its
  loudness live, and a button that ends the turn;
  then it MUST show that the text is being prepared. The assistant is told
  that the message was dictated, so that it reads past what the
  transcription misheard;
- **reading aloud:** any answer can be read aloud, and stopped; code, tables,
  images and files are named, not read out;
- **hands-free mode:** for when the user cannot look at the screen, as when
  driving. The upper half of the screen shows the sprite acting out what
  happens: listening, working with its tools, reading the answer aloud
  (UX-013); one large button in the lower half, which a stray touch does not
  miss, starts and ends the user's turn, and shows the same animation while
  it listens; an ended turn is sent at once, and its complete
  answer is read aloud. Once it is read, the user's next turn starts by
  itself; pressing the button while the answer is read stops the reading
  and starts the next turn at once. The media buttons of a headset or a
  car, the next-track button among them, MUST act as the large button where
  the device passes them to the client. Sounds MUST say when the user's turn
  starts and ends, that the assistant is still working, that its answer is
  about to be read, and that something failed, so that the user knows where
  the conversation stands without looking; a phone that quiets its speaker
  while it opens the microphone MUST NOT swallow the sound of a turn
  starting. The screen MUST also say, in words, which step the turn is at:
  transcribing, writing the answer, preparing the voice, reading aloud,
  with how long the step has taken, so that a slow step is not taken for a
  stuck one; and when a step fails, which one and why. The assistant is
  told that its answer will be read aloud, and writes it for listening, no
  shorter and no simpler (ADR-0088).

Clients MUST say when a speech model runs remotely, as they do for models
(MOD-010).

Rationale: journey J9; persona P2 brainstorms while driving.

## UX-006: Sharing into the app

- **Status:** implemented
- **Priority:** SHOULD
- **Phase:** 1
- **Verification:** integration, e2e

On devices that support it, the installed web app SHOULD accept text, links,
images and files shared from other apps, and offer to start a conversation
with them: a new chat whose message box holds the shared text and link, with
the shared files attached (CNV-017). Clients MUST NOT send anything shared
until the user sends it, and MUST say above the message box that its content
was shared from another app. A share MUST stay on the device until it is
offered, and MUST be offered only to a user signed in within an hour of
sharing. When nothing arrives, clients MUST say so (UX-014) (ADR-0102).

Rationale: journey J5.

## UX-007: Accessibility

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e, review

Clients MUST meet WCAG 2.2 level AA, MUST respect the system text size and
MUST remain usable with text enlarged to 200%.

Rationale: persona P4.

## UX-008: Live context and cost

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e

While a run streams, clients MUST show how much of the model's context window
the conversation uses, and the cost of the run so far on pay-per-token
providers. Clients MUST show the cost of each assistant message beside it,
and keep in view the cost of the open conversation and the user's spend over
the last 24 hours and the last 30 days (MOD-006, MOD-007, ADR-0073).

Rationale: journey J12.

## UX-009: Progress and questions during long tasks

- **Status:** implemented
- **Priority:** SHOULD
- **Phase:** 1
- **Verification:** e2e

The assistant SHOULD keep a task list for long tasks, one per conversation,
which lasts from one run to the next. During a run, clients SHOULD show the
task list as it updates, and its latest state when the conversation is
opened. Clients MUST show the questions the assistant asks the user
(AGT-015) as choices the user can answer, in their own words or by skipping
the question, in place of the message box, also when the conversation is
opened later; several questions are shown one at a time, and the controls to
answer stay in view on any screen (ADR-0083).

Rationale: journey J7.

## UX-010: Rewinding asks first and says the files stay

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e

Before a conversation is rewound (CNV-004), including by editing an earlier
message (CNV-016), clients MUST ask the user to confirm, say how many
messages will be deleted, and tell them that files in their workspace are
not changed by rewinding.

Rationale: journey J2.

## UX-011: Light and dark themes

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e

Clients MUST offer a light and a dark theme, follow the device's setting by
default, and let the user choose one instead. Both themes MUST meet the
contrast that UX-007 requires.

## UX-012: The sprite greets the user

- **Status:** implemented
- **Priority:** SHOULD
- **Phase:** 1
- **Verification:** e2e

When the user starts a new conversation, clients SHOULD show the sprite
greeting them with a quote chosen at random from a list of famous quotes in
the public domain, with its author and work, translated with the rest of the
interface (ADR-0111).

## UX-013: The sprite shows what a run is doing

- **Status:** implemented
- **Priority:** SHOULD
- **Phase:** 1
- **Verification:** e2e, review

While a run is in progress, clients SHOULD show the sprite acting out what
the assistant is doing: thinking, searching the web, reading, writing files,
running commands or answering, and in hands-free mode listening to the
user (UX-005); when the run ends, it stands still. The sprite
MUST be decorative: the same activity MUST be given as text, and the sprite
MUST NOT move when the device asks for reduced motion (ADR-0111).

## UX-014: Errors say what to do

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e

Clients MUST show errors so that they say what went wrong and how to fix it,
announced to assistive technologies, and SHOULD show the sprite holding a sign
beside them (ADR-0111). An error that ended a run MUST be shown in the
conversation, in place of the run's answer, with the reason the model or its
provider gave (MOD-015), and MUST stay there when the conversation is reloaded
or opened on another device: it is part of the conversation, not a notice to
dismiss. The reason stays too when the run's stored answer keeps it, as a
refusal's does. Other errors are shown in a notice.

Rationale: personas P2 and P4.

## UX-015: Choosing the model

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e

Clients MUST let the user choose the model of a conversation (MOD-012), and
tenant admins the default model, among every model of their household's
connections, and search them, with the same picker. For each
model they MUST show its connection, its name, whether it runs locally or
remotely (MOD-010), its price when it is paid per token, and whether it can
only chat, without tools (MOD-014).

Clients MUST show the settings of the household, such as its default model
and its connections, only to tenant admins, set apart from the user's own
settings and named as the household's, and MUST say that they apply to every
user of the household. Where a user's own setting overrides one of the
household's, as a user's default model does, clients MUST say so and show
the household's value that applies when the user sets none.

## UX-016: Testing a connection in the settings

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e

When a tenant admin adds or changes a connection, clients MUST show the
result of its test (MOD-013) step by step, with the reason for a failure and
how to fix it, and MUST show the technical details on request. Clients MUST
ask only for what the kind of connection needs: for OpenRouter, the API key.

## UX-017: One design language

- **Status:** accepted
- **Priority:** SHOULD
- **Phase:** 2
- **Verification:** review

Clients SHOULD follow the design language of ADR-0111: its design tokens,
shared components, screens, typefaces, icons and sprite, as the reference
prototype shows them. Two controls that do the same job SHOULD look and
behave the same on every screen.

Rationale: the first design language (ADR-0070) named colors only, and the
screens drifted apart; UX-037 checks what a test can check, and a reviewer
the rest.

## UX-018: Typing starts where the user expects

- **Status:** implemented
- **Priority:** SHOULD
- **Phase:** 1
- **Verification:** e2e

On devices with a keyboard, clients SHOULD put the focus in the field where
the user starts typing: the username on the sign-in screen, and the message
box when a new chat opens. On touch screens they SHOULD NOT, since focusing a
field opens the on-screen keyboard over the screen.

## UX-019: The workspace panel

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e

Clients MUST let the user browse a conversation's workspace as a tree,
beside the conversation or, on a phone, as a full-screen sheet, with each
entry's size and when it changed, and the workspace's size against its quota
(SBX-019). The user MUST be able to preview, download, upload into a folder,
create a folder, rename and move, and delete files and folders, and reset the
whole workspace; deleting and resetting MUST ask first. A folder MUST download
as a `.zip`. The panel MUST show the workspace as it is after each answer
(ADR-0079).

## UX-020: Workspace files never run in the app

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** security, e2e

A workspace file MUST NOT be served or shown as a page or a script of the
app's origin. The API MUST serve a file for download as an attachment, and
for preview only as one of a fixed list of types, with
`X-Content-Type-Options: nosniff` and a Content Security Policy that lets a
file opened by itself run nothing in the app's origin; clients MUST show HTML
as its source, or run it as a web page in an opaque origin without network
(ART-003), and SVG as an image (ADR-0079, ADR-0086, T-22).

## UX-021: Side panels the user can resize

- **Status:** implemented
- **Priority:** SHOULD
- **Phase:** 1
- **Verification:** e2e

On screens wide enough to show them beside the conversation, clients SHOULD
let the user resize the conversation list and the workspace panel by
dragging their edge, and also with the keyboard, between a minimum and a
maximum width that keep the conversation readable. Each width SHOULD be kept
on the device, and SHOULD return to its default when the user double-clicks
the edge (UX-007, UX-019).

Rationale: long file names, wide pages and diagrams need a wider panel; a
long answer needs a narrower one.

## UX-022: Approval prompts

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e

Clients MUST show a pending approval request (AGT-007) in place of the
message box, as they show questions (UX-009), also when the conversation is
opened later, with the time left before it is denied. The prompt MUST show
the tool by its label and name, its arguments in full, the data it sends
and where, and why it needs approval in plain words; when the reason is
untrusted content, it MUST say that what the assistant read could be trying
to steer it. The prompt MUST offer exactly the answers the request offers
(ADR-0090), with Deny first and never preselected, and approvals and
questions pending together MUST be answered together.

Rationale: journey J7; approval fatigue is a residual risk of the threat
model, so a prompt must be rare and say what is at stake.

## UX-023: Seeing and governing what tools do

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e

Clients MUST show, on each tool call in a conversation, whether it needed
approval and how it was answered (AGT-008). They MUST show a conversation's
allowances (AGT-006) with its settings, each one withdrawable. They MUST
offer an Activity page among the user's settings, listing the user's audit
events, newest first, filterable by conversation and by tool, each linking
to its conversation while it exists and flagging calls that may have run
twice. Among the household's settings (UX-015), clients MUST let tenant
admins set each user's tool permissions (AGT-002), per tool and per
capability class, showing what applies to each tool and why.

Rationale: journey J7; persona P1 checks what the assistant did, and the
household's admin decides what each member's assistant may do.

## UX-024: Local models only

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e

Clients MUST let each user choose, among their own settings, to use only
local models (MOD-003), and say when the household or a tenant admin has
already chosen it for them. Among the household's settings (UX-015), they
MUST let tenant admins choose it for the household and for each user.

When the data egress policy that applies to the user refuses remote models,
the model picker (UX-015) MUST show remote models as unavailable, saying
why; a conversation whose model is refused MUST say so before the user
sends a message, and a run refused with `model.egress_refused` MUST say why
and let the user choose a local model. Spoken turns and reading aloud MUST
be shown as unavailable, saying why, when the policy refuses the household's
speech models (ADR-0091).

Rationale: journey J14; the household decides what may leave the house, and
each member sees what that means for them.

## UX-025: Changing a connection in the settings

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e

Among the household's settings (UX-015), clients MUST let tenant admins
change a connection as the API allows (MOD-008): its name, and for a
connection to the household's own server its address, where it runs and its
context window, which they MUST also let admins set when they add one. A new
API key replaces the old one, which clients MUST NOT show; leaving the key
empty keeps it, and admins MUST be able to remove the key of a connection to
their own server. A change that fails its test is not saved, and clients MUST
show its test as when adding a connection (UX-016).

Rationale: an admin who raises the window of their own server, or moves it
to another address, should not have to remove the connection and lose the
conversations' choice of its models.

## UX-026: Passkeys in the app

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e

Among the user's own settings, clients MUST list the user's passkeys
(AUTH-010), each with its name, when it was created and when it was last
used, and MUST let the user add one, asking for their password and a name,
and remove one, asking for their password. When the instance cannot use
passkeys (ADR-0094), clients MUST say so and that the instance admin can
enable them. At sign-in, after the password of a user who has passkeys,
clients MUST ask for a passkey, and MUST let the user ask for it again or
go back to the password when the device's prompt is cancelled or fails.
Among the household's settings (UX-015), clients MUST show tenant admins
how many passkeys each user has, and let them remove them all, after
confirming that the user will then sign in with their password alone.

Rationale: a second factor that is hard to add, or that locks
someone out, would be turned off.

## UX-027: Memory in the app

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e

Among the user's own settings, clients MUST offer a Memory page with the
switch that turns memory on and off (MEM-006), the user's memory items
newest first, and how much of the limit they use (MEM-007). Each item MUST
show its text, when it was last written, and where it came from: the user,
or the conversation it was written in, linked while it exists (MEM-005).
Untrusted items (MEM-008) MUST be marked, with the explanation that they
were written after the assistant read content that was not the user's, and
saving one MUST be offered as the way to confirm it. The page MUST let the
user add an item, edit one, delete one, and delete all after asking. In a
conversation, a call to a memory tool MUST show what was remembered,
changed or forgotten, and lead to the Memory page (ADR-0095).

Rationale: journey J11.

## UX-028: Skills in the app

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e

Among the user's own settings, clients MUST offer a Skills page listing the
built-in skills and the user's, each with its name, description and a
switch, and the user's with where they came from (AGT-025). Untrusted skills
MUST be marked, with the explanation that someone other than the user wrote
them; marking one trusted MUST first show its files. The page MUST let the
user create a skill, edit its `SKILL.md` and text files, upload an archive,
import from a URL choosing among the skills found, download a skill, and
delete one after asking. Conversation settings MUST list the skills that are
on, each with a switch, and show a skill off in the conversation as off. In
a conversation, loading a skill MUST show which skill the assistant uses,
and a call to `save_skill` MUST show the skill saved and lead to the Skills
page (ADR-0096).

Rationale: journey J13.

## UX-029: Remote MCP servers in the app

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e

Among the household's settings, clients MUST let a tenant admin add a remote
MCP server, with its name, prefix, address and authentication, and an OAuth
client when the service needs one, and change, refresh, switch off and
remove one, showing why a connection failed. For each server they MUST list
every tool it offers, with its name, title, description, input schema and
annotations, and let the admin accept or withdraw each one; a tool that
changed since it was accepted MUST be shown as changed, with what changed
(AGT-028). The tool permissions of a user MUST list the servers, each of
which the admin can deny. The user's tool switches, in a conversation and in
their defaults, MUST show each server as a group with one switch and its
accepted tools, and a denied server switched off and locked. For a server
that needs a credential, they MUST show whether the user's account is
connected, let the user enter a token or sign in, with advice to give a
token the least rights it needs, and remove their credential (AGT-030,
AGT-031). In a conversation, a call to a server's tool MUST show the
server's name, and its approval request the arguments and the server's host
(AGT-018, ADR-0099, ADR-0100).

Rationale: journey J13.

## UX-030: The thread follows the answer only from its end

- **Status:** implemented
- **Priority:** SHOULD
- **Phase:** 1
- **Verification:** e2e

While an answer streams, clients SHOULD keep the end of the conversation in
view only while the user is at its end. When the user scrolls up, new text
MUST NOT move the conversation; clients SHOULD instead show at its end a
sign that new text has arrived, which takes the user back to the end when
chosen. Back at the end, the conversation follows the answer again.

Rationale: a user who scrolls up to read the start of a long answer loses
their place if every new piece of text pulls them back down.

## UX-031: Tasks in the app

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 2
- **Verification:** e2e

Clients MUST let a user create, change, pause, resume, fire at once
(TSK-011) and delete their tasks among their settings, with the task's
instructions, settings, time zone, triggers and grants. For a schedule they MUST say in words when it fires,
from its start and recurrence, and show the next firing, or that it ended
(ADR-0109); for a webhook trigger, show its address once and let
the user replace it; for an event trigger, offer the accepted event types of
the servers the user may use and a form for the subscription's arguments
from its schema. Grants MUST be chosen from the tools the task may be given,
with the arguments of a fixed grant in full, and a task that TSK-005 refuses
MUST be shown with the reason and which grants to remove. A task's page MUST
list the conversations it started, newest first, with their outcome, and the
latest skipped firings (TSK-009). In the conversation list, a conversation a
task started MUST show the task's name, and in the conversation, the calls
denied as `not_granted` MUST be shown as such (TSK-002, TSK-004).

Rationale: journey J15.

## UX-032: The app follows what changes

- **Status:** implemented
- **Priority:** SHOULD
- **Phase:** 2
- **Verification:** e2e

While open, clients SHOULD follow the stream of API-008 and show what it
announces without the user reloading: a conversation a task started SHOULD
appear in the conversation list within seconds, marked as running until its
first run ends, and a task's page SHOULD show its new conversations and
their outcome as they change. After the stream is lost, clients MUST reload
what they show when it returns (ADR-0108).

Rationale: journey J15.

## UX-033: Notifications that are off say so

- **Status:** implemented
- **Priority:** SHOULD
- **Phase:** 2
- **Verification:** e2e

While notifications are available on the instance (UX-004) and off on the
device, clients SHOULD show a lasting sign of it in their main view, which
turns them on from a button, says how to allow them when the browser blocks
them, and which the user MAY dismiss on that device; a dismissed sign MUST
NOT come back on that device until the user turns notifications on and off
again (ADR-0101).

Rationale: journeys J8 and J15: a task's answer waits for a user who
learns of it.

## UX-034: Escape stops the answer

- **Status:** implemented
- **Priority:** SHOULD
- **Phase:** 2
- **Verification:** e2e

While a run of the open conversation is in progress, pressing Escape SHOULD
stop it, as the stop button does (CNV-003), unless a dialog or a menu is open,
which Escape closes instead.

Rationale: journey J2; the keyboard reaches the stop button only by moving
focus to it.

## UX-035: The end of an answer leaves the thread where it is

- **Status:** implemented
- **Priority:** SHOULD
- **Phase:** 2
- **Verification:** e2e

When a run ends, clients SHOULD NOT scroll the conversation: what the user is
reading stays in place, also when the conversation's history is reloaded
after the run (UX-030).

Rationale: the thread jumps to its end when an answer finishes, away from
the part of the answer the user was reading.

## UX-036: Pasting an image attaches it, with a preview

- **Status:** implemented
- **Priority:** SHOULD
- **Phase:** 2
- **Verification:** e2e

Pasting an image, or files, into the message field SHOULD attach them as
picking them does (CNV-017), instead of inserting text. Attached images
SHOULD show as small previews in the composer before sending and in the
message once sent, each removable before sending (ADR-0110).

Rationale: journey J5; a screenshot is pasted far more often than saved and
picked.

## UX-037: Screens are built from the shared components

- **Status:** accepted
- **Priority:** MUST
- **Phase:** 2
- **Verification:** design

The web client MUST take every color, size of text, spacing step, radius,
control height, shadow and duration from the design tokens of ADR-0111, and
MUST build its buttons, fields, selects, switches, dialogs, menus and the
other controls ADR-0111 lists only from the shared components. Outside the
shared components its code MUST NOT style a native control, use a value that
is not a design token, write a color, or show a control with the browser's
own look.

Rationale: most of the client is written by coding agents, which copy the
nearest styles and change them; a rule that only a reviewer checks did not
hold (UX-017).

## UX-038: Nothing is blank

- **Status:** accepted
- **Priority:** SHOULD
- **Phase:** 2
- **Verification:** e2e

A list with nothing in it SHOULD say what it is for and, where the user may
add an entry, offer the action that adds the first one. While content loads
or an action of the user is in progress, clients SHOULD show that it is, and
SHOULD NOT let the action be started twice (ADR-0111).

Rationale: persona P4; an empty page reads as a broken one.
