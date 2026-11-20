// Messages that float above the page: gone after a moment, or when dismissed (UX-014, UX-037, ADR-0111).
import { X } from "lucide-react";
import type { ReactNode } from "react";

import { IconButton } from "./Button";

/** Where toasts show: at the top of the window, above everything else, the newest last. */
export function Toasts({ children }: { children: ReactNode }) {
  return <div className="pointer-events-none fixed inset-x-4 top-16 z-60 mx-auto mt-[env(safe-area-inset-top)] flex max-w-dialog-md flex-col gap-2">{children}</div>;
}

/** One message: a title, what to do about it, at most one action, and the button that dismisses it. */
export function Toast({
  role,
  leading,
  title,
  action,
  dismissLabel,
  onDismiss,
  children,
}: {
  /** A status is announced when there is a pause; an alert at once. */
  role: "status" | "alert";
  /** What stands before the text, such as the sprite holding its sign. */
  leading?: ReactNode;
  title: string;
  action?: ReactNode;
  dismissLabel: string;
  onDismiss: () => void;
  children?: ReactNode;
}) {
  return (
    <div role={role} className="slide pointer-events-auto flex items-center gap-3 rounded-lg border border-line bg-raised py-3 pr-3 pl-4 text-small text-ink shadow-float">
      {leading}
      <div className="min-w-0 flex-1">
        <strong className="block font-semibold">{title}</strong>
        {children && <p className="mt-px text-ink-2">{children}</p>}
        {action && <div className="mt-2">{action}</div>}
      </div>
      <IconButton label={dismissLabel} onClick={onDismiss}>
        <X aria-hidden="true" />
      </IconButton>
    </div>
  );
}
