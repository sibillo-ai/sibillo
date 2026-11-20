// Notices: errors say what went wrong and what to do, with the sprite holding a sign (UX-014, ADR-0111).
import { createContext, type ReactNode, useCallback, useContext, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Sprite } from "./components/Sprite";
import { Button } from "./ui";
import { Toast, Toasts } from "./ui/Toast";

export interface Notice {
  kind: "error" | "info";
  title: string;
  text?: string;
  action?: { label: string; run: () => void };
  /** Stays until the user acts on it or closes it, as a new version that is ready does (UX-040). */
  lasting?: boolean;
}

interface Shown extends Notice {
  id: number;
}

const Notices = createContext<(notice: Notice) => void>(() => undefined);

export function useNotify(): (notice: Notice) => void {
  return useContext(Notices);
}

const INFO_SECONDS = 2.6;

export function NoticeProvider({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const [shown, setShown] = useState<Shown[]>([]);
  const dismiss = useCallback((id: number) => setShown((all) => all.filter((notice) => notice.id !== id)), []);
  const notify = useCallback(
    (notice: Notice) => {
      const id = Date.now() + Math.random();
      setShown((all) => [...all.filter((other) => other.kind !== notice.kind || other.title !== notice.title), { ...notice, id }]);
      if (notice.kind === "info" && !notice.lasting) window.setTimeout(() => dismiss(id), INFO_SECONDS * 1000);
    },
    [dismiss],
  );
  const value = useMemo(() => notify, [notify]);
  return (
    <Notices.Provider value={value}>
      {children}
      <Toasts>
        {shown.map((notice) => (
          <Toast
            key={notice.id}
            role={notice.kind === "error" ? "alert" : "status"}
            leading={notice.kind === "error" ? <Sprite pose="error" className="h-16 w-14 flex-none" /> : undefined}
            title={notice.title}
            dismissLabel={t("errors.dismiss")}
            onDismiss={() => dismiss(notice.id)}
            action={
              notice.action && (
                <Button
                  size="sm"
                  onClick={() => {
                    notice.action?.run();
                    dismiss(notice.id);
                  }}
                >
                  {notice.action.label}
                </Button>
              )
            }
          >
            {notice.text}
          </Toast>
        ))}
      </Toasts>
    </Notices.Provider>
  );
}
