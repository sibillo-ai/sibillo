// What a notification's payload says, and nothing more: its kind and the identifiers that open the right
// conversation (UX-004, ADR-0039, ADR-0101). Shared by the service worker, so it imports nothing.

export const NOTIFICATION_KINDS = ["run_finished", "run_failed", "approval_pending", "question_pending"] as const;

export type NotificationKind = (typeof NOTIFICATION_KINDS)[number];

export interface AppNotification {
  kind: NotificationKind;
  /** One notification per conversation: a newer one replaces an older one. */
  tag: string;
  /** Where tapping it leads, within the app. */
  url: string;
}

const ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function isKind(value: unknown): value is NotificationKind {
  return typeof value === "string" && (NOTIFICATION_KINDS as readonly string[]).includes(value);
}

/** The notification a push asks for, or `undefined` for anything that is not one. */
export function notificationOf(payload: unknown): AppNotification | undefined {
  if (typeof payload !== "object" || payload === null) return undefined;
  const { kind, conversation_id: conversation, run_id: run } = payload as Record<string, unknown>;
  if (!isKind(kind) || typeof conversation !== "string" || typeof run !== "string") return undefined;
  if (!ID.test(conversation) || !ID.test(run)) return undefined;
  return { kind, tag: conversation, url: `/c/${conversation}` };
}
