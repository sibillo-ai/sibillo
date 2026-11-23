// What a notification's payload says, and nothing more: its kind and the identifiers that open the right
// conversation (UX-004, ADR-0039, ADR-0101), and the fixed text of each kind in the interface language (I18N-004,
// ADR-0135). Shared by the service worker, so it imports only the notification strings of each translation.

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

type KindTexts = Partial<Record<NotificationKind, Partial<NotificationText>>>;

export interface NotificationText {
  title: string;
  body: string;
}

// The notification strings of every translation, a few per language, so that a push needs no loading.
const TEXTS: Record<string, KindTexts | undefined> = Object.fromEntries(
  Object.entries(import.meta.glob<{ kinds?: KindTexts } | undefined>(["./locales/*.json", "!./locales/languages.json", "!./locales/sources.json"], { eager: true, import: "notifications" })).map(
    ([path, strings]) => [path.replace(/^.*\/(.+)\.json$/, "$1"), strings?.kinds],
  ),
);

/** The text of a notification of `kind` in `language`, or in English for what that language lacks. */
export function notificationText(kind: NotificationKind, language: string): NotificationText {
  const english = TEXTS["en"]?.[kind];
  const own = TEXTS[language]?.[kind];
  return { title: own?.title ?? english?.title ?? "", body: own?.body ?? english?.body ?? "" };
}
