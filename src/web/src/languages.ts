// The languages of the interface and of the assistant (I18N-002, I18N-003, ADR-0103, ADR-0135).
// Kept as BCP 47 tags in locales/languages.json, which the tests read too; their names come from the platform, so
// they need no translation resources (I18N-001).
import list from "./locales/languages.json";

/** Common languages: those the interface comes in, and those offered as the preferred language. */
export const LANGUAGES: readonly string[] = list.languages;

/** The languages whose translation a person has reviewed; the others' were made by a model. */
export const REVIEWED: readonly string[] = list.reviewed;

function named(tag: string, locale: string): string {
  try {
    const name = new Intl.DisplayNames([locale], { type: "language" }).of(tag) ?? tag;
    return name.charAt(0).toLocaleUpperCase(locale) + name.slice(1);
  } catch {
    return tag;
  }
}

/**
 * Each language, named in its own language and in the interface's, sorted by the latter; `stored` is kept even if
 * not listed. A language whose translation a model made says so with `automatic` (I18N-002).
 */
export function languageOptions(locale: string, stored: string | null | undefined, automatic: string): { tag: string; label: string }[] {
  const tags: string[] = [...LANGUAGES];
  if (stored && !tags.includes(stored)) tags.push(stored);
  return tags
    .map((tag) => {
      const own = named(tag, tag);
      const ours = named(tag, locale);
      const name = own === ours ? own : `${own} — ${ours}`;
      const label = LANGUAGES.includes(tag) && !REVIEWED.includes(tag) ? `${name} (${automatic})` : name;
      return { tag, sortBy: ours, label };
    })
    .sort((a, b) => a.sortBy.localeCompare(b.sortBy, locale))
    .map(({ tag, label }) => ({ tag, label }));
}
