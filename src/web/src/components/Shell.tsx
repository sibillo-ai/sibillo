import { LogOut, Menu as MenuIcon, Plus, SlidersHorizontal, X } from "lucide-react";
import { createContext, type CSSProperties, useCallback, useContext } from "react";
import { useTranslation } from "react-i18next";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router";

import type { User } from "../api/client";
import { formatMoney, useUsage } from "../costs";
import { useBusy } from "../busy";
import { useSignOut } from "../session";
import { useLeavingTemporary } from "../temporary";
import { useChangeStream } from "../changes";
import { Avatar, buttonClass, cx, IconButton, NAV_ITEM } from "../ui";
import { ConversationList } from "./ConversationList";
import { NotificationsSign } from "./NotificationSettings";
import { ResizeHandle, usePanelWidth } from "./ResizeHandle";
import { HandsFreeOverlay, VoiceProvider } from "../voice";
import { Sprite } from "./Sprite";

/** What opens the conversation list on a phone, for the top bar of each page (UX-039). */
const MenuContext = createContext<() => void>(() => undefined);

/** Whether the conversation list is open on a phone: it is a step of the history, which the device's Back closes (UX-039). */
export function menuOpen(state: unknown): boolean {
  return typeof state === "object" && state !== null && (state as { menu?: unknown }).menu === true;
}

/** The function that opens the conversation list on a phone. */
export function useOpenMenu(): () => void {
  return useContext(MenuContext);
}

/** The button of a phone's top bar that opens the conversation list (UX-039). */
export function MenuButton() {
  const { t } = useTranslation();
  const open = useOpenMenu();
  return (
    <span className="flex flex-none md:hidden">
      <IconButton label={t("shell.openMenu")} aria-expanded={false} onClick={open}>
        <MenuIcon aria-hidden="true" />
      </IconButton>
    </span>
  );
}

/**
 * The conversation list beside the conversation; on phones the list is a page of its own, as wide as the screen,
 * and each page has a top bar with the button that opens it (ADR-0111, UX-039).
 */
export function Shell({ me }: { me: User }) {
  const { t } = useTranslation();
  // The sidebar starts with the width of the design language, and the user may resize it (UX-021).
  const list = usePanelWidth("sibillo.listWidth", 272, 220, 440);
  const signOut = useSignOut();
  const { busy, run } = useBusy();
  const location = useLocation();
  const navigate = useNavigate();
  useLeavingTemporary();
  // What changes elsewhere, such as a conversation a task started, shows at once (UX-032).
  useChangeStream();
  // On a phone the open list is an entry of the history over the page it was opened from: Back closes it, and
  // choosing a conversation, or the settings, leaves it behind as the step they go back to (UX-039).
  const open = menuOpen(location.state);
  const openMenu = useCallback(() => {
    void navigate({ pathname: location.pathname, search: location.search }, { state: { menu: true } });
  }, [navigate, location.pathname, location.search]);
  const closeMenu = () => void navigate(-1);

  return (
    <VoiceProvider>
      <MenuContext value={openMenu}>
        <div className="flex h-full overflow-hidden bg-canvas text-ink">
          <nav
            aria-label={t("shell.conversations")}
            style={{ "--list-width": `${list.width}px` } as CSSProperties}
            className={cx(
              open ? "flex" : "hidden",
              "fixed inset-0 z-40 w-full flex-none flex-col gap-3 bg-sunken px-3 pt-safe pb-safe md:relative md:inset-auto md:flex md:w-(--list-width) md:border-r md:border-line",
            )}
          >
            <ResizeHandle label={t("shell.resizeList")} side="right" panel={list} className="hidden md:block" />
            <div className="flex h-10 flex-none items-center gap-2 pl-1">
              <Link to="/" className="flex min-w-0 flex-1 items-center gap-2 rounded-sm text-reading font-semibold">
                <Sprite pose="waiting" head className="size-7 flex-none" />
                <span className="truncate">{t("app.name")}</span>
              </Link>
              <span className="flex flex-none md:hidden">
                <IconButton label={t("shell.closeMenu")} onClick={closeMenu}>
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
              {/* From the open list on a phone, the settings lead back to it (UX-039). */}
              <NavLink to="/settings" state={open ? { fromMenu: true } : undefined} className={NAV_ITEM}>
                <SlidersHorizontal aria-hidden="true" />
                <span className="min-w-0 flex-1 truncate">{t("shell.settings")}</span>
              </NavLink>
              <div className="flex items-center gap-2 pt-2 pl-2">
                <Avatar name={me.display_name} />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-body font-semibold">{me.display_name}</div>
                  <UsageSummary />
                </div>
                <IconButton label={t("shell.signOut")} busy={busy("signOut")} onClick={() => void run("signOut", signOut)}>
                  <LogOut aria-hidden="true" />
                </IconButton>
              </div>
            </div>
          </nav>
          <div className="flex min-w-0 flex-1 flex-col">
            <main className="relative flex min-h-0 flex-1 flex-col">
              <Outlet />
              <HandsFreeOverlay />
            </main>
          </div>
        </div>
      </MenuContext>
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
