# ADR-0103: The preferred language

- **Status:** Proposed
- **Date:** 2026-11-18
- **Deciders:** @tapionx
- **Related:** ADR-0019, ADR-0081, ADR-0092, ADR-0102, I18N-001, I18N-002, I18N-003, CNV-014, EVL-001

## Context

The built-in base instructions tell the assistant to answer in the language
the user writes in (CNV-014). That is right for most messages, and wrong for
those that have no language of their own: a link shared from another app
(ADR-0102), a pasted equation, a file sent without a word. The assistant then
guesses, often in English, the language of most of what it was trained on and
of most pages it reads. An Italian household wants Italian there.

A user may replace the base instructions (CNV-014), and may write "answer in
Italian" in them or in the additional instructions; but a preference written
in prose is lost when the user restores the built-in instructions, applies to
every message even when the user writes in another language, and cannot be
read by the client, which will want the same preference for its own language
once there are translations (I18N-002).

## Decision

1. **A user default.** The preferred language is one of the user defaults
   (ADR-0081), in `user_settings.language`, and in `language` of
   `/me/settings`: a BCP 47 language tag, `null` for none. Only a language,
   an optional script and an optional region are accepted, as in `it`,
   `pt-BR` or `zh-Hant-TW`, by a pattern that the API and a database
   constraint both check: the tag reaches the model, so it carries nothing
   else. Leaving it out of a request sets none, as for `disabled_servers`.
2. **Read at each run.** Like instructions without a conversation's own
   (ADR-0081), the preferred language is read when a run starts, so it
   reaches every conversation from its next run; conversations do not copy
   it, and it has no setting per conversation.
3. **Its own instruction.** When the user has a preferred language, the run's
   instructions say, right after the base instructions:
   "The user's preferred language is the one with the BCP 47 tag `<tag>`.
   Answer in it, unless the user writes in another language or asks for
   one; then answer in that one." It is not part of the base instructions,
   so it stays when the user replaces them, as the working instructions do.
   The tag is named, not translated into a name, so the server needs no
   table of language names: models read tags well, and the eval suite checks
   that they do.
4. **The client names languages with the platform.** The assistant settings
   offer the preferred language as a choice of "none", said as answering in
   the language of the user's messages, and of a list of common languages,
   kept by the client as tags. Each is named in its own language and in the
   interface's, by `Intl.DisplayNames`, so the names need no translation
   resources (I18N-001). A stored tag that is not in the list is offered too.
5. **Checked by evals.** Two scenarios of the eval suite (ADR-0092) set an
   Italian preference: in one, the user sends an equation with no words, and
   the answer must be in Italian; in the other, the user writes in English,
   and the answer must be in English. The language of an answer is told by
   counting common words of each language: enough for answers of a few
   sentences, and without a model as a judge. The scenarios set the user
   defaults before the conversation starts.

## Consequences

- Messages without a language of their own, shared links above all, are
  answered in the household's language.
- The same preference can choose the interface's language when there are
  translations (I18N-002), and the language of speech recognition (UX-005);
  neither uses it yet.
- Titles and compaction summaries keep following the conversation's
  language; they do not use the preference.
- Telling a language by its common words fails for very short answers and
  for languages that share many words; the scenarios ask for answers long
  enough, in two languages that share few.

## Alternatives considered

- **The browser's language as the preference:** sent with every request as
  `Accept-Language`, but it is the device's, often English on a phone set up
  that way, and differs between a user's devices.
- **A free text, such as "Italian":** clearer to a model, and an open door
  for instructions in a field the user does not read as a prompt; a tag is
  checked by a pattern.
- **A table of language names on the server:** a dependency, or a list to
  keep, for what models already understand.
- **A preference per conversation:** the user can already ask for another
  language in any message; one more setting per conversation adds little.
