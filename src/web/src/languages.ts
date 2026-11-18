// The languages a user may prefer the assistant to answer in (I18N-003, ADR-0103).
// Kept as BCP 47 tags; their names come from the platform, so they need no translation resources (I18N-001).

/** Common languages, offered as the preferred language. */
export const LANGUAGES = [
  "ar", "bg", "bn", "ca", "cs", "cy", "da", "de", "el", "en", "es", "et", "eu", "fa", "fi", "fil", "fr", "ga", "gl",
  "he", "hi", "hr", "hu", "id", "is", "it", "ja", "ko", "lt", "lv", "ms", "mt", "nb", "nl", "pl", "pt", "pt-BR", "ro",
  "ru", "sk", "sl", "sq", "sr", "sv", "sw", "ta", "th", "tr", "uk", "ur", "vi", "zh-Hans", "zh-Hant",
] as const;

function named(tag: string, locale: string): string {
  try {
    const name = new Intl.DisplayNames([locale], { type: "language" }).of(tag) ?? tag;
    return name.charAt(0).toLocaleUpperCase(locale) + name.slice(1);
  } catch {
    return tag;
  }
}

/** Each language, named in its own language and in the interface's, sorted by the latter; `stored` is kept even if not listed. */
export function languageOptions(locale: string, stored?: string | null): { tag: string; label: string }[] {
  const tags: string[] = [...LANGUAGES];
  if (stored && !tags.includes(stored)) tags.push(stored);
  return tags
    .map((tag) => {
      const own = named(tag, tag);
      const ours = named(tag, locale);
      return { tag, sortBy: ours, label: own === ours ? own : `${own} — ${ours}` };
    })
    .sort((a, b) => a.sortBy.localeCompare(b.sortBy, locale))
    .map(({ tag, label }) => ({ tag, label }));
}
