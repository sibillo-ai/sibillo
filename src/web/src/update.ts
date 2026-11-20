// A new version of the app takes over (UX-040, ADR-0112): the app looks for one when it comes back into view,
// when it goes out of view and every hour, and loads it as soon as that loses nothing the user typed.

const HOUR_MS = 60 * 60 * 1000;
// The fields where the user types text.
const TEXT_FIELDS = "textarea, input:not([type]), input[type=text], input[type=search], input[type=url], input[type=email], input[type=password]";

let watching = false;

/** Fields the user typed in: their text would be lost by loading the page again. */
const typed = new WeakSet<EventTarget>();

function holdsTypedText(): boolean {
  for (const field of document.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>(TEXT_FIELDS)) {
    if (typed.has(field) && field.value.trim() !== "") return true;
  }
  return false;
}

/**
 * Watches for a new version of the app. `onReady` is called when one has taken over a page that cannot load it
 * yet, so that the app says it is ready; the page loads it the next time it goes out of view with nothing typed.
 */
export function watchForUpdates(onReady: () => void): void {
  if (watching || !("serviceWorker" in navigator)) return;
  watching = true;
  const workers = navigator.serviceWorker;
  // The first worker of a page, on its first visit, is not a new version.
  let controlled = workers.controller !== null;
  let waiting = false;

  /** Loads the new version if it is waiting and nothing would be lost; whether it did. */
  function load(): boolean {
    if (!waiting || document.visibilityState !== "hidden" || holdsTypedText()) return false;
    window.location.reload();
    return true;
  }

  function check() {
    // The browser fetches the service worker past its HTTP cache for this check.
    void workers
      .getRegistration()
      .then((registration) => registration?.update())
      .catch(() => undefined);
  }

  document.addEventListener("input", (event) => event.target && typed.add(event.target), true);
  workers.addEventListener("controllerchange", () => {
    if (!controlled) {
      controlled = true;
      return;
    }
    waiting = true;
    if (!load()) onReady();
  });
  document.addEventListener("visibilitychange", () => {
    if (!load()) check();
  });
  window.setInterval(check, HOUR_MS);
}
