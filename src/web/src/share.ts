// Shares from other apps (UX-006, ADR-0102): the service worker keeps the latest one on the device, and the
// app takes it once, as a new chat. This module runs in both, so it uses nothing but IndexedDB.

/** What another app shared: its fields as the share sheet filled them, and when it arrived. */
export interface Share {
  title: string;
  text: string;
  url: string;
  files: File[];
  received: number;
}

/** How long a share waits on the device to be offered, as while the user signs in. */
export const SHARE_LIFETIME_MS = 60 * 60 * 1000;

const DATABASE = "sibillo-share";
const STORE = "shares";
// Only the latest share is kept: a new one replaces it.
const KEY = "latest";

/** The message box's text: the title, the text and the link on their own paragraphs, without repeats. */
export function messageOf(share: Pick<Share, "title" | "text" | "url">): string {
  const parts = [share.title, share.text, share.url].map((part) => part.trim()).filter((part) => part !== "");
  const kept = parts.filter((part, index) => !parts.some((other, at) => at !== index && other !== part && other.includes(part)));
  return kept.filter((part, index) => kept.indexOf(part) === index).join("\n\n");
}

/** Whether a share received at `received` is still offered at `now`. */
export function isFresh(received: number, now: number): boolean {
  return received <= now && now - received <= SHARE_LIFETIME_MS;
}

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("IndexedDB did not open"));
  });
}

async function transact<T>(mode: IDBTransactionMode, work: (store: IDBObjectStore) => IDBRequest<T> | undefined): Promise<T | undefined> {
  const database = await open();
  try {
    return await new Promise<T | undefined>((resolve, reject) => {
      const transaction = database.transaction(STORE, mode);
      const request = work(transaction.objectStore(STORE));
      transaction.oncomplete = () => resolve(request?.result);
      transaction.onerror = () => reject(transaction.error ?? new Error("IndexedDB failed"));
      transaction.onabort = () => reject(transaction.error ?? new Error("IndexedDB aborted"));
    });
  } finally {
    database.close();
  }
}

/** Keeps `share` on the device, in place of any other. */
export async function keepShare(share: Share): Promise<void> {
  await transact("readwrite", (store) => store.put(share, KEY));
}

/** Takes the kept share, deleting it from the device; one older than its lifetime is deleted unread. */
export async function takeShare(now: number = Date.now()): Promise<Share | undefined> {
  const share = await transact<unknown>("readwrite", (store) => {
    const request = store.get(KEY);
    store.delete(KEY);
    return request;
  });
  if (!isShare(share) || !isFresh(share.received, now)) return undefined;
  return share;
}

function isShare(value: unknown): value is Share {
  if (typeof value !== "object" || value === null) return false;
  const share = value as Record<string, unknown>;
  return (
    typeof share.title === "string" &&
    typeof share.text === "string" &&
    typeof share.url === "string" &&
    typeof share.received === "number" &&
    Array.isArray(share.files) &&
    share.files.every((file) => file instanceof File)
  );
}

/** The share a form posted to `/share` carries; an empty file field is no file. */
export function shareOf(form: FormData, received: number): Share {
  const field = (name: string) => {
    const value = form.get(name);
    return typeof value === "string" ? value : "";
  };
  const files = form.getAll("files").filter((value): value is File => value instanceof File && value.name !== "");
  return { title: field("title"), text: field("text"), url: field("url"), files, received };
}
