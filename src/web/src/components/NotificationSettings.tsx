// Notifications on this device: off until the user turns them on here (UX-004, ADR-0039, ADR-0101).
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, unwrap } from "../api/client";
import { useNotify } from "../notices";
import { pushSupported, subscribe, unsubscribe } from "../push";

export const NOTIFICATIONS = ["me", "notifications"] as const;
// Set on a device where the user dismissed the sign that notifications are off (UX-033).
export const SIGN_DISMISSED = "sibillo.notificationsSignDismissed";
const SWITCH =
  "relative h-6 w-10 flex-none rounded-full bg-line-strong transition-colors peer-checked:bg-accent peer-focus-visible:outline-2 peer-focus-visible:outline-accent after:absolute after:top-0.5 after:left-0.5 after:size-5 after:rounded-full after:bg-bg after:transition-transform peer-checked:after:translate-x-4";

export function NotificationsSection() {
  const { t } = useTranslation();
  const heading = useId();
  const field = useId();
  const more = useId();
  const notify = useNotify();
  const queries = useQueryClient();
  const settings = useQuery({ queryKey: NOTIFICATIONS, queryFn: async () => unwrap(await api.GET("/me/notifications")) });
  const [busy, setBusy] = useState(false);
  const supported = pushSupported();
  const available = settings.data?.available ?? true;
  const subscribed = settings.data?.subscribed ?? false;
  const denied = supported && Notification.permission === "denied";

  async function change(on: boolean) {
    setBusy(true);
    try {
      if (on) {
        const key = settings.data?.public_key;
        if (key === undefined) return;
        const subscription = await subscribe(key);
        if (subscription === undefined) {
          notify({ kind: "error", title: t("notifications.deniedTitle"), text: t("notifications.denied") });
          return;
        }
        queries.setQueryData(NOTIFICATIONS, unwrap(await api.PUT("/me/notifications", { body: subscription })));
        // Turned on, then off again later, they show their sign again (UX-033).
        localStorage.removeItem(SIGN_DISMISSED);
      } else {
        const result = await api.DELETE("/me/notifications");
        if (!result.response.ok) throw new Error("notifications were not turned off");
        await unsubscribe();
        await queries.invalidateQueries({ queryKey: NOTIFICATIONS });
      }
    } catch {
      notify({ kind: "error", title: t("errors.title"), text: t("notifications.failed") });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby={heading} className="flex flex-col gap-3">
      <div>
        <h2 id={heading} className="mb-1 text-base font-bold">
          {t("notifications.title")}
        </h2>
        <p className="max-w-[62ch] text-sm text-muted">{t("notifications.hint")}</p>
      </div>
      {!available ? (
        <p role="note" className="max-w-[62ch] rounded-xl border border-line px-3 py-2.5 text-sm">
          {t("notifications.unavailable")}
        </p>
      ) : !supported ? (
        <p role="note" className="max-w-[62ch] rounded-xl border border-line px-3 py-2.5 text-sm">
          {t("notifications.unsupported")}
        </p>
      ) : (
        <div className="relative flex items-center justify-between gap-4 rounded-2xl border border-line bg-surface px-4 py-3">
          <span className="flex min-w-0 flex-col">
            <label htmlFor={field} className="cursor-pointer font-bold">
              {t("notifications.thisDevice")}
            </label>
            <span id={more} className="text-[12.5px] text-muted">
              {denied ? t("notifications.blocked") : t("notifications.privacy")}
            </span>
          </span>
          <span className="relative flex-none">
            <input
              id={field}
              type="checkbox"
              role="switch"
              checked={subscribed}
              disabled={busy || settings.data === undefined || (denied && !subscribed)}
              aria-describedby={more}
              onChange={(event) => void change(event.target.checked)}
              className="peer absolute inset-0 size-full cursor-pointer opacity-0 disabled:cursor-not-allowed"
            />
            <span aria-hidden="true" className={`${SWITCH} pointer-events-none block peer-disabled:opacity-50`} />
          </span>
        </div>
      )}
    </section>
  );
}

/** A lasting sign that notifications are off on this device, which turns them on, until dismissed here (UX-033). */
export function NotificationsSign() {
  const { t } = useTranslation();
  const heading = useId();
  const notify = useNotify();
  const queries = useQueryClient();
  const settings = useQuery({ queryKey: NOTIFICATIONS, queryFn: async () => unwrap(await api.GET("/me/notifications")) });
  const [dismissed, setDismissed] = useState(() => localStorage.getItem(SIGN_DISMISSED) === "1");
  const [busy, setBusy] = useState(false);
  const data = settings.data;
  if (dismissed || data === undefined || !data.available || data.subscribed) return null;
  const supported = pushSupported();
  const denied = supported && Notification.permission === "denied";

  async function turnOn() {
    setBusy(true);
    try {
      const key = data?.public_key;
      const subscription = supported && key !== undefined ? await subscribe(key) : undefined;
      if (subscription === undefined) {
        notify({ kind: "error", title: t("notifications.deniedTitle"), text: supported ? t("notifications.denied") : t("notifications.unsupported") });
        return;
      }
      queries.setQueryData(NOTIFICATIONS, unwrap(await api.PUT("/me/notifications", { body: subscription })));
      localStorage.removeItem(SIGN_DISMISSED);
    } catch {
      notify({ kind: "error", title: t("errors.title"), text: t("notifications.failed") });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby={heading} className="mx-1 flex flex-col gap-2 rounded-xl border border-line bg-surface px-3 py-2.5 text-[13px]">
      <h2 id={heading} className="font-semibold">
        {t("notifications.signTitle")}
      </h2>
      <p className="text-muted">{denied ? t("notifications.blocked") : t("notifications.signBody")}</p>
      <div className="flex flex-wrap gap-1.5">
        <button type="button" disabled={busy} onClick={() => void turnOn()} className="h-8 rounded-[10px] bg-fg px-3 font-semibold text-bg disabled:opacity-50">
          {t("notifications.turnOn")}
        </button>
        <button
          type="button"
          onClick={() => {
            localStorage.setItem(SIGN_DISMISSED, "1");
            setDismissed(true);
          }}
          className="h-8 rounded-[10px] border border-line-strong px-3 font-semibold hover:bg-hover"
        >
          {t("notifications.dismiss")}
        </button>
      </div>
    </section>
  );
}
