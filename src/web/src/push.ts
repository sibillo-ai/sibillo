// This device's notifications, through the browser's Push API (UX-004, ADR-0101). The subscription
// belongs to the device session: the API keeps it, and the browser keeps its keys.

/** Whether this browser can receive notifications at all; on iPhones, only once the app is installed. */
export function pushSupported(): boolean {
  return typeof window !== "undefined" && "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

function toBytes(value: string): Uint8Array<ArrayBuffer> {
  const base64 = value.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(value.length / 4) * 4, "=");
  return Uint8Array.from(atob(base64), (char) => char.charCodeAt(0));
}

/** A subscription as the API takes it. */
export interface DeviceSubscription {
  endpoint: string;
  keys: { p256dh: string; auth: string };
}

/** Ask the browser for a subscription with the instance's key; `undefined` when the user says no. */
export async function subscribe(publicKey: string): Promise<DeviceSubscription | undefined> {
  const permission = await Notification.requestPermission();
  if (permission !== "granted") return undefined;
  const registration = await navigator.serviceWorker.ready;
  const existing = await registration.pushManager.getSubscription();
  const subscription =
    existing ?? (await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: toBytes(publicKey) }));
  const { endpoint, keys } = subscription.toJSON();
  if (endpoint === undefined || keys?.p256dh === undefined || keys.auth === undefined) {
    throw new Error("the browser gave a subscription without its keys");
  }
  return { endpoint, keys: { p256dh: keys.p256dh, auth: keys.auth } };
}

/** Forget the browser's subscription, once the API no longer has it. */
export async function unsubscribe(): Promise<void> {
  if (!pushSupported()) return;
  const registration = await navigator.serviceWorker.ready;
  const subscription = await registration.pushManager.getSubscription();
  await subscription?.unsubscribe();
}
