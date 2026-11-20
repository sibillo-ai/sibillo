# ADR-0111: A design language of tokens and shared components

- **Status:** Accepted
- **Date:** 2026-11-20
- **Deciders:** @tapionx
- **Related:** UX-017, UX-037, UX-038, UX-039, UX-003, UX-005, UX-007, UX-008, UX-011, UX-012, UX-013, UX-014, UX-015, UX-019, UX-033, OBS-001, I18N-001, ADR-0067, ADR-0070, ADR-0088

## Context

ADR-0070 gave the web client a design language: colors as tokens, three
typefaces, one icon set and the sprite. It named colors and nothing else, and
it ended with "new screens reuse the tokens and components" without saying
which components. A count of the client, twenty features later, shows what
that left open:

- no shared component: 121 buttons, 48 fields and 48 dialogs, each styled
  where it is used; the same string of classes for a button is copied into
  nine files, and the copies have drifted;
- 20 sizes of text, 17 corner radii and 5 heights for one kind of control;
- two different selects on one page, section titles of different sizes from
  page to page, and columns of four different widths;
- lists that show a bare sentence when they are empty;
- an accent red almost equal to the red of errors, and used for every switch,
  so that a page of switches reads as a page of alarms.

UX-017 asks for one design language and is verified by review alone, so
nothing stops the next feature from copying the nearest string and changing
it. Most of the client is written by coding agents, which copy what they
find.

The maintainer judged the result sufficient, wants an interface that feels
solid and is the same on every screen, and asked for a design made anew
rather than a repair. A prototype of the new design was built and approved
before this record; it is kept as
[`specs/design/web-prototype-2.html`](../design/web-prototype-2.html).

## Decision

This record supersedes ADR-0070. It keeps the typefaces, the icon set, the
sprite and the quotes, and replaces the rest.

1. **A house, not a dashboard.** Sibillo lives in a home: the interface is
   warm paper and ink, quiet until something needs attention. It keeps the
   layout people know from other assistants (the conversation list on the
   side, one centered column, the message box below) and takes no other
   product's identity: no logos, colors, typefaces or illustrations of
   another product.
2. **Design tokens are the only values.** Every color, size of text, spacing
   step, radius, control height, width of content, shadow and duration in
   the client is a design token, and the tokens are these:

   | Kind | Tokens |
   |---|---|
   | Color | Sixteen roles, each with a light and a dark value: `canvas`, `sunken`, `surface`, `raised`, `line`, `line-strong`, `ink`, `ink-2`, `ink-3`, `hover`, `scrim`, `accent`, `accent-soft`, `ok`, `warn`, `danger`; and the soft backgrounds of `ok`, `warn` and `danger`. The sprite's own colors are apart and the same in both themes. |
   | Type | Six roles: display 30/36, title 18/24, reading 16/26, body 14/20, small 13/18, caption 12/16; three weights: 400, 500, 600 |
   | Space | 4, 8, 12, 16, 24, 32, 48 |
   | Radius | 6 for items and badges, 10 for controls, 16 for cards and dialogs, full for avatars and the send button |
   | Control height | 32 and 40; at least 44 where the pointer is a finger |
   | Width | reading column 720, form column 640, dialogs 400, 560 and 720, sidebar 272 |
   | Elevation | three levels: on the page (a line, no shadow), floating (menus, the message box), above the page (dialogs, over a scrim) |
   | Motion | 120 ms for hover and press, 200 ms for what enters; one curve; none when the device asks for reduced motion (UX-007) |

   The values are those of the prototype. The theme follows the device
   unless the user chooses one (UX-011), and text meets the contrast UX-007
   requires in both. Tailwind (ADR-0067) is configured with these scales in
   place of its own, so that a size outside them has no class.
3. **The accent is rare.** Red marks the one thing to do next, which is
   sending a message, the focused control, and the sprite. Primary buttons
   and switches that are on are ink. Success, attention and errors have
   their own colors. Because the red of errors is close to the accent, an
   action that cannot be undone never relies on color: it has a verb of its
   own, an icon, and a confirmation.
4. **Typefaces have roles.** Newsreader is the voice of the house: the
   greeting, the title of a page, quotes. Hanken Grotesk is everything the
   user operates or reads at length. JetBrains Mono is code, paths and
   addresses. All three are under the SIL Open Font License and served by the
   app itself, so that no font request reaches a third party (OBS-001).
5. **One icon set.** Lucide's icons (ISC license), imported one by one, drawn
   at 16 px in controls and rows.
6. **Shared components are the only controls.** The client has one
   implementation of each of these, in `src/web/src/ui/`, and screens are
   assembled from them (UX-037):

   | Shared component | What it is for |
   |---|---|
   | Button | Primary (once per view at most), secondary, ghost (in toolbars), danger; two sizes; with an icon, or an icon alone with a name for assistive technologies; a busy state |
   | Field | One line of text, several lines, or a search; with a label above and a hint or an error below |
   | Select | A choice among options; closed, it looks like a field on every browser, and the list it opens is the device's own, which is what a phone's user expects |
   | Switch, Segmented control, Radio | On or off; one of a few; one of several with descriptions |
   | Badge | A short state beside a name: neutral, ok, warn, accent |
   | Card and Row | A card holds rows divided by lines. A row says what it is on the left and has its control on the right. Settings and lists are both made of rows; cards never nest |
   | Group | A heading, an optional description and an optional action above a card |
   | Page header | The title of a page, in the display role, and what the page is for |
   | Notice | A message in place: neutral, warn or error, with at most one action (UX-014, UX-033) |
   | Empty state | What a list is for and the action that adds its first entry (UX-038) |
   | Dialog | A title, a body and a footer whose rightmost button is the action; three widths; a sheet from the bottom on a phone |
   | Menu | Actions or options that float; the model picker is a menu with a search (UX-015) |
   | Navigation item | An entry of the conversation list, of the settings' sections, or of a tree of files (UX-019) |
   | Top bar | The bar at the top of a page: on a phone, the button that opens the conversation list or the one that goes back, then where the user is; then the page's own actions, at its right end (UX-039) |
   | Message box, Message, Activity, Request card | The parts of a conversation: the composer; a user's message and an answer; what a run did, as compact lines that each expand (UX-003); an approval or a question waiting above the message box |

   Outside that directory the client does not style a native control, does
   not use a value that is not a token, and does not write a color. A design
   test fails when it does. A new kind of control is added to the shared
   components, and to the prototype, before a screen uses it.
7. **The screens.**
   - *The shell.* The sidebar holds the name and the sprite, with the button
     for a new folder beside them; the search, with the new chat beside it as
     a square button with a pencil, as tall as the search; the conversations
     in their groups (the pinned ones, the folders, the rest), and at its
     foot the settings and the user, with their spend over the last 24 hours
     and the last 30 days (UX-008) and the button that signs out. A notice
     that notifications are off sits above the foot (UX-033). The user may
     resize the sidebar (UX-021); 272 is the width it starts with. On a phone
     the sidebar is a page of its own, as wide as the screen, so that the
     titles of the conversations can be read (UX-039).
   - *On a phone every page has a top bar* (UX-039). It holds what the
     computer shows elsewhere: the button that opens the conversation list,
     or Back where the page has a parent, and where the user is. There is no
     other bar above it. On a computer a conversation and a new chat have
     one too, for their own actions.
   - *A new chat.* The top bar has the temporary chat at its right end. The
     greeting, its quote and the model the chat will start with sit together
     in the middle, above the message box: the model is chosen before the
     first message, as part of starting.
   - *A conversation.* Its top bar has its title, its model, its cost and
     its context, its files and its settings, on a computer and on a phone
     alike. On a computer the cost and the context are a line under the
     title. On a phone, where one line has no room for them, the bar has a
     second line: the model with its name in full at its start, the cost as
     an amount alone and the share of the context at its end; the files are
     an icon. The model belongs to the conversation, not to
     the next message, so it is not in the message box. The answer is plain
     text in the reading role; the user's message is a bubble. Approvals and
     questions wait above the message box.
   - *Settings.* One column of the form width: a page header, then groups of
     rows. The household's settings stay apart from the user's and named as
     the household's (UX-015). On a phone the sections are a list the user
     enters, one page at a time; the top bar names the page that is open and
     has Back, which leads from a section to the list of sections, and from
     the list to the conversation list. The device's own Back does the same
     (UX-039).
   - *Side panels*, such as the files of a conversation, open beside the
     conversation, and full-screen on a phone (UX-019).
8. **Nothing is blank.** A list with nothing in it shows an empty state, and
   a wait shows that it is a wait (UX-038).
9. **The sprite is an original sibillo.** Small and lanky, with a big
   floppy red hat, pointy ears, straw-colored hair and eyes closed in a smile,
   in red stockings. It is drawn as SVG and animated with CSS: an animation
   runtime would add weight, and the Content Security Policy blocks the
   WebAssembly some of them need (ADR-0067). It has one pose per moment:

   | Moment | Pose |
   |---|---|
   | The home screen | waves, beside the greeting and a quote (UX-012) |
   | The model is working | thinks, with dots above its head |
   | Searching the web | searches with a lens |
   | Reading a page or a file | reads a book |
   | Writing a file | writes in a notebook |
   | Running a command | knocks with its mallet |
   | The answer streams | bobs gently |
   | Listening, in hands-free mode | holds a hand behind its ear (UX-005, ADR-0088) |
   | The run has ended | stands still, waiting |
   | An error | holds up a sign, in the error notice (UX-014) |

   Clients choose the pose from the run's events: the tool being called
   decides it, and any other tool shows the thinking pose (UX-013). The
   sprite is decorative: hidden from assistive technologies, with the same
   information given as text, and still when the device asks for reduced
   motion (UX-007).
10. **Quotes from the public domain.** The greeting shows a quote chosen at
    random from a short list of famous lines whose authors died long ago, in
    translations that are in the public domain or written by the project,
    with author and work, kept in the client's translation files (I18N-001).
11. **The prototype is the reference.** The implementation follows its
    tokens, components, screens and wording. Its sample data and its
    prototype bar are not part of the design. A screen it does not show is
    built from the same components, and added to it when it needs a
    component the prototype lacks. The prototype of ADR-0070 stays in the
    repository as history.
12. **A gallery of the real components.** The client has a page, served only
    by its development server and left out of the build, that shows every
    shared component in each of its states and in both themes. It is what a
    reviewer compares with the prototype.

## Consequences

- Every screen of the client is rebuilt from the shared components. The
  order is: tokens, shared components and gallery; settings and dialogs; the
  conversation and the message box; the shell and sign-in. Until the last
  step the client mixes the two looks, so the steps land close together.
- A feature's screen costs less to write and to review: it has no styles of
  its own to judge.
- The design test (UX-037) is what keeps coding agents from drifting: a
  copied string of classes no longer passes.
- Looks are still not tested automatically: tests check behavior,
  accessibility and that only tokens and shared components are used; a
  reviewer checks the gallery and the screens against the prototype
  (UX-017).
- Browser tests that find controls by their styling, if any, change with the
  screens; tests that find them by role and name do not.
- The comments and documents that cite ADR-0070 for the sprite are updated
  as the code they sit in is touched.
- A design that needs a value outside the tokens needs a change to this
  record first. That is the point, and it will sometimes be a nuisance.

## Alternatives considered

- **Repairing the existing look:** extracting the copied strings into shared
  components without changing the design. It removes the drift and keeps an
  interface the maintainer finds merely sufficient; the work of touching
  every screen is the same.
- **A ready-made component kit with its own look:** quick, and recognizably
  generic (ADR-0070 refused it for the same reason). Radix (ADR-0067) stays
  underneath, for behavior and accessibility, without a look.
- **Guidelines without a test:** UX-017 was that, and the client drifted in
  three weeks.
- **Comparing screenshots in CI:** catches any change of a pixel, including
  the wanted ones and those of a font renderer, and costs time the budget of
  ADR-0059 does not have. The design test checks the cause instead.
- **Red primary buttons and switches:** more of the sprite's color, at the
  price of a red that no longer means anything and sits beside the red of
  errors.
