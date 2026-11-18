// The app's service worker (UX-001, ADR-0067): it caches only the app's own files and never the API, shows
// notifications, which carry no content, with a fixed text for each kind (UX-004, ADR-0101), and receives
// shares from other apps (UX-006, ADR-0102).
import { cleanupOutdatedCaches, createHandlerBoundToURL, precacheAndRoute } from "workbox-precaching";
import { NavigationRoute, registerRoute } from "workbox-routing";

import { notifications as strings } from "../locales/en.json";
import { notificationOf } from "../notifications";
import { keepShare, shareOf } from "../share";

declare const self: ServiceWorkerGlobalScope & { __WB_MANIFEST: Array<string | { url: string; revision: string | null }> };

// A share from another app: kept on the device, and offered by the app as a new chat. Only a navigation, as
// the share sheet makes, so that no script leaves a share behind without opening the app. Nothing is sent.
self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "POST" || request.mode !== "navigate" || url.origin !== self.location.origin || url.pathname !== "/share") return;
  event.respondWith(
    (async () => {
      try {
        await keepShare(shareOf(await request.formData(), Date.now()));
      } catch {
        // Too large to keep, or unreadable: the app says that nothing arrived.
      }
      return Response.redirect(new URL("/?shared=1", self.location.origin).href, 303);
    })(),
  );
});

precacheAndRoute(self.__WB_MANIFEST);
cleanupOutdatedCaches();
registerRoute(new NavigationRoute(createHandlerBoundToURL("/index.html"), { denylist: [/^\/v1\//] }));

// A new version takes over at once, as `registerType: "autoUpdate"` expects.
self.addEventListener("install", () => {
  void self.skipWaiting();
});
self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("push", (event) => {
  let payload: unknown;
  try {
    payload = event.data?.json();
  } catch {
    return;
  }
  const notification = notificationOf(payload);
  if (notification === undefined) return;
  const text = strings.kinds[notification.kind];
  event.waitUntil(
    self.registration.showNotification(text.title, {
      body: text.body,
      tag: notification.tag,
      icon: "/icon-192.png",
      badge: "/icon-192.png",
      data: { url: notification.url },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const data: unknown = event.notification.data;
  const path = typeof data === "object" && data !== null ? (data as { url?: unknown }).url : undefined;
  // Only a path of the app, as the service worker itself wrote it.
  if (typeof path !== "string" || !path.startsWith("/c/")) return;
  const url = new URL(path, self.location.origin).href;
  event.waitUntil(
    (async () => {
      const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      const open = windows.find((client) => new URL(client.url).origin === self.location.origin);
      if (open !== undefined) {
        await open.focus();
        await open.navigate(url);
        return;
      }
      await self.clients.openWindow(url);
    })(),
  );
});
