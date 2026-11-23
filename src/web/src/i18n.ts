// Every user-facing string comes from translation resources (I18N-001), in every language of the list (I18N-002),
// shown in the interface language (I18N-004), with its direction (I18N-005) and its plural forms (I18N-006);
// see ADR-0135.
import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import { LANGUAGES } from "./languages";
import en from "./locales/en.json";
import { rememberNotificationLanguage } from "./notificationLanguage";

type Resource = Record<string, unknown>;

// English is part of the bundle; another translation is loaded when its language is chosen. The app never imports
// notifications.ts, which takes the notification strings of every translation for the service worker: otherwise
// the bundle would hold every translation whole.
const TRANSLATIONS = import.meta.glob<Resource>(["./locales/*.json", "!./locales/en.json", "!./locales/languages.json", "!./locales/sources.json"], {
  import: "default",
});
const RIGHT_TO_LEFT = new Set(["ar", "he", "fa", "ur"]);

void i18n.use(initReactI18next).init({
  resources: { en: { translation: en } },
  lng: "en",
  fallbackLng: "en",
  partialBundledLanguages: true,
  interpolation: { escapeValue: false },
});

/** The language of the list a tag names, matched by lookup (RFC 4647): `pt-PT` is `pt`, `zh-Hant-TW` is `zh-Hant`. */
function lookup(tag: string): string | undefined {
  let canonical: string;
  try {
    canonical = Intl.getCanonicalLocales(tag)[0] ?? "";
  } catch {
    return undefined;
  }
  const parts = canonical.split("-");
  while (parts.length > 0) {
    const candidate = parts.join("-").toLowerCase();
    const found = LANGUAGES.find((language) => language.toLowerCase() === candidate);
    if (found) return found;
    parts.pop();
    // A lone single-letter subtag, such as the `x` of a private use, is not a range of its own.
    while (parts.length > 0 && parts[parts.length - 1]!.length === 1) parts.pop();
  }
  return undefined;
}

/** The interface language: the preferred language, else the first of the browser's, else English (I18N-004). */
export function interfaceLanguage(preferred: string | null | undefined, browser: readonly string[]): string {
  for (const tag of [preferred, ...browser]) {
    const found = tag ? lookup(tag) : undefined;
    if (found) return found;
  }
  return "en";
}

/** The direction a language is written in (I18N-005). */
export function textDirection(tag: string): "ltr" | "rtl" {
  return RIGHT_TO_LEFT.has(tag.split("-")[0]!.toLowerCase()) ? "rtl" : "ltr";
}

/** The browser's languages, most preferred first. */
export function browserLanguages(): readonly string[] {
  return navigator.languages.length > 0 ? navigator.languages : [navigator.language];
}

let wanted = "en";

/**
 * Shows the interface in `language`. The page takes its language and direction at once, so that they are right from
 * the first paint and for assistive technologies; its strings follow once its translation is loaded.
 */
export async function showInterfaceIn(language: string): Promise<void> {
  wanted = language;
  document.documentElement.lang = language;
  document.documentElement.dir = textDirection(language);
  if (language !== "en" && !i18n.hasResourceBundle(language, "translation")) {
    const load = TRANSLATIONS[`./locales/${language}.json`];
    if (load) {
      try {
        i18n.addResourceBundle(language, "translation", await load(), true, false);
      } catch {
        // Not reachable now, as when a new version replaced this one's files: English until the next try.
      }
    }
  }
  // A later choice won while this one was loading.
  if (wanted !== language) return;
  await i18n.changeLanguage(language);
  void rememberNotificationLanguage(language);
}

// Before anything else, the browser's languages decide (I18N-004); the user's preferred language follows once known.
void showInterfaceIn(interfaceLanguage(null, browserLanguages()));

export default i18n;
