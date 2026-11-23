# Translating the interface

The web client comes in every language of the list a user picks their
preferred language from, about fifty
([I18N-002](../../specs/requirements/i18n.md),
[ADR-0135](../../specs/adr/0135-the-interface-in-every-language.md)).
English and Italian are reviewed by a person and always complete; the others
are translated by a model, may lack strings, which then show in English, and
are marked as translated automatically where the user chooses a language.

## Where the translations are

| File | What it holds |
|---|---|
| `src/web/src/locales/en.json` | The source: every string of the app |
| `src/web/src/locales/<tag>.json` | One translation per BCP 47 tag |
| `src/web/src/locales/languages.json` | The languages, and those a person reviewed |
| `src/web/src/locales/sources.json` | For each translated string, the English text it came from, as a short hash |
| `src/web/scripts/glossaries/<tag>.json` | How each language names Sibillo's concepts: task, skill, household … |

A string that shows a count has plural forms, `<key>_one` and `<key>_other` in
English; each language has the forms its plural rules name, such as `_few`
and `_many`. Code passes the count and never compares it to 1.

## When you add or change an English string

1. Change `en.json`, and the Italian text in `it.json`, in the same change.
2. Record the Italian sources: `pnpm translate --record it` in `src/web`.
3. Either translate the other languages:

   ```bash
   cd src/web
   SIBILLO_TRANSLATE_API_KEY=… pnpm translate
   ```

   or, without a model key, remove what became stale, which shows English
   until the next translation:

   ```bash
   cd src/web
   pnpm translate --prune
   ```

CI fails on a translation of an English text that has changed since, on a
key English no longer has, on placeholders (`{{name}}`) that differ from
English, and on a reviewed language that lacks a string
(`tests/design/test_web_languages.py`).

The script reaches any OpenAI-compatible endpoint:
`SIBILLO_TRANSLATE_BASE_URL` (OpenRouter by default) and
`SIBILLO_TRANSLATE_MODEL`. It runs on your machine only: Sibillo never
translates at runtime. `pnpm translate de fr` translates only those
languages.

## Reviewing a language

A model's translation has mistakes. To review one:

1. Read the glossary of the language and correct it first: the next run
   follows it.
2. Read the translation next to `en.json` and correct what is wrong; fill
   what is missing.
3. Record its sources with `pnpm translate --record <tag>`, and add the tag to
   `reviewed` in `languages.json`. From then on CI requires the language to
   be complete, and every change of an English string needs its translation
   in the same change.

## Adding a language

Add its tag to `languages` in `languages.json` and run `pnpm translate <tag>`.
A language written from right to left also needs its tag in
`RIGHT_TO_LEFT` in `src/web/src/i18n.ts`. Styles use logical properties
(`ms-2`, `ps-4`, `text-start`), never left and right, so the layout mirrors
by itself.
