import { LogOut, Menu as MenuIcon, Plus, SlidersHorizontal, X } from "lucide-react";
import { type CSSProperties, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, NavLink, Outlet, useLocation } from "react-router";

import type { User } from "../api/client";
import { formatMoney, useUsage } from "../costs";
import { useSignOut } from "../session";
import { useLeavingTemporary } from "../temporary";
import { useChangeStream } from "../changes";
import { Avatar, buttonClass, cx, IconButton, NAV_ITEM } from "../ui";
import { ConversationList } from "./ConversationList";
import { NotificationsSign } from "./NotificationSettings";
import { ResizeHandle, usePanelWidth } from "./ResizeHandle";
import { HandsFreeOverlay, VoiceProvider } from "../voice";
import { Sprite } from "./Sprite";

/** The conversation list beside the conversation; on phones the list slides over it (ADR-0111). */
export function Shell({ me }: { me: User }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  // The sidebar starts with the width of the design language, and the user may resize it (UX-021).
  const list = usePanelWidth("sibillo.listWidth", 272, 220, 440);
  const signOut = useSignOut();
  const location = useLocation();
  useLeavingTemporary();
  // What changes elsewhere, such as a conversation a task started, shows at once (UX-032).
  useChangeStream();
  // Close the list on phones after choosing a conversation.
  const [shownFor, setShownFor] = useState(location.pathname);
  if (shownFor !== location.pathname) {
    setShownFor(location.pathname);
    setOpen(false);
  }

  return (
    <VoiceProvider>
      <div className="flex h-full overflow-hidden bg-canvas text-ink">
        {open && <div className="fixed inset-0 z-30 bg-scrim md:hidden" aria-hidden="true" onClick={() => setOpen(false)} />}
        <nav
          aria-label={t("shell.conversations")}
          style={{ "--list-width": `${list.width}px` } as CSSProperties}
          className={cx(
            open ? "flex" : "hidden",
            "fixed inset-y-0 left-0 z-40 w-sidebar max-w-5/6 flex-none flex-col gap-3 border-r border-line bg-sunken px-3 pt-safe pb-safe shadow-above md:relative md:flex md:w-(--list-width) md:max-w-none md:shadow-none",
          )}
        >
          <ResizeHandle label={t("shell.resizeList")} side="right" panel={list} className="hidden md:block" />
          <div className="flex h-10 flex-none items-center gap-2 pl-1">
            <Link to="/" className="flex min-w-0 flex-1 items-center gap-2 rounded-sm text-reading font-semibold">
              <Sprite pose="waiting" head className="size-7 flex-none" />
              <span className="truncate">{t("app.name")}</span>
            </Link>
            <span className="flex flex-none md:hidden">
              <IconButton label={t("shell.closeMenu")} onClick={() => setOpen(false)}>
                <X aria-hidden="true" />
              </IconButton>
            </span>
          </div>
          <Link to="/" className={buttonClass({ block: true })}>
            <Plus aria-hidden="true" />
            {t("shell.newChat")}
          </Link>
          <ConversationList />
          <NotificationsSign />
          <div className="flex flex-none flex-col">
            <NavLink to="/settings" className={NAV_ITEM}>
              <SlidersHorizontal aria-hidden="true" />
              <span className="min-w-0 flex-1 truncate">{t("shell.settings")}</span>
            </NavLink>
            <div className="flex items-center gap-2 pt-2 pl-2">
              <Avatar name={me.display_name} />
              <div className="min-w-0 flex-1">
                <div className="truncate text-body font-semibold">{me.display_name}</div>
                <UsageSummary />
              </div>
              <IconButton label={t("shell.signOut")} onClick={() => void signOut()}>
                <LogOut aria-hidden="true" />
              </IconButton>
            </div>
          </div>
        </nav>
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-14 flex-none items-center gap-2 pr-4 pl-safe md:hidden">
            <IconButton label={t("shell.openMenu")} aria-expanded={open} onClick={() => setOpen(true)}>
              <MenuIcon aria-hidden="true" />
            </IconButton>
            <span className="min-w-0 flex-1 truncate text-body font-semibold">{t("app.name")}</span>
          </header>
          <main className="relative flex min-h-0 flex-1 flex-col">
            <Outlet />
            <HandsFreeOverlay />
          </main>
        </div>
      </div>
    </VoiceProvider>
  );
}

/** The user's spend over the last 24 hours and 30 days, as a caption under their name (UX-008). */
function UsageSummary() {
  const { t } = useTranslation();
  const usage = useUsage();
  if (!usage.data) return null;
  const rows: [string, string][] = [
    [t("usage.day"), formatMoney(usage.data.last_24_hours)],
    [t("usage.month"), formatMoney(usage.data.last_30_days)],
  ];
  return (
    <dl className="flex flex-wrap gap-x-2 text-caption text-ink-3 tabular-nums">
      {rows.map(([label, value]) => (
        <div key={label} className="flex gap-1">
          <dt>{label}</dt>
          <dd className="font-medium text-ink-2">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
