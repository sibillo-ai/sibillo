// Translates the web client's strings with a model, on a developer's machine, never on the instance (I18N-002,
// ADR-0135).
//
//   pnpm translate                 every model-made language: its missing and stale strings
//   pnpm translate de fr           only these languages; a reviewed one too, for a person to review afterwards
//   pnpm translate --prune         removes stale and unknown strings of every language, with no model
//   pnpm translate --record it     records the sources of a reviewed language a person translated
//
// The model is reached through an OpenAI-compatible endpoint: SIBILLO_TRANSLATE_API_KEY, and optionally
// SIBILLO_TRANSLATE_BASE_URL (OpenRouter by default) and SIBILLO_TRANSLATE_MODEL.
//
// So that a language names each concept of Sibillo the same way in every string, each language has a glossary,
// scripts/glossaries/<tag>.json, made by the model on its first translation and kept: a person may correct it, and
// the next run follows it.
//
// locales/sources.json records, for each language but English and each of its keys, the first 16 hexadecimal
// digits of the SHA-256 of the English text it was translated from; for a plural form, of the English texts of
// every plural form of its key, ordered by their keys and joined by a line feed. A text whose source differs is
// stale.
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";

const LOCALES = new URL("../src/locales/", import.meta.url);
const GLOSSARIES = new URL("./glossaries/", import.meta.url);
const PLURAL = /^(.+)_(zero|one|two|few|many|other)$/;
const PLACEHOLDER = /\{\{\s*([\w.]+)\s*(?:,[^}]*)?\}\}/g;
const BATCH = 120;
const PARALLEL = 8;

const read = (name) => JSON.parse(readFileSync(new URL(name, LOCALES), "utf8"));
const write = (name, data) => writeFileSync(new URL(name, LOCALES), `${JSON.stringify(data, null, 2)}\n`);

/** Every text of a resource by its key; the items of a list by their index. */
function flat(tree, prefix = "", into = new Map()) {
  for (const [name, value] of Object.entries(tree)) {
    if (typeof value === "string") into.set(`${prefix}${name}`, value);
    else flat(value, `${prefix}${name}.`, into);
  }
  return into;
}

const englishTree = read("en.json");
const english = flat(englishTree);
const { languages, reviewed } = read("languages.json");
const bases = new Set([...english.keys()].flatMap((key) => (PLURAL.exec(key)?.[2] === "other" ? [PLURAL.exec(key)[1]] : [])));
const formsOf = (base) => [...english.keys()].filter((key) => PLURAL.exec(key)?.[1] === base).sort();
const categories = (tag) => new Intl.PluralRules(tag).resolvedOptions().pluralCategories;
const placeholders = (text) => new Set([...text.matchAll(PLACEHOLDER)].map((match) => match[1]));

/** The English text a key translates, or `undefined` for a key English does not have. */
function englishOf(key) {
  const plural = PLURAL.exec(key);
  if (plural && bases.has(plural[1])) return formsOf(plural[1]).map((name) => english.get(name)).join("\n");
  return english.get(key);
}

const sourceOf = (text) => createHash("sha256").update(text, "utf8").digest("hex").slice(0, 16);

/** Whether a translated text keeps the English placeholders; a plural form may leave out the count. */
function keepsPlaceholders(key, text) {
  const plural = PLURAL.exec(key);
  const wanted = placeholders(plural && bases.has(plural[1]) ? english.get(`${plural[1]}_other`) : english.get(key));
  const found = placeholders(text);
  for (const name of found) if (!wanted.has(name)) return false;
  for (const name of wanted) if (!found.has(name) && !(plural && name === "count")) return false;
  return text.trim().length > 0;
}

/** Whether a key may be in the translation of `tag`. */
function known(tag, key) {
  const plural = PLURAL.exec(key);
  if (plural && bases.has(plural[1])) return categories(tag).includes(plural[2]);
  return english.has(key);
}

/** A translation's texts in the shape and order of the English resource, its plural forms in its own. */
function shape(tag, texts) {
  function build(node, prefix) {
    if (Array.isArray(node)) {
      const items = node.map((item, index) => build(item, `${prefix}${index}.`));
      // A list is the translation's whole, or English's.
      return items.every((item) => item !== undefined && Object.keys(item).length > 0) ? items : undefined;
    }
    const out = {};
    const done = new Set();
    for (const [name, value] of Object.entries(node)) {
      const key = `${prefix}${name}`;
      if (typeof value === "string") {
        const plural = PLURAL.exec(name);
        if (plural && bases.has(`${prefix}${plural[1]}`)) {
          if (done.has(plural[1])) continue;
          done.add(plural[1]);
          for (const form of categories(tag)) {
            const text = texts.get(`${prefix}${plural[1]}_${form}`);
            if (text !== undefined) out[`${plural[1]}_${form}`] = text;
          }
        } else if (texts.has(key)) out[name] = texts.get(key);
      } else {
        const child = build(value, `${key}.`);
        if (child !== undefined && (Array.isArray(child) || Object.keys(child).length > 0)) out[name] = child;
      }
    }
    return out;
  }
  return build(englishTree, "");
}

/** What `tag` lacks or has stale: plain keys, and plural keys with the forms its rules name. */
function needed(tag, texts, sources) {
  const plain = [];
  const plural = [];
  for (const key of english.keys()) {
    const match = PLURAL.exec(key);
    if (match && bases.has(match[1])) continue;
    if (!texts.has(key) || sources[key] !== sourceOf(english.get(key))) plain.push(key);
  }
  for (const base of bases) {
    const forms = categories(tag);
    if (forms.some((form) => !texts.has(`${base}_${form}`) || sources[`${base}_${form}`] !== sourceOf(englishOf(`${base}_other`)))) plural.push(base);
  }
  return { plain, plural };
}

/** Removes what `tag` has that is unknown, stale, unrecorded or of a form its rules do not name. */
function prune(tag, texts, sources) {
  for (const key of [...texts.keys()]) {
    const source = englishOf(key);
    if (!known(tag, key) || source === undefined || sources[key] !== sourceOf(source) || !keepsPlaceholders(key, texts.get(key))) {
      texts.delete(key);
    }
  }
  for (const key of Object.keys(sources)) if (!texts.has(key)) delete sources[key];
}

// The concepts each language names once and for all, with what they mean in Sibillo (specs/glossary.md).
const CONCEPTS = {
  household: "the family or group of people who share one Sibillo, and their home",
  "household admin": "a member of the household who manages its settings, models and members",
  "server's administrator": "the person who installed and runs the server Sibillo is on",
  conversation: "an exchange of messages with the assistant (also called a chat)",
  chat: "a conversation, in short",
  task: "a job the assistant runs on its own, on a schedule or when an event happens, starting a new conversation each time",
  "task list": "the checklist of steps the assistant plans and ticks off while it works in a conversation; its items are steps, not tasks",
  activity: "the page that lists every tool call the assistant made",
  skill: "a set of instructions and files that teaches the assistant how to do something",
  tool: "something the assistant can use, such as searching the web or running a command",
  "tool call": "one use of a tool by the assistant",
  approval: "the user's yes or no before the assistant makes a call",
  grant: "a call a task may make without asking, because nobody is there to approve it",
  workspace: "the folder of files of a conversation",
  sandbox: "the isolated computer where the assistant runs commands",
  memory: "what the assistant remembers about the user",
  model: "an AI language model",
  connection: "a link to a model provider or a model server",
  "local model": "a model that runs on the household's own hardware, so that messages never leave the home",
  "runs at home": "said of a model on the household's own hardware",
  remote: "said of a model at a provider, outside the home",
  trigger: "what starts a task: a schedule, a webhook or an event",
  service: "an external service the assistant reaches through MCP, such as Home Assistant",
  untrusted: "said of content that did not come from the user, which may try to mislead the assistant",
  "hands-free": "the voice mode in which the user talks and listens without touching the screen",
  "sign in": "to enter one's account",
  "system prompt": "the assistant's main instructions",
};

/** The glossary of `tag`: kept, or made by the model on the first translation. */
async function glossary(tag) {
  const file = new URL(`${tag}.json`, GLOSSARIES);
  if (existsSync(file)) return JSON.parse(readFileSync(file, "utf8"));
  const name = new Intl.DisplayNames(["en"], { type: "language" }).of(tag) ?? tag;
  const terms = await ask(
    tag,
    [
      `You prepare the glossary for translating the interface of Sibillo, a private AI assistant that a household runs on its own server, from English into ${name} (BCP 47: ${tag}).`,
      "For each concept, give the one term the interface will use everywhere: the word a well-made consumer app in this language would use, short and clear to people who are not technical. Never give the same term to two concepts. Keep a term in English only where speakers of the language commonly do.",
      'Answer with one JSON object, {"glossary": {"<concept>": "<term>", …}}, with exactly the concepts asked for.',
    ].join("\n"),
    { concepts: CONCEPTS },
    "glossary",
  );
  const kept = Object.fromEntries(Object.keys(CONCEPTS).filter((concept) => typeof terms[concept] === "string").map((concept) => [concept, terms[concept]]));
  mkdirSync(GLOSSARIES, { recursive: true });
  writeFileSync(file, `${JSON.stringify(kept, null, 2)}\n`);
  return kept;
}

function instructions(tag, terms) {
  const name = new Intl.DisplayNames(["en"], { type: "language" }).of(tag) ?? tag;
  return [
    `You translate the interface of Sibillo, a private AI assistant that a household runs on its own server, from English into ${name} (BCP 47: ${tag}).`,
    "The texts are buttons, labels, hints, notices and messages of a web app, read on phones and computers by people who are not technical.",
    "Rules:",
    "- Translate meaning, not words: short, natural, as a careful native speaker would write in a well-made app. Use the informal address the language uses in consumer apps, consistently.",
    "- Keep every placeholder such as {{count}} or {{name}} exactly as it is, untranslated; you may move it within the sentence.",
    "- Keep the product's name, Sibillo, and technical names (MCP, OpenRouter, Ollama, API, URL, passkey where the language has no common word) as they are.",
    "- Keep Markdown, punctuation that has a role (an ellipsis …, a colon before a value) and leading or trailing spaces or commas.",
    "- A key ending in _zero, _one, _two, _few, _many or _other is a plural form chosen by the number {{count}} with the language's plural rules. Write each form asked for. Keep {{count}} in every form, unless the form is used only for the number 1 in this language.",
    "- Quotes by authors (keys under quotes): use the established translation of the quote when there is one; keep the author's and the work's names as they are known in the language.",
    "- Address the user without assuming their gender where the language allows it.",
    "- Name each concept of this glossary with its term, everywhere, and never use a term for another concept:",
    ...Object.entries(terms).map(([concept, term]) => `  - ${concept} (${CONCEPTS[concept] ?? ""}): ${term}`),
    'Answer with one JSON object, {"translations": {"<key>": "<text>", …}}, with exactly the keys asked for, and nothing else.',
  ].join("\n");
}

async function complete(tag, items, terms) {
  return ask(tag, instructions(tag, terms), { translate: items }, "translations");
}

/** Asks the model with `system` and `user`, and returns the object it answers under `field`. */
async function ask(tag, system, user, field) {
  const base = process.env.SIBILLO_TRANSLATE_BASE_URL ?? "https://openrouter.ai/api/v1";
  const model = process.env.SIBILLO_TRANSLATE_MODEL ?? "deepseek/deepseek-v4.1-flash";
  const key = process.env.SIBILLO_TRANSLATE_API_KEY;
  if (!key) throw new Error("SIBILLO_TRANSLATE_API_KEY is not set");
  for (let attempt = 1; ; attempt += 1) {
    try {
      const response = await fetch(`${base.replace(/\/$/, "")}/chat/completions`, {
        method: "POST",
        headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
        body: JSON.stringify({
          model,
          temperature: 0.2,
          response_format: { type: "json_object" },
          messages: [
            { role: "system", content: system },
            { role: "user", content: JSON.stringify(user, null, 1) },
          ],
        }),
        signal: AbortSignal.timeout(300_000),
      });
      if (!response.ok) throw new Error(`${response.status} ${(await response.text()).slice(0, 200)}`);
      const content = (await response.json()).choices?.[0]?.message?.content ?? "";
      const json = content.slice(content.indexOf("{"), content.lastIndexOf("}") + 1);
      const answer = JSON.parse(json)[field];
      if (typeof answer !== "object" || answer === null) throw new Error(`no ${field} in the answer`);
      return answer;
    } catch (error) {
      if (attempt >= 4) throw error;
      console.warn(`${tag}: attempt ${attempt} failed (${error.message}); trying again`);
      await new Promise((resolve) => setTimeout(resolve, 2000 * attempt));
    }
  }
}

async function translate(tag, texts, sources) {
  const { plain, plural } = needed(tag, texts, sources);
  const items = [
    ...plain.map((key) => ({ key, english: english.get(key) })),
    ...plural.map((base) => ({
      key: base,
      english: Object.fromEntries(formsOf(base).map((name) => [PLURAL.exec(name)[2], english.get(name)])),
      write_forms: categories(tag).map((form) => `${base}_${form}`),
    })),
  ];
  if (items.length === 0) return;
  const terms = await glossary(tag);
  let added = 0;
  let refused = 0;
  for (let start = 0; start < items.length; start += BATCH) {
    const batch = items.slice(start, start + BATCH);
    const asked = new Set(batch.flatMap((item) => item.write_forms ?? [item.key]));
    const answer = await complete(tag, batch, terms);
    for (const [key, text] of Object.entries(answer)) {
      if (!asked.has(key) || typeof text !== "string" || !known(tag, key) || !keepsPlaceholders(key, text)) {
        refused += 1;
        continue;
      }
      texts.set(key, text);
      sources[key] = sourceOf(englishOf(key));
      added += 1;
    }
    console.log(`${tag}: ${Math.min(start + BATCH, items.length)}/${items.length} asked, ${added} written, ${refused} refused`);
  }
}

async function main() {
  const args = process.argv.slice(2);
  const mode = args.includes("--prune") ? "prune" : args.includes("--record") ? "record" : "translate";
  const named = args.filter((arg) => !arg.startsWith("--"));
  for (const tag of named) if (!languages.includes(tag) || tag === "en") throw new Error(`${tag} is not a language to translate`);
  if (mode === "record" && named.length === 0) throw new Error("--record needs the languages to record");
  const tags = named.length > 0 ? named : languages.filter((tag) => tag !== "en" && (mode !== "translate" || !reviewed.includes(tag)));
  const sources = read("sources.json");
  const queue = [...tags];
  async function worker() {
    for (let tag = queue.shift(); tag !== undefined; tag = queue.shift()) {
      let texts;
      try {
        texts = flat(read(`${tag}.json`));
      } catch {
        texts = new Map();
      }
      // A copy, recorded only with the translation it describes, so that an interrupted run leaves both alike.
      const own = { ...(sources[tag] ?? {}) };
      if (mode === "record") {
        for (const key of texts.keys()) {
          const source = englishOf(key);
          if (source !== undefined) own[key] = sourceOf(source);
        }
      }
      prune(tag, texts, own);
      if (mode === "translate") {
        if (reviewed.includes(tag)) console.warn(`${tag} is reviewed: a person must review what the model writes`);
        try {
          await translate(tag, texts, own);
        } catch (error) {
          console.error(`${tag}: ${error.message}; what was translated is kept`);
        }
      }
      write(`${tag}.json`, shape(tag, texts));
      sources[tag] = own;
      // After each language, so that an interrupted run keeps what it paid for.
      writeSources(sources);
    }
  }
  await Promise.all(Array.from({ length: Math.min(PARALLEL, tags.length) }, worker));
  writeSources(sources);
}

function writeSources(sources) {
  const ordered = Object.fromEntries(
    languages
      .filter((tag) => tag !== "en" && sources[tag])
      .map((tag) => [tag, Object.fromEntries(Object.entries(sources[tag]).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)))]),
  );
  write("sources.json", ordered);
}

await main();
