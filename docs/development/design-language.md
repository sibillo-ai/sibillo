# The design language of the web client

How to build a screen of the web client so that it looks and behaves like
every other one. The decision is
[ADR-0111](../../specs/adr/0111-a-design-language-of-tokens-and-shared-components.md);
the requirements are UX-017, UX-037 and UX-038; the reference is the prototype,
[`specs/design/web-prototype-2.html`](../../specs/design/web-prototype-2.html),
which opens in a browser.

## The two rules

1. **Design tokens are the only values.** Colors, sizes of text, spacing,
   radii, control heights, widths, shadows and durations are named in
   `src/web/src/styles.css`. A screen uses their utilities and nothing else.
2. **Shared components are the only controls.** Buttons, fields, selects,
   switches, dialogs, menus and the rest live in `src/web/src/ui/`. A screen
   assembles them; it never styles a `<button>` or an `<input>` of its own.

A design test, `tests/design/test_web_design_language.py`, fails when a file
outside `src/web/src/ui/` breaks either rule. It is what keeps a copied string
of classes from coming back.

## The tokens, as utilities

| Kind | Use | Never |
|---|---|---|
| Color | `canvas`, `sunken`, `surface`, `raised`, `line`, `line-strong`, `ink`, `ink-2`, `ink-3`, `hover`, `pressed`, `scrim`, `accent`, `accent-soft`, `on-accent`, `ok`, `warn`, `danger` and their `-soft` backgrounds, as in `bg-surface`, `text-ink-2`, `border-line` | a color written out, in any notation |
| Type | `text-display` (with `font-serif`), `text-title`, `text-reading`, `text-body`, `text-small`, `text-caption`; `font-normal`, `font-medium`, `font-semibold` | `text-sm`, `text-lg`, `font-bold`, `text-[13px]` |
| Space | padding, margin and gap on the steps `1 2 3 4 6 8 12` (4 to 48 px), `0`, `px` | `gap-2.5`, `p-5`, `mt-[18px]` |
| Radius | `rounded-sm` (6), `rounded-md` (10), `rounded-lg` (16), `rounded-full` | bare `rounded`, `rounded-xl` |
| Width | `max-w-read` (720), `max-w-form` (640), `max-w-dialog-sm`, `-md`, `-lg`, `w-sidebar` (272) | `max-w-[62ch]` |
| Elevation | `shadow-line`, `shadow-float`, `shadow-above` | `shadow`, `shadow-md` |
| Motion | `duration-120` for hover and press, `duration-200` for what enters, `ease-soft` | other durations |

A size that depends on the window is a fraction or a viewport unit of
Tailwind's own scale (`max-w-4/5`, `max-h-dvh`), or a CSS variable set in
`style` and read with the shorthand, as in `w-(--list-width)`. The edges of a
phone's screen are `pt-safe`, `pb-safe`, `pl-safe` and `pr-safe`.

## Which component, when

| To | Use |
|---|---|
| Do something | `Button`: `primary` once per view at most, the default otherwise, `ghost` in bars, `danger` for removals. `IconButton` when an icon says it alone; its `label` is its name. |
| Ask for text | `FormField` around `TextInput` or `TextArea`; `SearchInput` for a search |
| Choose | `Select` among many, `Segmented` among a few, `ToggleGroup` among views, `Radio` in rows with descriptions, `Switch` for on or off, `Checkbox` for any of several |
| Lay out a page | `Page`, then `Group`s, each with a `Card rows` of `Row`s: what it is on the left, the control on the right. Lists are rows too. Cards never nest. |
| Say something in place | `Notice` (`neutral`, `warn`, `error`); `Badge` for a short state beside a name |
| Show an empty list | `EmptyState`: a title, a sentence that says what the list is for (required), and the action that adds the first entry where the user may add one (UX-038) |
| Show a wait | `Loading` in place of the list or page while its query is pending, so that a list never says it is empty before it knows (UX-038) |
| Run an action | `useBusy` from `src/web/src/busy.ts`: `run(key, work)` ignores a second press while the first is in progress, and `busy(key)` gives the button its busy state. A dialog that confirms an action stays open, its button busy, until the action is done (UX-038). |
| Ask or edit apart | `Dialog`: a form with `onSubmit`, its buttons in `footer`, the action last; `asks` before what cannot be undone, with a `danger-solid` action |
| Offer actions | `Menu` with `MenuItem`s |
| Move through a list | `NavItem`, or `NAV_ITEM` on a link |
| Build a conversation | `ui/MessageBox`, `ui/Message`, `ui/RequestCard`, `ui/Panel` |

The accent is rare: it marks sending a message, the focused control and the
sprite. Buttons and switches are ink. An action that cannot be undone has a
verb of its own, an icon or the danger variant, and a confirmation.

## Seeing the components

```sh
cd src/web
corepack pnpm vite
```

Then open `/gallery.html`: every shared component in each of its states, with
a button for the dark theme. The page is served by the development server
only and is not part of the build. Compare it with the prototype when you
change a component.

## When something is missing

A screen that needs a control or a variant the shared components lack adds it
to `src/web/src/ui/`, to the gallery and, when it changes the design, to the
prototype, before the screen uses it. A design that needs a value outside the
tokens needs a change to ADR-0111 first.

Keep every role, name and label that a test or a screen reader relies on:
the browser tests find controls by role and name, never by their look.
