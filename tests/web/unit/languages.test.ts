// The interface in every language: which language it shows, its direction, its plural forms, English for what a
// translation lacks, and notifications in the interface language (I18N-002, I18N-004, I18N-005, I18N-006, ADR-0135).
import { readFileSync, readdirSync } from "node:fs";

import { describe, expect, it } from "vitest";

import i18n, { interfaceLanguage, textDirection } from "../../../src/web/src/i18n";
import { notificationText } from "../../../src/web/src/notifications";

type Tree = { [key: string]: string | Tree | Tree[] };

const LOCALES = new URL("../../../src/web/src/locales/", import.meta.url);
const read = <T>(name: string): T => JSON.parse(readFileSync(new URL(name, LOCALES), "utf8")) as T;
const { languages, reviewed } = read<{ languages: string[]; reviewed: string[] }>("languages.json");
const PLURAL = /^(.+)_(zero|one|two|few|many|other)$/;

function flat(tree: Tree | Tree[], prefix = ""): Map<string, string> {
  const keys = new Map<string, string>();
  for (const [name, value] of Object.entries(tree)) {
    if (typeof value === "string") keys.set(`${prefix}${name}`, value);
    else for (const [key, text] of flat(value, `${prefix}${name}.`)) keys.set(key, text);
  }
  return keys;
}

const english = flat(read<Tree>("en.json"));
const bases = new Set([...english.keys()].flatMap((key) => (PLURAL.exec(key)?.[2] === "other" ? [PLURAL.exec(key)![1]!] : [])));

describe("interfaceLanguage", () => {
  it("is the preferred language when there is a translation for it", () => {
    expect(interfaceLanguage("it", ["en-US"])).toBe("it");
    expect(interfaceLanguage("ar", ["it-IT"])).toBe("ar");
  });

  it("matches tags by lookup", () => {
    expect(interfaceLanguage("pt-BR", [])).toBe("pt-BR");
    expect(interfaceLanguage("pt-PT", [])).toBe("pt");
    expect(interfaceLanguage("zh-Hant-TW", [])).toBe("zh-Hant");
    expect(interfaceLanguage("de-CH", ["it"])).toBe("de");
    expect(interfaceLanguage("PT-br", [])).toBe("pt-BR");
  });

  it("is otherwise the first of the browser's languages there is a translation for", () => {
    expect(interfaceLanguage(null, ["it-IT", "en-US"])).toBe("it");
    expect(interfaceLanguage(undefined, ["tlh", "fr-CA", "de"])).toBe("fr");
    expect(interfaceLanguage("tlh", ["es-MX"])).toBe("es");
  });

  it("is otherwise English", () => {
    expect(interfaceLanguage(null, [])).toBe("en");
    expect(interfaceLanguage("tlh", ["tlh-Latn"])).toBe("en");
  });

  it("is always a language of the list", () => {
    for (const tag of languages) expect(interfaceLanguage(tag, [])).toBe(tag);
  });
});

describe("textDirection", () => {
  it("is right to left for Arabic, Hebrew, Persian and Urdu", () => {
    for (const tag of ["ar", "he", "fa", "ur"]) expect(textDirection(tag)).toBe("rtl");
  });

  it("is left to right for the others", () => {
    for (const tag of languages.filter((tag) => !["ar", "he", "fa", "ur"].includes(tag))) expect(textDirection(tag)).toBe("ltr");
  });
});

describe("plural forms", () => {
  const categories = (tag: string) => new Intl.PluralRules(tag).resolvedOptions().pluralCategories as string[];

  it("are every form a reviewed translation's rules name", () => {
    const missing: string[] = [];
    for (const tag of reviewed) {
      const keys = flat(read<Tree>(`${tag}.json`));
      for (const base of bases) for (const form of categories(tag)) if (!keys.has(`${base}_${form}`)) missing.push(`${tag}: ${base}_${form}`);
    }
    expect(missing).toEqual([]);
  });

  it("are only forms a translation's rules name", () => {
    const unknown: string[] = [];
    for (const tag of languages) {
      for (const key of flat(read<Tree>(`${tag}.json`)).keys()) {
        const match = PLURAL.exec(key);
        if (match && bases.has(match[1]!) && !categories(tag).includes(match[2]!)) unknown.push(`${tag}: ${key}`);
      }
    }
    expect(unknown).toEqual([]);
  });

  it("are chosen by the count", () => {
    const base = [...bases][0];
    expect(base).toBeDefined();
    const t = i18n.getFixedT("en");
    expect(t(base!, { count: 1 })).toBe(t(`${base!}_one`, { count: 1 }));
    expect(t(base!, { count: 2 })).toBe(t(`${base!}_other`, { count: 2 }));
  });
});

describe("a translation that lacks a string", () => {
  it("shows it in English", () => {
    i18n.addResourceBundle("de", "translation", { signIn: { title: "Willkommen zurück" } }, true, true);
    const t = i18n.getFixedT("de");
    expect(t("signIn.title")).toBe("Willkommen zurück");
    expect(t("signIn.submit")).toBe(english.get("signIn.submit"));
  });
});

describe("the translations' files", () => {
  it("are one per language of the list", () => {
    const files = readdirSync(LOCALES).filter((name) => name.endsWith(".json") && !["languages.json", "sources.json"].includes(name));
    expect(files.map((name) => name.replace(/\.json$/, "")).sort()).toEqual([...languages].sort());
  });
});

describe("notificationText", () => {
  const kinds = ["run_finished", "run_failed", "approval_pending", "question_pending"] as const;

  it("is in the interface language", () => {
    const italian = read<{ notifications: { kinds: Record<string, { title: string; body: string }> } }>("it.json");
    for (const kind of kinds) expect(notificationText(kind, "it")).toEqual(italian.notifications.kinds[kind]);
  });

  it("is in English for a language without a translation", () => {
    for (const kind of kinds) {
      expect(notificationText(kind, "tlh")).toEqual({
        title: english.get(`notifications.kinds.${kind}.title`),
        body: english.get(`notifications.kinds.${kind}.body`),
      });
    }
  });
});
