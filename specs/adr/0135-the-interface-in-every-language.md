# ADR-0135: The interface in every language

- **Status:** Accepted
- **Date:** 2026-11-23
- **Deciders:** @tapionx
- **Related:** ADR-0019, ADR-0067, ADR-0101, ADR-0103, I18N-001, I18N-002, I18N-003, I18N-004, I18N-005, I18N-006, API-007

## Context

ADR-0019 decided to ship English and Italian from the first release, and
I18N-002 asked for nothing more. The assistant already answers in any
language (I18N-003), and every string of the web client already comes from
translation resources (I18N-001), but the only resource is English and the
interface's language is fixed to it. Sibillo is meant for any household, not
only an Italian one, and a household is not a place where everyone reads
English.

Translations made by people cover only the languages someone volunteers for,
and fall behind each time a string changes. Models translate short interface
strings well, in a few minutes for every language, at a cost of cents.
Offering a language also takes more than its strings: the plural forms,
dates and numbers of that language, and, for Arabic, Hebrew, Persian or Urdu,
a layout that reads from right to left.

## Decision

1. **Every language of the list.** The web client offers its interface in
   every language of the list of common languages of ADR-0103, the same list
   the preferred language is chosen from. The list moves from
   `src/web/src/languages.ts` to `src/web/src/locales/languages.json`, as
   `{"languages": [...], "reviewed": [...]}`, which the client and the tests
   both read. Each language has one translation resource,
   `src/web/src/locales/<tag>.json`, with the keys of `en.json`. English is the
   source: a key that a translation lacks shows its English text, key by key.
2. **Reviewed and model-made translations.** A translation is reviewed when a
   person has checked all of it; its tag is then in `reviewed`. English and
   Italian are reviewed, and must stay complete: each has every key of
   `en.json`. Every other language is translated by a model and may lack keys.
   Where the user chooses a language, a language whose translation is not
   reviewed is marked as translated automatically. A contributor who reviews
   a translation completes it and adds its tag to `reviewed`.
3. **Translations follow the English text.** `src/web/src/locales/sources.json`
   records, for each language but English and each of its keys, a hash of the
   English text it was translated from. A translation whose English text has
   changed since is stale, and CI fails on it, as on a key `en.json` no longer
   has, and on a translation whose placeholders (`{{name}}`) differ from the
   English text's. A script of the web client, `pnpm translate`, translates
   the missing and stale keys of the model-made languages with a model, given
   an OpenAI-compatible endpoint and key from the environment, and records
   their sources; `pnpm translate --prune` only removes stale and unknown
   keys, so that a change of an English string needs no model to pass CI, and
   shows English until the next translation. A person who translates a
   reviewed language records its sources with `pnpm translate --record <tag>`.
   Models run only on a developer's machine, never on the instance or at
   runtime.
4. **The interface's language.** The interface language is the user's
   preferred language (ADR-0103) when the client has a translation for it;
   otherwise the first of the browser's languages for which it has one;
   otherwise English. A tag is matched by lookup (RFC 4647): `pt-BR` is
   `pt-BR`, then `pt`; `zh-Hant-TW` is `zh-Hant`. Before sign-in, the
   browser's languages decide. A change of the preferred language changes the
   interface at once, without reloading. There is no separate setting for the
   interface: one preference serves both.
5. **Loaded when needed.** English is part of the bundle; another translation
   is loaded when its language is chosen, so the app does not carry every
   language. Until it arrives, the interface shows English.
6. **Plurals, dates and numbers by the platform.** Plural forms use i18next's
   plural keys, which follow `Intl.PluralRules`, so each language has the
   forms its rules need (`_one`, `_few`, `_many`, `_other` …). Dates, times,
   numbers, sizes, durations and costs are formatted by `Intl` in the
   interface language, never by hand or in a fixed locale.
7. **Right to left.** The document's `lang` and `dir` follow the interface
   language. The styles use logical properties (`margin-inline-start`,
   `inset-inline-end`, `text-align: start` …), never physical left and
   right, so the layout mirrors by itself, and icons that point a direction,
   such as back and forward, mirror with it. Text the user or the assistant
   writes takes its own direction (`dir="auto"`), whatever the interface's.
8. **Outside the page.** The service worker shows notifications (ADR-0101)
   in the interface language: the app tells it the language whenever it
   changes, and it keeps the notification strings of every language, a few
   per language. The web app's manifest carries only the product's name, which
   is not translated.

This amends ADR-0019 on the languages shipped, and settles the interface
language that ADR-0103 left for later.

## Consequences

- A household in any of the listed languages, about fifty, uses Sibillo in
  its own language from the start.
- Model-made translations have mistakes, some embarrassing; the mark tells
  the user, and a review fixes them for good.
- Each new or changed English string needs its Italian translation in the
  same change, and a run of the translation script before a release, or its
  model-made translations show English.
- The repository carries about fifty translation files, a few megabytes.
- Right-to-left layout must be checked in the app as screens change; a
  design test forbids physical properties, but not every mistake.

## Alternatives considered

- **English and Italian only, others from volunteers:** what ADR-0019 decided;
  most languages would never come.
- **Translating at runtime with the instance's model:** no files to keep,
  but every page load would wait on a model, cost each household money, send
  the interface to a provider and change from one load to the next.
- **A translation platform (Weblate, Crowdin):** good for reviewing by many
  people, and still possible later over the same files; a service to run or
  depend on before anyone has offered a review.
- **An interface language separate from the preferred language:** a second
  setting for the rare person who wants answers in one language and the
  interface in another.
- **Failing CI on any key a model-made translation lacks:** would make every
  change of a string need a model and a key; English for a while is better.
