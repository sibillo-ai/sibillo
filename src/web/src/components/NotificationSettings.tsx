// Notifications on this device: off until the user turns them on here (UX-004, ADR-0039, ADR-0101).
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, unwrap } from "../api/client";
import { useNotify } from "../notices";
import { pushSupported, subscribe, unsubscribe } from "../push";
import { Button, Card, Notice, Page, Row, Switch } from "../ui";

export const NOTIFICATIONS = ["me", "notifications"] as const;
// Set on a device where the user dismissed the sign that notifications are off (UX-033).
export const SIGN_DISMISSED = "sibillo.notificationsSignDismissed";

export function NotificationsSection() {
  const { t } = useTranslation();
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
    <Page title={t("notifications.title")} description={t("notifications.hint")}>
      {!available ? (
        <Notice role="note">{t("notifications.unavailable")}</Notice>
      ) : !supported ? (
        <Notice role="note">{t("notifications.unsupported")}</Notice>
      ) : (
        <Card rows>
          <Row title={t("notifications.thisDevice")} htmlFor={field} description={<span id={more}>{denied ? t("notifications.blocked") : t("notifications.privacy")}</span>}>
            <Switch
              id={field}
              checked={subscribed}
              disabled={busy || settings.data === undefined || (denied && !subscribed)}
              aria-describedby={more}
              onChange={(on) => void change(on)}
            />
          </Row>
        </Card>
      )}
    </Page>
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

  // A region named by its title, as the sign always was; the notice inside it is read in place.
  return (
    <section aria-labelledby={heading} className="mx-1">
      <Notice tone="warn" role="note">
        <h2 id={heading} className="font-semibold">
          {t("notifications.signTitle")}
        </h2>
        <p>{denied ? t("notifications.blocked") : t("notifications.signBody")}</p>
        <div className="mt-2 flex flex-wrap gap-2">
          <Button size="sm" busy={busy} onClick={() => void turnOn()}>
            {t("notifications.turnOn")}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              localStorage.setItem(SIGN_DISMISSED, "1");
              setDismissed(true);
            }}
          >
            {t("notifications.dismiss")}
          </Button>
        </div>
      </Notice>
    </section>
  );
}
