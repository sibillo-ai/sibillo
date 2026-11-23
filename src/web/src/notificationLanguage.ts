// The interface language, kept where the service worker finds it when a push wakes it, so that notifications are
// in that language (I18N-004, ADR-0135). Apart from notifications.ts, which holds the notification strings of every
// translation: the app imports only this.

const STORE = "sibillo-interface";
const KEY = "/interface-language";

/** Keeps the interface language for the service worker's notifications. */
export async function rememberNotificationLanguage(language: string): Promise<void> {
  try {
    const cache = await caches.open(STORE);
    await cache.put(KEY, new Response(language, { headers: { "Content-Type": "text/plain" } }));
  } catch {
    // No cache storage, as in a private window of some browsers: notifications stay in English.
  }
}

/** The interface language the app last kept, or English. */
export async function notificationLanguage(): Promise<string> {
  try {
    const kept = await (await caches.open(STORE)).match(KEY);
    return kept ? (await kept.text()).trim() || "en" : "en";
  } catch {
    return "en";
  }
}
