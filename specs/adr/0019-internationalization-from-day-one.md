# ADR-0019: Internationalization from day one

- **Status:** Accepted
- **Date:** 2026-10-29
- **Deciders:** @tapionx
- **Related:** ADR-0005, I18N-001, I18N-002, I18N-003

## Context

The first users are Italian; the project targets everyone. Retrofitting
internationalization into an application with hard-coded strings is long and
error-prone.

## Decision

We will externalize every user-facing string from the first line of client
and server code, ship English and Italian from the first release, and let
the assistant answer in each user's preferred language.

Amended by ADR-0135: the interface comes in every language of the list of
ADR-0103, English and Italian reviewed by a person, the others translated
by a model.

## Consequences

- Slightly more ceremony when adding UI text.
- Community translations become possible without code changes.

## Alternatives considered

- **English only, i18n later:** the retrofit cost grows with every screen.
