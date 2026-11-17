// Notifications on this device: off until the user turns them on here (UX-004, ADR-0039, ADR-0101).
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, unwrap } from "../api/client";
import { useNotify } from "../notices";
import { pushSupported, subscribe, unsubscribe } from "../push";

const NOTIFICATIONS = ["me", "notifications"] as const;
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
