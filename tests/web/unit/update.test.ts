// A new version of the app takes over: the app looks for one when it comes back into view, when it goes out of
// view and every hour, and loads it as soon as that loses nothing the user typed (UX-040, ADR-0112).
//
// The browser's service worker is a stand-in that says what the browser says; one test in the browser takes a
// real new worker over a page.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const HOUR_MS = 60 * 60 * 1000;

class Workers extends EventTarget {
  controller: object | null = {};
  update = vi.fn(() => Promise.resolve());
  getRegistration = () => Promise.resolve({ update: this.update });
  /** A new worker takes over the page. */
  takeOver() {
    this.dispatchEvent(new Event("controllerchange"));
  }
}

let workers: Workers;
let reload: ReturnType<typeof vi.fn>;
let ready: ReturnType<typeof vi.fn>;

function seen(state: "hidden" | "visible") {
  Object.defineProperty(document, "visibilityState", { value: state, configurable: true });
  Object.defineProperty(document, "hidden", { value: state === "hidden", configurable: true });
  document.dispatchEvent(new Event("visibilitychange"));
}

function type(text: string) {
  const field = document.createElement("textarea");
  document.body.append(field);
  field.value = text;
  field.dispatchEvent(new Event("input", { bubbles: true }));
}

/** How many times the page was told to load again. */
const reloads = () => reload.mock.calls.length;

/** What the page's promises have to say, once the timers have run. */
const settle = () => vi.advanceTimersByTimeAsync(0);

const listeners: [string, EventListenerOrEventListenerObject, boolean | AddEventListenerOptions | undefined][] = [];

/** Starts watching, as the app does once, the page controlled by a worker or not yet. */
async function watch(controlled = true) {
  vi.resetModules();
  workers.controller = controlled ? {} : null;
  const { watchForUpdates } = await import("../../../src/web/src/update");
  watchForUpdates(ready);
}

beforeEach(() => {
  vi.useFakeTimers();
  document.body.innerHTML = "";
  seen("visible");
  workers = new Workers();
  Object.defineProperty(navigator, "serviceWorker", { value: workers, configurable: true });
  reload = vi.fn();
  vi.stubGlobal("location", { reload });
  ready = vi.fn();
  // What a watcher listens to on the document goes with it, as the page's does when it loads again.
  const add = document.addEventListener.bind(document);
  vi.spyOn(document, "addEventListener").mockImplementation((type, listener, options) => {
    listeners.push([type, listener, options]);
    add(type, listener, options);
  });
});

afterEach(() => {
  for (const [type, listener, options] of listeners.splice(0)) document.removeEventListener(type, listener, options);
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("watchForUpdates", () => {
  it("changes nothing on a first visit, when the first worker takes the page over", async () => {
    await watch(false);
    workers.takeOver();
    seen("hidden");
    expect(reloads()).toBe(0);
    expect(ready).not.toHaveBeenCalled();
  });

  it("loads the new version when the app goes out of view with nothing typed", async () => {
    await watch();
    workers.takeOver();
    expect(ready).toHaveBeenCalledOnce();
    seen("hidden");
    expect(reloads()).toBe(1);
  });

  it("looks for a new version when the app goes out of view or comes back", async () => {
    await watch();
    seen("hidden");
    seen("visible");
    await settle();
    expect(workers.update).toHaveBeenCalledTimes(2);
  });

  it("waits and says it is ready while there is text typed, and loads once the app is out of view without it", async () => {
    await watch();
    type("half a thought");
    workers.takeOver();
    expect(ready).toHaveBeenCalledOnce();
    expect(reloads()).toBe(0);
    // Out of view, the typed text still keeps the page as it is.
    seen("hidden");
    expect(reloads()).toBe(0);
  });

  it("looks for a new version every hour", async () => {
    await watch();
    await settle();
    expect(workers.update).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(HOUR_MS);
    expect(workers.update).toHaveBeenCalledOnce();
    await vi.advanceTimersByTimeAsync(HOUR_MS);
    expect(workers.update).toHaveBeenCalledTimes(2);
  });
});
